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
    text, meta = ingestion.extract_text(document)
    chunks = ingestion.chunk_text(text)
    if not chunks:
        raise ValueError("No extractable text found in the document.")

    all_texts = [c for c in chunks]
    # Fit over the entire corpus (this document + all other documents).
    other_texts = list(
        DocumentChunk.objects.exclude(document=document).values_list("text", flat=True)
    )
    embeddings.fit_corpus(other_texts + all_texts)

    DocumentChunk.objects.filter(document=document).delete()
    vectors = embeddings.embed_texts(chunks)
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                document=document,
                chunk_index=i,
                text=chunk,
                embedding=vector.tolist(),
                embedding_backend=embeddings.get_backend(),
            )
            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
    )
    # Re-embed other documents' chunks with the refitted vectorizer.
    if other_texts:
        _reembed_others(document)

    document.chunk_count = len(chunks)
    document.indexed_at = datetime.now(timezone.utc)
    document.save(update_fields=["chunk_count", "indexed_at", "updated_at"])
    logger.info("Indexed %s: %d chunks", document.title, len(chunks))
    return {"chunks": len(chunks), "meta": meta}


def _reembed_others(exclude_document):
    from kb.models import DocumentChunk

    others = list(DocumentChunk.objects.exclude(document=exclude_document))
    if not others:
        return
    vectors = embeddings.embed_texts([c.text for c in others])
    for chunk, vector in zip(others, vectors):
        chunk.embedding = vector.tolist()
    DocumentChunk.objects.bulk_update(others, ["embedding"], batch_size=200)
