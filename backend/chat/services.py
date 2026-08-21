"""Chat pipeline (requirements #20-23, #54):

    message -> emergency rule engine
                   |-- triggered -> escalation answer (LLM bypassed entirely)
                   '-- clear -----> patient context -> RAG retrieval -> LLM
                                                                       '-- unavailable -> safe fallback
"""
import logging

from assessments.rules import evaluate as rules_evaluate
from assessments.rules.keywords import detect_symptoms
from audit.services import log_event
from chat.llm import FALLBACK_NO_LLM, generate_answer, llm_configured
from chat.models import ChatMessage, ChatSession
from kb.services import rag

logger = logging.getLogger(__name__)

CHAT_DISCLAIMER = (
    "This assistant provides general educational information, not medical diagnosis or "
    "treatment. Emergency warnings always take priority. Consult a healthcare professional "
    "for medical advice."
)


def _patient_context(patient_profile):
    """Minimal, authorized context for personalization (no sensitive history)."""
    from assessments.models import Prediction

    latest = (
        Prediction.objects.filter(assessment__patient=patient_profile)
        .select_related("assessment")
        .order_by("-assessment__visit_date", "-id")
        .first()
    )
    if not latest:
        return None
    parts = [
        f"latest assessed risk category: {latest.risk_level} "
        f"(model confidence {round(latest.probability * 100)}%)"
    ]
    if latest.assessment.gestational_week:
        parts.append(f"reported gestational week at last assessment: {latest.assessment.gestational_week}")
    return "; ".join(parts)


def respond(session, user_message_text, request=None):
    """Process one user message through the safety pipeline and persist both
    messages. Returns the assistant message dict."""
    ChatMessage.objects.create(session=session, role=ChatMessage.ROLE_USER, content=user_message_text)

    detected = detect_symptoms(user_message_text)

    # 1) EMERGENCY RULE ENGINE — first and authoritative.
    # Vital signs come from the latest assessment (if any); chat text
    # contributes detected symptoms. Only high-concern/emergency words in the
    # message itself escalate — stored vitals alone don't hijack a chat about
    # nutrition.
    vitals = {}
    from assessments.models import Assessment

    latest_assessment = (
        Assessment.objects.filter(patient=session.patient).order_by("-visit_date", "-id").first()
    )
    if detected and latest_assessment:
        vitals = {
            "systolic_bp": latest_assessment.systolic_bp,
            "diastolic_bp": latest_assessment.diastolic_bp,
            "heart_rate": latest_assessment.heart_rate,
            "body_temperature": latest_assessment.body_temperature,
            "bmi": latest_assessment.bmi,
        }
    rules_out = rules_evaluate(vitals, detected)

    if rules_out["escalate"]:
        triggered_ids = ", ".join(t["id"] for t in rules_out["triggered"])
        answer = (
            f"{rules_out['message']}\n\n"
            f"Warning signs detected in your message: {triggered_ids} "
            f"(rule set {rules_out['rules_version']}).\n\n"
            "Please do not wait to see if it improves. If you are alone, call someone now. "
            "This chat assistant cannot provide emergency care."
        )
        message = ChatMessage.objects.create(
            session=session,
            role=ChatMessage.ROLE_ASSISTANT,
            content=answer,
            escalation=rules_out,
            sources=[],
            generation_mode="escalation",
        )
        log_event(
            request, "RULE_ESCALATION", target_type="chat_message", target_id=str(message.id),
            detail={"category": rules_out["category"], "rules": [t["id"] for t in rules_out["triggered"]]},
        )
        return _serialize(message)

    # 2) Patient context (authorized, minimal).
    patient_context = _patient_context(session.patient)

    # 3) RAG retrieval with source attribution.
    context = rag.retrieve_context(user_message_text)

    # 4) LLM generation with graceful fallback.
    history = [
        {"role": m.role, "content": m.content}
        for m in ChatMessage.objects.filter(session=session).order_by("created_at", "id")[:12]
    ]
    # Drop the final user turn — it is passed as `question` explicitly.
    history = history[:-1]

    answer, mode = generate_answer(
        user_message_text, context_chunks=context["chunks"] if context else None,
        history=history, patient_context=patient_context,
    )

    if answer is None:
        if context and context["chunks"]:
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
        escalation={"category": rules_out["category"], "escalate": False, "rules_version": rules_out["rules_version"]},
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
