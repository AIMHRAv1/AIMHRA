"""Optional vision-model (VLM) extraction stage.

DISABLED by default (settings.OCR_VISION_ENABLED, env OCR_VISION_ENABLED).
Only small models are allowed (default qwen2.5vl:3b). The VLM sees the page
image directly, so its answers CANNOT be digit-checked against OCR text —
every VLM value is therefore marked low confidence and source "vlm" for
mandatory operator review.

Model co-loading: all Ollama calls in the OCR module pass keep_alive=0 so a
model unloads immediately after its request; with OLLAMA_MAX_LOADED_MODELS=1
(recommended in .env.example) the VLM and the chat LLM are never resident at
the same time.
"""
import base64
import logging

from django.conf import settings

from ocr.services.llm_extract import _call_ollama, _parse_json_answer

logger = logging.getLogger(__name__)

VLM_CONFIDENCE = 0.5  # low by definition — operator must verify

PROMPT = (
    "This is a photo of a maternal health lab report card. Read it and return "
    "ONLY a JSON object with exactly these keys: age, body_temperature, "
    "heart_rate, systolic_bp, diastolic_bp, bmi, hba1c, fasting_glucose, "
    "gestational_week, visit_date. Use null for any field not visible. Copy "
    "numbers exactly as printed — never calculate or guess. JSON:"
)


def vision_enabled():
    return bool(getattr(settings, "OCR_VISION_ENABLED", False))


def vision_model():
    return getattr(settings, "OCR_VISION_MODEL", "qwen2.5vl:3b")


def vision_extract_fields(image_png_bytes, wanted_fields):
    """Ask the vision model about fields still missing. Returns (extracted,
    model_name); extracted maps field -> {"value", "raw_text", "source"}."""
    if not vision_enabled():
        return {}, vision_model()
    image_b64 = base64.b64encode(image_png_bytes).decode("ascii")
    fields_spec = {f: None for f in wanted_fields}
    fields_spec["visit_date"] = None
    extracted = {}
    try:
        answer = _call_ollama(
            PROMPT + "\nJSON keys required: " + ", ".join(fields_spec),
            vision_model(),
            image_b64=image_b64,
        )
    except Exception:
        logger.exception("OCR vision extraction call failed; continuing without it")
        return extracted, vision_model()

    data = _parse_json_answer(answer)
    if not data:
        return extracted, vision_model()
    for field in wanted_fields:
        value = data.get(field)
        if value is None or (isinstance(value, float) and value != value):
            continue
        extracted[field] = {
            "value": value,
            "raw_text": f"vlm:{vision_model()}",
            "source": "vlm",
        }
    return extracted, vision_model()
