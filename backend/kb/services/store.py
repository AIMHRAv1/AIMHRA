"""Vector store abstraction for local cosine retrieval and optional Qdrant."""
import logging

import numpy as np

logger = logging.getLogger(__name__)


def _qdrant_collection():
    from django.conf import settings

    if settings.EMBEDDING_BACKEND == "local":
        return "aimhra_kb_local_tfidf"
    if settings.EMBEDDING_BACKEND == "openai":
        return "aimhra_kb_openai_text_embedding_3_small"
    raise RuntimeError(f"Unsupported embedding backend: {settings.EMBEDDING_BACKEND}")


def _normalize(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def retrieve(query_embedding, top_k=5, document_ids=None):
    """Return [(chunk_id, score), ...] or raise when index state is invalid."""
    from django.conf import settings
    from kb.models import DocumentChunk

    chunks = DocumentChunk.objects.exclude(embedding=[]).select_related("document")
    if document_ids:
        chunks = chunks.filter(document_id__in=document_ids)
    rows = list(chunks.values("id", "embedding", "embedding_backend"))
    if not rows:
        raise RuntimeError("The knowledge base is empty. Upload and index documents first.")
    if any(row["embedding_backend"] != settings.EMBEDDING_BACKEND for row in rows):
        raise RuntimeError("Stored knowledge vectors use a different embedding backend; reindex the knowledge base.")

    if settings.VECTOR_BACKEND == "qdrant":
        return _retrieve_qdrant(query_embedding, top_k, document_ids)
    if settings.VECTOR_BACKEND != "local":
        raise RuntimeError(f"Unsupported vector backend: {settings.VECTOR_BACKEND}")

    matrix = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
    query = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[1] != query.shape[1]:
        raise RuntimeError("Stored vectors do not match the query embedding dimension; reindex the knowledge base.")
    matrix = _normalize(matrix)
    query = _normalize(query)
    scores = (matrix @ query.T).ravel()
    order = np.argsort(-scores)[:top_k]
    return [(rows[i]["id"], float(scores[i])) for i in order]


def _qdrant_client():
    from django.conf import settings

    if not settings.VECTOR_DB_URL:
        raise RuntimeError("Qdrant is selected but VECTOR_DB_URL is not configured.")
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise RuntimeError("Qdrant is selected but qdrant-client is not installed.") from exc
    return QdrantClient(url=settings.VECTOR_DB_URL, api_key=settings.VECTOR_DB_API_KEY or None)


def _ensure_qdrant_collection(client, dimension):
    from qdrant_client.models import Distance, VectorParams

    collection_name = _qdrant_collection()
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        return
    collection = client.get_collection(collection_name)
    vectors = collection.config.params.vectors
    if not isinstance(vectors, dict) and vectors.size != dimension:
        raise RuntimeError(
            "The Qdrant collection dimension does not match the active embedding model; "
            "recreate the AIMHRA collection and reindex."
        )
    if isinstance(vectors, dict):
        raise RuntimeError("Named Qdrant vectors are unsupported; configure a single-vector collection.")


def sync_qdrant_index():
    """Replace this application's Qdrant points with the complete database index."""
    from qdrant_client.models import (
        FieldCondition,
        Filter,
        FilterSelector,
        MatchValue,
        PointStruct,
    )
    from kb.models import DocumentChunk

    client = _qdrant_client()
    collection_name = _qdrant_collection()
    rows = list(
        DocumentChunk.objects.exclude(embedding=[])
        .select_related("document")
        .order_by("id")
    )
    if rows:
        dimensions = {len(row.embedding) for row in rows}
        if len(dimensions) != 1 or 0 in dimensions:
            raise RuntimeError("Stored knowledge vectors have inconsistent dimensions; reindex the knowledge base.")
        _ensure_qdrant_collection(client, dimensions.pop())
    elif client.collection_exists(collection_name):
        client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(
                filter=Filter(must=[
                    FieldCondition(key="app", match=MatchValue(value="aimhra"))
                ])
            ),
            wait=True,
        )
        return
    else:
        return

    client.delete(
        collection_name=collection_name,
        points_selector=FilterSelector(
            filter=Filter(must=[
                FieldCondition(key="app", match=MatchValue(value="aimhra"))
            ])
        ),
        wait=True,
    )
    points = [
        PointStruct(
            id=row.id,
            vector=row.embedding,
            payload={
                "app": "aimhra",
                "chunk_id": row.id,
                "document_id": row.document_id,
                "document_title": row.document.title,
                "issuing_organization": row.document.issuing_organization,
                "source": row.document.source_url,
                "page_number": row.page_number,
                "section": row.section,
                "chunk_index": row.chunk_index,
            },
        )
        for row in rows
    ]
    for offset in range(0, len(points), 256):
        client.upsert(
            collection_name=collection_name,
            points=points[offset:offset + 256],
            wait=True,
        )


def _retrieve_qdrant(query_embedding, top_k, document_ids):
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    client = _qdrant_client()
    collection_name = _qdrant_collection()
    if not client.collection_exists(collection_name):
        raise RuntimeError("The Qdrant knowledge index is missing; reindex the knowledge base.")

    query_filter = None
    if document_ids:
        query_filter = Filter(must=[
            FieldCondition(key="document_id", match=MatchAny(any=list(document_ids)))
        ])
    vector = np.asarray(query_embedding, dtype=np.float32).tolist()
    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=collection_name,
            query=vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        hits = response.points
    else:
        hits = client.search(
            collection_name=collection_name,
            query_vector=vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
    results = []
    for hit in hits:
        payload = hit.payload or {}
        chunk_id = payload.get("chunk_id", hit.id)
        if chunk_id is not None:
            results.append((int(chunk_id), float(hit.score)))
    if not results:
        raise RuntimeError("The Qdrant knowledge index returned no matching indexed chunks.")
    return results
