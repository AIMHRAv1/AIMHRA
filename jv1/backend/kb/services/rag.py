"""RAG retrieval: question -> embedding -> top chunks -> grounded context
with source attribution. No LLM here — see chat.services for generation."""
import logging

logger = logging.getLogger(__name__)

TOP_K = 5
MIN_SCORE = 0.05  # below this a match is considered too weak to cite


def retrieve_context(question, top_k=TOP_K):
    """Return dict with `chunks` [{document, section, text, score}] or None
    when the knowledge base is empty/unavailable. Never raises."""
    from kb.services import embeddings, store

    try:
        query_vector = embeddings.embed_texts([question])[0]
    except Exception:
        logger.exception("Query embedding failed")
        return None
    try:
        hits = store.retrieve(query_vector, top_k=top_k)
    except RuntimeError:
        return None
    except Exception:
        logger.exception("Vector retrieval failed")
        return None

    from kb.models import DocumentChunk

    chunks = []
    for chunk_id, score in hits:
        if score < MIN_SCORE:
            continue
        chunk = DocumentChunk.objects.select_related("document").filter(pk=chunk_id).first()
        if not chunk:
            continue
        chunks.append(
            {
                "document_id": chunk.document_id,
                "document_title": chunk.document.title,
                "source_url": chunk.document.source_url,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text[:1200],
                "score": round(float(score), 4),
            }
        )
    return {"chunks": chunks}
