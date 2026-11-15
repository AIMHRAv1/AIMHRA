"""Indexing pipeline: extract -> chunk -> embed -> persist chunk vectors."""
import logging
from datetime import datetime, timezone

from django.db import transaction

from kb.models import DocumentChunk, KnowledgeDocument
from kb.services import embeddings, ingestion

logger = logging.getLogger(__name__)


@transaction.atomic
def index_document(document):
    """(Re)index one document: clear old chunks, embed new ones.

    The local TF-IDF backend is fitted over ALL chunks of ALL documents, so
    every document is re-embedded on each index operation. Corpus sizes here
    are small; for large corpora switch EMBEDDING_BACKEND=openai.
    """
    chunks, meta = ingestion.chunk_document(document)
    if not chunks:
        raise ValueError("No extractable text found in the document.")

    DocumentChunk.objects.filter(document=document).delete()
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                document=document,
                chunk_index=i,
                text=chunk,
                page_number=page_number,
                section=section,
            )
            for i, (chunk, page_number, section) in enumerate(chunks)
        ]
    )
    corpus_chunks = list(DocumentChunk.objects.order_by("id"))
    corpus_texts = [chunk.text for chunk in corpus_chunks]
    embeddings.fit_corpus(corpus_texts)
    vectors = embeddings.embed_texts(corpus_texts)
    for chunk, vector in zip(corpus_chunks, vectors):
        chunk.embedding = vector.tolist()
        chunk.embedding_backend = embeddings.get_backend()
    DocumentChunk.objects.bulk_update(
        corpus_chunks, ["embedding", "embedding_backend"], batch_size=200
    )

    document.chunk_count = len(chunks)
    document.indexed_at = datetime.now(timezone.utc)
    document.save(update_fields=["chunk_count", "indexed_at", "updated_at"])
    from django.conf import settings

    if settings.VECTOR_BACKEND == "qdrant":
        from kb.services import store

        store.sync_qdrant_index()
    logger.info("Indexed %s: %d chunks", document.title, len(chunks))
    return {"chunks": len(chunks), "meta": meta}
