"""LLM extraction stage (local Ollama, temperature 0).

Used ONLY for fields the regex parser missed or flagged low-confidence.
The model receives the OCR text and must answer with a strict JSON object;
absent fields are null. Anti-hallucination guard: an LLM value is accepted
ONLY if its digits appear somewhere in the OCR text — otherwise it is
rejected and the field stays as the regex found it (or missing).

The chat LLM and this call share the Ollama server: we pass keep_alive=0 so
the model unloads right after each request and never stays resident beside
another model (OLLAMA_MAX_LOADED_MODELS=1 is documented in .env.example).
"""
import json
import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

_LLM_CONFIDENCE = 0.55  # below the amber threshold band, forces "review"

PROMPT = (
    "You are a data-extraction assistant. From the OCR text of a maternal "
    "health lab report card, extract these fields: age, body_temperature (Fahrenheit), "
    "heart_rate, systolic_bp, diastolic_bp, bmi, hba1c, fasting_glucose, "
    "gestational_week, visit_date (YYYY-MM-DD). "
    "Rules: return ONLY a JSON object with exactly these keys; use null for any "
    "field not present in the text; never invent or calculate a value; copy "
    "numbers exactly as they appear. JSON:"
)


def llm_configured():
    return bool(settings.LLM_BASE_URL)


def _digit_sequences(text):
    """All digit runs in the OCR text, e.g. '120/80' -> ['120', '80']."""
    return re.findall(r"\d+", (text or "").replace(",", "."))


def digits_present(value, ocr_text):
    """Anti-hallucination check: every digit run of the value must appear in
    the OCR text (as a substring of a digit run)."""
    if value is None:
        return False
    for digits in re.findall(r"\d+", str(value)):
        if not any(digits in seq for seq in _digit_sequences(ocr_text)):
            return False
    return True


def _call_ollama(user_content, model, keep_alive=0, image_b64=None):
    """Minimal OpenAI-compatible call to the local server with keep_alive=0
    so the model unloads immediately (never resident beside another model)."""
    import json as _json
    import urllib.request

    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    content = [{"type": "text", "text": user_content}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}})
    payload = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 300,
        "keep_alive": keep_alive,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=settings.LLM_TIMEOUT_SECONDS) as response:
        body = _json.loads(response.read().decode("utf-8"))
    return ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _parse_json_answer(answer):
    """Extract the JSON object from the model answer; None when malformed."""
    if not answer:
        return None
    match = re.search(r"\{.*\}", answer, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def llm_extract_fields(ocr_text, wanted_fields, model=None, image_b64=None):
    """Ask the local LLM for the wanted fields. Returns
    (extracted, model_name) where extracted maps field ->
    {"value", "raw_text", "source"} for values that passed the
    anti-hallucination digit check. Fields the LLM invented are dropped.
    """
    model = model or getattr(settings, "OCR_LLM_MODEL", None) or settings.LLM_MODEL
    wanted = [f for f in wanted_fields if f != "visit_date"]
    fields_spec = {f: None for f in wanted}
    fields_spec["visit_date"] = None
    user_content = PROMPT + "\nOCR TEXT:\n" + (ocr_text or "")[:4000]

    extracted = {}
    try:
        answer = _call_ollama(user_content, model, image_b64=image_b64)
    except Exception:
        logger.exception("OCR LLM extraction call failed; continuing without it")
        return extracted, model

    data = _parse_json_answer(answer)
    if not data:
        return extracted, model

    for field in wanted:
        value = data.get(field)
        if value is None:
            continue
        if isinstance(value, float) and value != value:  # NaN guard
            continue
        if isinstance(value, str):
            # The schema says numbers or null; string "null"/text is noise.
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?", value.strip()):
                continue
            value = value.strip()
        if not digits_present(value, ocr_text):
            logger.info("LLM value for %s rejected by digit check", field)
            continue
        extracted[field] = {
            "value": value,
            "raw_text": f"llm:{model}",
            "source": "llm",
        }
    return extracted, model
