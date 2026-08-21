"""Vector store abstraction.

- local (default): embeddings stored on DocumentChunk rows; retrieval scans
  chunks in SQL and ranks by cosine similarity in numpy. Simple, zero
  external services, appropriate for the corpus sizes of this project.
- qdrant: if VECTOR_BACKEND=qdrant and the client package is installed,
  embeddings are mirrored into a Qdrant collection instead.
"""
import logging

import numpy as np

logger = logging.getLogger(__name__)


def _normalize(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def retrieve(query_embedding, top_k=5, document_ids=None):
    """Return [(chunk_id, score), ...] best matches for the query vector.

    Raises RuntimeError if no chunks are indexed.
    """
    from django.conf import settings
    from kb.models import DocumentChunk

    chunks = DocumentChunk.objects.exclude(embedding=[]).select_related("document")
    if document_ids:
        chunks = chunks.filter(document_id__in=document_ids)
    rows = list(chunks.values("id", "embedding"))
    if not rows:
        raise RuntimeError("The knowledge base is empty. Upload and index documents first.")

    if settings.VECTOR_BACKEND == "qdrant" and settings.VECTOR_DB_URL:
        return _retrieve_qdrant(query_embedding, top_k, document_ids)

    matrix = _normalize(np.asarray([r["embedding"] for r in rows], dtype=np.float32))
    query = _normalize(np.asarray(query_embedding, dtype=np.float32).reshape(1, -1))
    scores = (matrix @ query.T).ravel()
    order = np.argsort(-scores)[:top_k]
    return [(rows[i]["id"], float(scores[i])) for i in order]


def _retrieve_qdrant(query_embedding, top_k, document_ids):
    """Mirror retrieval into Qdrant when configured (settings.VECTOR_BACKEND=qdrant)."""
    from django.conf import settings

    try:
        from qdrant_client import QdrantClient
    except ImportError:
        logger.warning("qdrant-client not installed; falling back to local retrieval.")
        return _retrieve_local_direct(query_embedding, top_k, document_ids)

    client = QdrantClient(url=settings.VECTOR_DB_URL, api_key=settings.VECTOR_DB_API_KEY or None)
    hits = client.search(
        collection_name="aimhra_kb",
        query_vector=np.asarray(query_embedding, dtype=np.float32).tolist(),
        limit=top_k,
    )
    return [(hit.id, hit.score) for hit in hits]


def _retrieve_local_direct(query_embedding, top_k, document_ids):
    """Local cosine retrieval without re-entering the backend dispatch."""
    from kb.models import DocumentChunk

    chunks = DocumentChunk.objects.exclude(embedding=[]).select_related("document")
    if document_ids:
        chunks = chunks.filter(document_id__in=document_ids)
    rows = list(chunks.values("id", "embedding"))
    if not rows:
        raise RuntimeError("The knowledge base is empty. Upload and index documents first.")
    matrix = _normalize(np.asarray([r["embedding"] for r in rows], dtype=np.float32))
    query = _normalize(np.asarray(query_embedding, dtype=np.float32).reshape(1, -1))
    scores = (matrix @ query.T).ravel()
    order = np.argsort(-scores)[:top_k]
    return [(rows[i]["id"], float(scores[i])) for i in order]
