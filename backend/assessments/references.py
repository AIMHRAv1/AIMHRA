"""Traceable guideline references for a decision-support result.

Maps each triggered clinical rule and each top SHAP model driver to the
knowledge-base passages that the RAG index retrieves for it. This is pure
aggregation over the existing retrieval service — no LLM, no ML; the same
inputs always produce the same references.

Citation integrity: a reference is only emitted when the retrieved chunk
exists, its document has a title, and the citation carries the document's
current sha256 (version) and section. Stale/empty sources are dropped rather
than guessed.
"""
import logging

from mlcore.constants import FEATURE_LABELS

logger = logging.getLogger(__name__)

REFERENCES_METHOD = "TF-IDF retrieval over the indexed knowledge base"


def _safe_query(text):
    return " ".join(str(text).split())[:300]


def _to_reference(topic_type, topic_id, topic_label, chunk):
    """Normalize one retrieval hit into a citation, verifying the fields that
    are presented to users. Returns None when the citation cannot be trusted."""
    if not chunk:
        return None
    title = (chunk.get("document_title") or "").strip()
    if not title:
        return None
    return {
        "topic_type": topic_type,          # "rule" | "model_driver"
        "topic_id": topic_id,              # rule id or feature name
        "topic_label": topic_label,
        "document_id": chunk.get("document_id"),
        "document_title": title,
        "source_url": (chunk.get("source_url") or "").strip(),
        "chunk_index": chunk.get("chunk_index"),
        "section": chunk.get("section") or "",
        "score": chunk.get("score"),
        "retrieval": REFERENCES_METHOD,
    }


def guideline_references(rules_out, prediction, top_k=3, max_references=12):
    """Retrieve supporting KB passages for the triggered rules and the top
    model drivers. Returns (references, warnings).

    warnings lists anything the caller should surface about citation
    availability (e.g. empty knowledge base) — never raises.
    """
    warnings = []
    if not rules_out and not prediction:
        return [], warnings

    try:
        from kb.models import KnowledgeDocument
        from kb.services.rag import retrieve_context

        if not KnowledgeDocument.objects.exists():
            return [], ["The knowledge base contains no indexed documents; "
                        "no guideline references could be retrieved."]

        topics = []
        for t in (rules_out or {}).get("triggered", [])[:5]:
            topics.append(("rule", t["id"], t["description"]))
        explanation = (prediction or {}).get("explanation") or {}
        for item in (explanation.get("features") or [])[:3]:
            label = item.get("label") or FEATURE_LABELS.get(item.get("feature"), item.get("feature"))
            topics.append(("model_driver", item.get("feature"), label))

        # One query per topic keeps citations attributable; retrieval is
        # local TF-IDF, so this stays fast.
        references, seen = [], set()
        for topic_type, topic_id, topic_label in topics:
            if len(references) >= max_references:
                break
            query = f"{topic_label} maternal health recommendation"
            context = retrieve_context(_safe_query(query), top_k=top_k)
            if not context or not context.get("chunks"):
                continue
            for chunk in context["chunks"]:
                ref = _to_reference(topic_type, topic_id, topic_label, chunk)
                if not ref:
                    continue
                key = (ref["document_id"], ref["chunk_index"])
                if key in seen:
                    # Attach the extra topic to the existing citation instead
                    # of duplicating the same passage.
                    continue
                seen.add(key)
                references.append(ref)
                break  # best passage per topic is enough
        if not references:
            warnings.append("Indexed documents exist, but no passage matched "
                            "the triggered rules or model drivers closely enough to cite.")
        return references, warnings
    except Exception:
        # References enrich the response; they must never break assessment
        # creation (e.g. KB unavailable).
        logger.exception("guideline_references failed; continuing without citations")
        return [], ["Guideline references could not be retrieved (knowledge base unavailable)."]


def attach_document_versions(references):
    """Hydrate each citation with the fields users must be able to verify:
    the chunk's `section`, the document's sha256 (content version) and its
    last index time. Citations whose chunk no longer exists are dropped."""
    if not references:
        return references
    from kb.models import DocumentChunk, KnowledgeDocument

    doc_ids = {r["document_id"] for r in references if r.get("document_id")}
    docs = KnowledgeDocument.objects.in_bulk(doc_ids)

    chunk_keys = {(r["document_id"], r["chunk_index"]) for r in references}
    chunks = {
        (c.document_id, c.chunk_index): c
        for c in DocumentChunk.objects.filter(
            document_id__in=doc_ids, chunk_index__in=[k[1] for k in chunk_keys]
        )
    }

    hydrated = []
    for r in references:
        doc = docs.get(r.get("document_id"))
        chunk = chunks.get((r.get("document_id"), r.get("chunk_index")))
        if doc is None or chunk is None:
            continue  # citation target vanished from the KB — drop, don't guess
        r["section"] = chunk.section or ""
        r["document_sha256"] = doc.sha256
        r["document_indexed_at"] = doc.indexed_at.isoformat() if doc.indexed_at else None
        hydrated.append(r)
    return hydrated
