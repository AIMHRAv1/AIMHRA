"""Offline LLM client for a locally-running OpenAI-compatible server
(Ollama by default, llama.cpp server / vLLM also work) with strict grounding
and a safe extractive fallback.

- No cloud calls are made. The default base URL is the local Ollama endpoint.
- The system prompt forbids diagnosis, prescriptions and certainty claims.
- Answers must be grounded in the supplied RAG context when present.
- An unavailable local server degrades gracefully to an extractive answer
  composed purely from retrieved knowledge-base chunks — never crashes.
"""
import json
import logging
import re
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an educational maternal-health assistant inside a decision-support system "
    "used by healthcare workers. You are NOT a doctor and must never diagnose, prescribe "
    "medication or dosages, or tell the user to ignore symptoms. However, providing "
    "general educational information is your job: describe practical care steps drawn "
    "from the trusted excerpts (e.g. rest, positioning, monitoring, nutrition, "
    "transport arrangements, what to report to the medical team) using cautious language "
    "('commonly', 'may', 'it is recommended to consult'). Never refuse to answer "
    "wholesale and never say you cannot help — when the excerpts are insufficient, say "
    "what they do not cover and recommend consulting a healthcare professional. Ground "
    "your answer in the excerpts when provided and do not invent facts beyond them. "
    "Never claim to have examined the patient. Match the requested depth: short "
    "factual questions get short answers; when detailed step-by-step guidance is "
    "requested, provide it fully in plain language."
)

FALLBACK_NO_LLM = (
    "The local AI service is not available right now. "
    "Here is what the trusted knowledge base contains for your question. "
    "For anything urgent or unclear, please contact a healthcare professional."
)

# Neutral intro for extractive answers — used whenever the model's own answer
# is unavailable (server down OR the model refused), so it must not claim to
# know why.
KB_INTRO = (
    "Here is what the trusted knowledge base contains for this situation. "
    "For anything urgent or unclear, please contact a healthcare professional."
)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "do", "does",
    "did", "can", "could", "should", "would", "will", "shall", "may", "might", "must",
    "i", "me", "my", "we", "you", "your", "it", "its", "this", "that", "these", "those",
    "what", "which", "who", "whom", "how", "when", "where", "why", "of", "in", "on",
    "for", "to", "with", "about", "and", "or", "if", "at", "by", "from", "as", "have",
    "has", "had", "get", "got", "any", "some", "there", "their", "them", "than", "so",
}


def llm_configured():
    """A local model server is considered configured whenever a base URL is set."""
    return bool(settings.LLM_BASE_URL)


_REFUSAL_MARKERS = (
    "can't provide medical advice",
    "cannot provide medical advice",
    "cannot provide any medical",
    "not able to provide medical",
    "unable to provide medical",
    "i can't assist",
    "i cannot assist",
)


def looks_like_refusal(text):
    """True when a small local model answered with a blanket refusal instead
    of the expected educational guidance."""
    if not text:
        return True
    lowered = text.lower()
    if any(marker in lowered for marker in _REFUSAL_MARKERS):
        return True
    # A useful grounded answer is substantive; a bare deflection is not.
    return len(lowered) < 150 and "consult" in lowered and "•" not in text


def generate_answer(question, context_chunks=None, history=None, patient_context=None):
    """Call the configured local OpenAI-compatible chat server.

    Returns (answer_text, mode) where mode in {"local_llm", "no_llm_configured"}.
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
        answer = _chat_completion(messages)
        return (answer, "local_llm") if answer else (None, "no_llm_configured")
    except Exception:
        logger.exception("Local LLM call failed; using extractive fallback")
        return None, "no_llm_configured"


def _chat_completion(messages):
    """Minimal OpenAI-compatible /chat/completions call via stdlib urllib."""
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 900,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=settings.LLM_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))
    answer = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return answer.strip()


def compose_extractive(question, context_chunks, intro=FALLBACK_NO_LLM, max_words=300):
    """Offline extractive answer: rank sentences of the retrieved chunks by
    question-keyword overlap and render the best ones as bullets. Used when
    the local model server is unavailable so the chat still answers usefully
    without any network access."""
    keywords = _question_keywords(question)
    scored = []
    for chunk in context_chunks or []:
        for sentence in _sentences(chunk.get("text", "")):
            overlap = len(keywords & _tokens(sentence))
            if overlap > 0:
                scored.append((overlap, sentence.strip(), chunk.get("document_title", "")))
    scored.sort(key=lambda item: (-item[0], -len(item[1])))
    picked, seen = [], set()
    for _, sentence, _title in scored:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append(sentence)
        if sum(len(s.split()) for s in picked) >= max_words:
            break
        if len(picked) >= 8:
            break
    if not picked:
        return None
    bullets = "\n".join(f"• {s}" for s in picked)
    # The standard intros already end with this line — don't repeat it.
    if "contact a healthcare professional" in intro.lower():
        return f"{intro}\n\n{bullets}"
    return f"{intro}\n\n{bullets}\n\nFor anything urgent or unclear, please contact a healthcare professional."


def _question_keywords(question):
    return {t for t in _tokens(question) if t not in _STOPWORDS and len(t) > 2}


def _tokens(text):
    return set(re.findall(r"[a-z]+", text.lower()))


def _sentences(text):
    # Normalize PDF line-wraps before splitting so sentences stay intact.
    flat = re.sub(r"\s+", " ", text)
    return [s.strip(" •·") for s in re.split(r"(?<=[.!?])\s+", flat) if 60 < len(s.strip()) < 400]
