"""OpenAI-compatible LLM client with strict grounding and safe fallback.

- The system prompt forbids diagnosis, prescriptions and certainty claims.
- Answers must be grounded in the supplied RAG context when present.
- Unavailable/unconfigured LLM degrades gracefully — never crashes the chat.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an educational maternal-health assistant inside a decision-support system. "
    "You are NOT a doctor and must never diagnose, prescribe medication or dosages, or "
    "tell the user to ignore symptoms. Use cautious language ('commonly', 'may', 'it is "
    "recommended to consult'). When trusted knowledge excerpts are provided, ground your "
    "answer in them and do not invent facts beyond them. If the excerpts are insufficient, "
    "say what you do not know and recommend consulting a healthcare professional. "
    "Never claim to have examined the patient. Keep answers concise (under 250 words) "
    "and use plain language."
)

FALLBACK_NO_LLM = (
    "The AI response service is not available right now. "
    "Here is what the trusted knowledge base contains for your question. "
    "For anything urgent or unclear, please contact a healthcare professional."
)


def llm_configured():
    return bool(settings.LLM_API_KEY)


def generate_answer(question, context_chunks=None, history=None, patient_context=None):
    """Call the configured OpenAI-compatible chat API.

    Returns (answer_text, mode) where mode in {"llm", "no_llm_configured"}.
    Raises nothing — callers get the fallback on any failure.
    """
    if not llm_configured():
        return None, "no_llm_configured"

    context_block = ""
    if context_chunks:
        excerpts = "\n\n".join(
            f"[Source {i + 1}: {c['document_title']} (chunk {c['chunk_index']})]\n{c['text']}"
            for i, c in enumerate(context_chunks)
        )
        context_block = (
            "Trusted knowledge excerpts (ground your answer in these where relevant):\n\n"
            f"{excerpts}\n\n"
            "If these excerpts do not cover the question, say so explicitly."
        )

    context_line = ""
    if patient_context:
        context_line = (
            "Patient context entered into the system (do not claim you examined the patient; "
            "refer to it as 'based on the information entered into the system'): "
            + patient_context
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        messages.append({"role": turn["role"].lower(), "content": turn["content"]})
    user_content = "\n\n".join(p for p in [context_line, context_block, f"User question: {question}"] if p)
    messages.append({"role": "user", "content": user_content})

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=600,
        )
        answer = (response.choices[0].message.content or "").strip()
        return (answer, "llm") if answer else (None, "no_llm_configured")
    except Exception:
        logger.exception("LLM call failed; using fallback")
        return None, "no_llm_configured"
