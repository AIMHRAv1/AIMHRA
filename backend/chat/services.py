"""Educational chat pipeline: message -> RAG retrieval -> local LLM, with an
extractive knowledge-base fallback when the local model is unavailable.

Assessment rules and recorded vital signs are handled by the assessment
workflow, not injected into chat replies.
"""
from audit.services import log_event
from chat.llm import FALLBACK_NO_LLM, KB_INTRO, compose_extractive, generate_answer, looks_like_refusal
from chat.models import ChatMessage, ChatSession
from kb.services import rag

CHAT_DISCLAIMER = (
    "This assistant provides general educational information, not medical diagnosis or "
    "treatment. Consult a healthcare professional for personal medical advice."
)


def respond(session, user_message_text, request=None):
    """Generate an educational response and persist both messages."""
    ChatMessage.objects.create(session=session, role=ChatMessage.ROLE_USER, content=user_message_text)

    # 1) RAG retrieval with source attribution.
    context = rag.retrieve_context(user_message_text)

    # 2) LLM generation with graceful fallback.
    history = [
        {"role": m.role, "content": m.content}
        for m in ChatMessage.objects.filter(session=session)
        .exclude(role=ChatMessage.ROLE_ASSISTANT, generation_mode="escalation")
        .order_by("created_at", "id")[:12]
    ]
    # Drop the final user turn — it is passed as `question` explicitly.
    history = history[:-1]

    answer, mode = generate_answer(
        user_message_text, context_chunks=context["chunks"] if context else None,
        history=history,
    )
    # A blanket model refusal is treated as a generation failure and replaced
    # with the extractive knowledge-base answer.
    if answer is not None and looks_like_refusal(answer):
        answer = None

    if answer is None:
        if context and context["chunks"]:
            extractive = compose_extractive(user_message_text, context["chunks"], intro=KB_INTRO)
            if extractive:
                answer = extractive
            else:
                excerpts = "\n\n---\n\n".join(
                    f"[{c['document_title']} — chunk {c['chunk_index']}] {c['text'][:500]}"
                    for c in context["chunks"]
                )
                answer = f"{FALLBACK_NO_LLM}\n\nRelevant knowledge-base excerpts:\n\n{excerpts}"
            mode = "rag_only_fallback"
        else:
            answer = (
                f"{FALLBACK_NO_LLM}\n\nNo indexed knowledge matched your question. "
                "Please rephrase it or contact your healthcare provider."
            )
            mode = "no_llm_configured"

    sources = [
        {
            "document_title": c["document_title"],
            "source_url": c["source_url"],
            "chunk_index": c["chunk_index"],
            "score": c["score"],
        }
        for c in (context["chunks"] if context else [])
    ]

    message = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.ROLE_ASSISTANT,
        content=answer,
        escalation={"escalate": False},
        sources=sources,
        generation_mode=mode,
    )
    log_event(request, "CHAT_ACCESS", target_type="chat_session", target_id=str(session.id),
              detail={"mode": mode, "sources": len(sources)})
    return _serialize(message)


def _serialize(message):
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "escalation": message.escalation,
        "sources": message.sources,
        "generation_mode": message.generation_mode,
        "created_at": message.created_at.isoformat(),
        "disclaimer": CHAT_DISCLAIMER,
    }
