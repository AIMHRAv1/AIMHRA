"""RAG retrieval: question -> embedding -> top chunks -> grounded context
with source attribution. No LLM here — see chat.services for generation."""
import logging
import re

logger = logging.getLogger(__name__)

TOP_K = 5
MIN_SCORE = 0.05  # below this a match is considered too weak to cite
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a", "about", "after", "and", "are", "can", "do", "does", "for", "from",
    "how", "i", "is", "me", "of", "on", "please", "tell", "the", "this", "to",
    "what", "when", "with", "would",
}
_QUERY_EXPANSIONS = {
    "hypertension": (
        "hypertensive disorders", "high blood pressure", "raised blood pressure",
        "blood pressure", "pre-eclampsia", "preeclampsia", "proteinuria", "screening",
    ),
    "preeclampsia": ("pre-eclampsia", "hypertension", "proteinuria", "blood pressure"),
    "antenatal": ("prenatal", "antenatal care", "pregnancy care", "ANC"),
    "danger signs": (
        "warning signs", "vaginal bleeding", "severe headache", "convulsions",
        "blurred vision", "difficulty breathing", "decreased fetal movement",
    ),
}


def _retrieval_terms(question):
    normalized = question.lower().replace("pre-eclampsia", "preeclampsia")
    expanded = []
    for concept, terms in _QUERY_EXPANSIONS.items():
        if concept in normalized:
            expanded.extend(terms)
    original_terms = [
        term for term in _TOKEN_RE.findall(normalized) if term not in _STOP_WORDS
    ]
    expansion_terms = [
        term for term in _TOKEN_RE.findall(" ".join(expanded)) if term not in _STOP_WORDS
    ]
    return original_terms, expansion_terms, expanded


def _lexical_relevance(chunk_text, original_terms, expansion_terms):
    chunk_terms = set(_TOKEN_RE.findall(chunk_text.lower()))
    original = set(original_terms)
    expansion = set(expansion_terms) - original
    original_score = len(original & chunk_terms) / len(original) if original else 0.0
    expansion_score = len(expansion & chunk_terms) / len(expansion) if expansion else 0.0
    return (0.75 * original_score) + (0.25 * expansion_score)


def retrieve_context(question, top_k=TOP_K):
    """Return dict with `chunks` [{document, section, text, score}] or None
    when the knowledge base is empty/unavailable. Never raises."""
    from kb.services import embeddings, store
    from kb.models import DocumentChunk

    if not DocumentChunk.objects.exists():
        logger.info("RAG retrieval skipped because the knowledge base is empty")
        return None
    if not DocumentChunk.objects.exclude(embedding=[]).exists():
        logger.error("RAG chunks exist without stored vectors; reindex the knowledge base")
        return None

    original_terms, expansion_terms, expanded_phrases = _retrieval_terms(question)
    retrieval_query = " ".join([question, *expanded_phrases])
    try:
        query_vector = embeddings.embed_texts([retrieval_query])[0]
    except Exception:
        logger.exception("Query embedding failed")
        return None
    try:
        candidate_count = max(top_k * 8, 40)
        hits = store.retrieve(query_vector, top_k=candidate_count)
    except RuntimeError as exc:
        logger.warning("RAG retrieval unavailable: %s", exc)
        return None
    except Exception:
        logger.exception("Vector retrieval failed")
        return None

    ranked_chunks = []
    for chunk_id, vector_score in hits:
        chunk = DocumentChunk.objects.select_related("document").filter(pk=chunk_id).first()
        if not chunk:
            continue
        lexical_score = _lexical_relevance(chunk.text, original_terms, expansion_terms)
        score = (0.6 * max(0.0, float(vector_score))) + (0.4 * lexical_score)
        ranked_chunks.append((score, chunk))

    ranked_chunks.sort(key=lambda result: result[0], reverse=True)
    chunks = []
    for score, chunk in ranked_chunks:
        if score < MIN_SCORE:
            continue
        chunks.append({
                "document_id": chunk.document_id,
                "document_title": chunk.document.title,
                "issuing_organization": chunk.document.issuing_organization,
                "source_url": chunk.document.source_url,
                "source": chunk.document.source_url,
                "page_number": chunk.page_number,
                "section": chunk.section,
                "chunk_id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text[:1200],
                "score": round(float(score), 4),
            })
        if len(chunks) == top_k:
            break
    return {"chunks": chunks}
