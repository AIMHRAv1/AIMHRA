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
from chat.llm import generate_answer, validate_grounded_answer
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
    if patient_profile is None:
        return None

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


def _approved_recommendation_lines(recommendations):
    lines = []
    for group in (
        "routine_monitoring", "further_assessment",
        "medical_consultation", "urgent_medical_attention",
    ):
        for recommendation in (recommendations or {}).get(group, []):
            title = recommendation.get("title")
            action = recommendation.get("suggested_next_action")
            if title and action:
                lines.append(f"{title}: {action}")
    return lines


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

    latest_assessment = None
    if session.patient_id:
        latest_assessment = (
            Assessment.objects.filter(patient_id=session.patient_id)
            .order_by("-visit_date", "-id")
            .first()
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
    approved_recommendations = (
        latest_assessment.recommendations if latest_assessment else None
    )

    # 3) RAG retrieval with source attribution.
    context = rag.retrieve_context(user_message_text)

    # 4) LLM generation with graceful fallback.
    history = [
        {"role": m.role, "content": m.content}
        for m in ChatMessage.objects.filter(session=session).order_by("created_at", "id")[:12]
    ]
    # Drop the final user turn — it is passed as `question` explicitly.
    history = history[:-1]

    chunks = context["chunks"] if context else []
    answer = None
    mode = "no_relevant_context"
    if chunks:
        answer, mode = generate_answer(
            user_message_text, context_chunks=chunks,
            history=history, patient_context=patient_context,
            approved_recommendations=approved_recommendations,
        )

        if answer is not None and not validate_grounded_answer(answer, chunks):
            logger.warning(
                "LLM response lacked valid source-grounded citations; using source excerpts"
            )
            answer = None

        if answer is None:
            answer = "Relevant retrieved guideline excerpts (quoted verbatim):\n\n" + "\n\n".join(
                f"[S{i}] “{chunk['text'][:500]}”"
                for i, chunk in enumerate(chunks, start=1)
            )
            mode = "rag_only_fallback"
        else:
            answer = f"Guideline-based explanation (from retrieved sources):\n\n{answer}"
        if len({chunk["document_id"] for chunk in chunks}) > 1:
            answer += (
                "\n\nThese excerpts are from separate sources and have not been reconciled. "
                "If their statements differ, consult a qualified healthcare professional; "
                "this assistant does not choose between them."
            )
    else:
        answer = (
            "Knowledge-base limitation: no relevant guideline information was retrieved for "
            "this question. No guideline-based answer is available; please consult a qualified "
            "healthcare professional for clinical guidance."
        )

    recommendation_lines = _approved_recommendation_lines(approved_recommendations)
    if recommendation_lines:
        answer += (
            "\n\nApproved assessment recommendations (unchanged; retrieved excerpts do not "
            "replace or override them):\n"
            + "\n".join(f"- {line}" for line in recommendation_lines)
        )

    sources = [
        {
            "citation_id": f"S{i}",
            "document_title": c["document_title"],
            "issuing_organization": c.get("issuing_organization", ""),
            "section": c.get("section", ""),
            "page_number": c.get("page_number"),
            "source_url": c["source_url"],
            "chunk_id": c.get("chunk_id"),
            "chunk_index": c["chunk_index"],
            "score": c["score"],
        }
        for i, c in enumerate((context["chunks"] if context else []), start=1)
    ]
    if sources:
        references = "\n".join(
            " — ".join(
                part for part in [
                    f"[{source['citation_id']}]",
                    source["issuing_organization"] or "Issuing organization not recorded",
                    source["document_title"],
                    f"Section: {source['section']}" if source["section"] else "",
                    f"p. {source['page_number']}" if source["page_number"] is not None else "",
                    source["source_url"] or "Source URL not recorded",
                ] if part
            )
            for source in sources
        )
        answer = f"{answer.rstrip()}\n\nSources:\n{references}"
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
        "knowledge_status": (
            "retrieved_guidelines" if message.sources else "no_relevant_guidelines_retrieved"
        ),
        "generation_mode": message.generation_mode,
        "created_at": message.created_at.isoformat(),
        "disclaimer": CHAT_DISCLAIMER,
    }
