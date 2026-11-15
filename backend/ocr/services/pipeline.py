"""OCR extraction pipeline orchestrator (Step 2 cascade design).

upload bytes -> ONE fast pass (grayscale + cubic upscale)
    -> parse + validate
    -> extra compute ONLY for missing / low-confidence / invalid fields:
         + CLAHE / background-normalization variant
         + field-level crop re-read with a digit whitelist
    -> LLM stage (local model, temp 0, digit anti-hallucination)
    -> optional VLM stage (disabled by default)

NEVER creates an Assessment and NEVER runs a prediction. Raw values are
never corrected silently — uncertain fields are flagged and, where a decimal
insertion would fix them, a SUGGESTION is attached for the operator.
"""
import logging
import time

from django.conf import settings

from ocr.exceptions import OcrError
from ocr.services import parser, upload, validate
from ocr.services.parser import TARGET_FIELDS

logger = logging.getLogger(__name__)

# Fields whose regex result is considered solid enough to skip extra passes.
CONFIDENT_THRESHOLD = 0.85


def _png_for_vlm(content):
    """Preprocessed PNG copy of the page for the optional VLM stage. Returns
    None unless the VLM stage is enabled (we never pay the decode/encode
    cost otherwise)."""
    if not getattr(settings, "OCR_VISION_ENABLED", False):
        return None
    try:
        from ocr.services.preprocess import decode_image, preprocess_variant

        import cv2

        processed = preprocess_variant(decode_image(content), level=1)
        ok, buf = cv2.imencode(".png", processed)
        return buf.tobytes() if ok else None
    except Exception:
        logger.exception("Could not prepare the page image for the VLM stage")
        return None


def _try_qr(content):
    """Decode a QR code from the image and parse an embedded field payload.
    Returns ({field: entry}, qr_crop_b64_or_None) or None when no usable QR
    is present. Payload format: {"fields": {"age": 28, ...}} — values go
    through the SAME validation as OCR output."""
    try:
        import base64

        import cv2
        import json as _json
        import numpy as np

        from ocr.services.preprocess import decode_image, preprocess_variant

        detector = cv2.QRCodeDetector()
        img = decode_image(content)
        for level in (0, 1):  # plain, then shadow-normalized
            work = preprocess_variant(img, level=level)
            try:
                data, points, _ok = detector.detectAndDecode(work)
            except Exception:
                data, points = "", None
            if not data:
                continue
            try:
                payload = _json.loads(data)
            except ValueError:
                # Most QR codes on report cards encode a URL or an id, not a
                # field payload — normal, fall through to OCR (debug only).
                logger.debug("QR payload is not a field JSON (%.40s…); falling back to OCR", data)
                continue
            fields = payload.get("fields")
            if not isinstance(fields, dict):
                continue
            qr_crop = None
            if points is not None and len(points):
                pts = points[0].astype(int)
                x0, y0 = pts.min(axis=0)
                x1, y1 = pts.max(axis=0)
                pad = 10
                h, w = work.shape[:2]
                crop = work[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]
                ok, buf = cv2.imencode(".png", crop)
                if ok:
                    qr_crop = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
            out = {}
            for name, value in fields.items():
                if name in TARGET_FIELDS and value is not None:
                    out[name] = {
                        "value": value, "confidence": 1.0,
                        "raw_text": "qr", "source": "qr", "valid": True,
                    }
            if out:
                return out, qr_crop
        return None
    except Exception:
        logger.exception("QR fast path failed; falling back to OCR")
        return None


def _dispatch_ocr(file_type, content, path):
    """Cascade OCR: ONE fast pass first. Returns (variants, image_png) where
    variants is a list of (pass_name, lines, engine_info, processed_img)."""
    from ocr.services import ocr_engine

    if file_type == "pdf":
        lines, engine_info = ocr_engine.extract_pdf(content)
        return [("pdf", lines, engine_info, None)], None

    engine = (getattr(settings, "OCR_ENGINE", "tesseract") or "tesseract").lower()
    if engine == "easyocr":
        from ocr.services import engine_easyocr

        if engine_easyocr.easyocr_available():
            try:
                lines, engine_info = engine_easyocr.ocr_image_easyocr(content)
                image_png = _png_for_vlm(content)  # None unless the VLM stage is enabled
                return [("easyocr", lines, engine_info, None)], image_png
            except Exception:
                logger.exception("EasyOCR failed; falling back to Tesseract")
        else:
            logger.info("OCR_ENGINE=easyocr but EasyOCR is not installed; using Tesseract")

    result = ocr_engine.ocr_image(content, variant=0, return_words=True)
    if len(result) == 2:  # legacy/mock shape (lines, engine_info)
        lines, engine_info = result
        words, processed = [], None
    else:
        lines, engine_info, words, processed = result
    return [("fast", lines, engine_info, processed)], None


def _extra_variant(content, level):
    from ocr.services import ocr_engine

    names = {1: "clahe", 2: "denoise_deskew", 3: "threshold"}
    result = ocr_engine.ocr_image(content, variant=level, return_words=True)
    if len(result) == 2:
        lines, engine_info = result
        words, processed = [], None
    else:
        lines, engine_info, words, processed = result
    return (names.get(level, f"variant{level}"), lines, engine_info, processed)


def _score_pass(fields):
    valid_n = sum(1 for e in fields.values() if e.get("value") is not None and e.get("valid", False))
    total_n = len(fields)
    mean_conf = (
        sum(float(e.get("confidence") or 0) for e in fields.values()) / total_n if total_n else 0.0
    )
    return (valid_n, total_n, mean_conf)


def _parse_reread_value(text, field):
    """First number in a crop re-read. The crop may span the value AND the
    reference column ("22.1 18.5-24.9"), so only the first number counts —
    concatenating everything turned 22.1 into 22.13185249. A combined
    "161/100" token yields systolic (before the slash) or diastolic (after).
    Values with more than 2 decimal places are crop garbage (no lab field on
    these cards has 3 decimals) — rejected."""
    import re

    t = (text or "").replace(",", ".")
    slash = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", t)
    if field == "systolic_bp" and slash:
        return float(slash.group(1))
    if field == "diastolic_bp" and slash:
        return float(slash.group(2))
    m = re.search(r"\d+(?:\.\d+)?", t)
    if not m:
        return None
    value = float(m.group(0))
    if "." in m.group(0) and len(m.group(0).split(".")[1]) > 2:
        return None
    return value


def _reread_fields(lines, processed_img, wanted):
    """Field-level re-reading: locate the label, crop the VALUE region from
    the already-processed image, and re-OCR the crop with a digit whitelist
    (--psm 7). Cheap (small crops) and only runs for wanted fields.

    The crop covers the FIRST digit-word on the label line only (plus the
    slash-pair word for BP): cropping the whole line pulled in neighbouring
    columns (sample numbers, reference ranges) and produced plausible-looking
    garbage. A crop whose text looks like a range ("97.0-99.0") is discarded
    outright."""
    import re as _re

    from ocr.services import ocr_engine
    from ocr.services.parser import _fuzzy_match_field, _match_label

    results = {}
    if processed_img is None:
        return results
    for field in wanted:
        if field == "visit_date":
            continue
        for idx, line in enumerate(lines):
            low = line.get("text", "").lower()
            hit = _match_label(low, field) is not None or _fuzzy_match_field(low)[0] == field
            if not hit:
                continue
            words = line.get("words") or []
            digit_words = [w for w in words if any(ch.isdigit() for ch in w["text"])]
            if not digit_words and idx + 1 < len(lines):
                digit_words = [
                    w for w in (lines[idx + 1].get("words") or [])
                    if any(ch.isdigit() for ch in w["text"])
                ]
            if not digit_words:
                continue
            if field in ("systolic_bp", "diastolic_bp"):
                value_words = [w for w in digit_words if "/" in w["text"]] or digit_words[:1]
            else:
                value_words = digit_words[:1]
            x0 = min(w["left"] for w in value_words)
            y0 = min(w["top"] for w in value_words)
            x1 = max(w["left"] + w["width"] for w in value_words)
            y1 = max(w["top"] + w["height"] for w in value_words)
            text = ocr_engine.ocr_value_crop(processed_img, (x0, y0, x1 - x0, y1 - y0))
            if _re.search(r"\d+\s*[-–]\s*\d+", text):
                continue  # crop reads like a reference range, not a value
            value = _parse_reread_value(text, field)
            if value is None:
                continue
            results[field] = {
                "value": value,
                "raw_text": f"reread: {text}",
                "source": "reread",
                "confidence": 0.8,
            }
            break
    return results


def _crop_image_for_field(lines, processed_img, field):
    """Base64 PNG crop of the region an extracted value was read from, so the
    operator can compare against the form input. None when unavailable."""
    import base64

    from ocr.services.parser import _fuzzy_match_field, _match_label

    if processed_img is None:
        return None
    if field == "visit_date":  # no label pattern; dates have no value crop
        return None
    try:
        import cv2

        for idx, line in enumerate(lines):
            low = line.get("text", "").lower()
            hit = _match_label(low, field) is not None or _fuzzy_match_field(low)[0] == field
            if not hit:
                continue
            words = line.get("words") or []
            value_words = [w for w in words if any(ch.isdigit() for ch in w["text"])]
            if not value_words and idx + 1 < len(lines):
                value_words = [
                    w for w in (lines[idx + 1].get("words") or [])
                    if any(ch.isdigit() for ch in w["text"])
                ]
            if not value_words:
                continue
            x0 = min(w["left"] for w in value_words)
            y0 = min(w["top"] for w in value_words)
            x1 = max(w["left"] + w["width"] for w in value_words)
            y1 = max(w["top"] + w["height"] for w in value_words)
            pad = 6
            h_img, w_img = processed_img.shape[:2]
            crop = processed_img[
                max(0, y0 - pad):min(h_img, y1 + pad), max(0, x0 - pad):min(w_img, x1 + pad)
            ]
            if crop.size == 0:
                return None
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                return None
            return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:
        logger.exception("Field crop for %s failed", field)
    return None


def extract(file_type, content):
    """Run the full cascade over validated upload bytes.

    Returns the endpoint payload dict. Raises EngineUnavailable (503) or
    ValueError (undecodable image) — both handled by the view.
    """
    started = time.perf_counter()
    path = upload.temp_file_path(file_type, content)
    quality_warnings = []
    try:
        # Capture-quality gate BEFORE any OCR (retake message on bad photos).
        from ocr.services.gate import check_capture_quality

        check_capture_quality(content, file_type)

        # QR fast path: some report cards embed the values in a QR code.
        if file_type != "pdf" and getattr(settings, "OCR_ENABLE_QR", True):
            qr_result = _try_qr(content)
            if qr_result is not None:
                qr_fields, qr_crop = qr_result
                qr_fields, summary = validate.validate_fields(qr_fields)
                if qr_crop:
                    for entry in qr_fields.values():
                        entry["crop_image"] = qr_crop
                missing = validate.build_missing(qr_fields, TARGET_FIELDS)
                return {
                    "fields": qr_fields,
                    "missing": missing,
                    "warnings": ["Values read from the QR code — please verify before submitting."],
                    "raw_text": "(QR code payload)",
                    "engine_info": {"engine": "qr", "duration_ms": int((time.perf_counter() - started) * 1000)},
                    "summary": summary,
                }
        variants, image_png = _dispatch_ocr(file_type, content, path)
        try:
            if file_type != "pdf":
                from ocr.services.preprocess import decode_image

                src = decode_image(content)
                if max(src.shape[:2]) < 900:
                    quality_warnings.append(
                        "The photo is low resolution — values may be misread. "
                        "Please retake the photo closer to the card, in even light, "
                        "or upload the PDF report."
                    )
        except Exception:
            pass  # undecodable input is handled by the extraction itself
    finally:
        upload.cleanup(path)

    if not any(lines for _n, lines, _i, _img in variants):
        raise OcrError(
            "No readable text was found in the file. Please upload a clearer "
            "photo or a PDF with selectable text."
        )

    # Parse + validate every pass; best pass wins, gaps filled from others.
    candidates = []
    for pass_name, lines, engine_info, processed in variants:
        pass_fields, pass_warnings = parser.parse_lines(lines)
        pass_fields, pass_summary = validate.validate_fields(pass_fields)
        candidates.append({
            "pass": pass_name, "fields": pass_fields, "warnings": pass_warnings,
            "lines": lines, "engine_info": engine_info, "processed": processed,
            "_score": _score_pass(pass_fields),
        })
    best = max(candidates, key=lambda c: c["_score"])
    fields = dict(best["fields"])
    warnings = list(best["warnings"])
    filled_from = []
    for candidate in candidates:
        if candidate is best:
            continue
        for name, entry in candidate["fields"].items():
            if name not in fields and entry.get("value") is not None:
                merged = dict(entry)
                merged["source"] = f"{merged.get('source', 'tesseract')}+{candidate['pass']}"
                fields[name] = merged
                filled_from.append(name)
    if filled_from:
        warnings.append(
            f"Fields {', '.join(sorted(filled_from))} were recovered from the alternate OCR pass."
        )
    processed_img = best["processed"]
    best_lines = best["lines"]
    engine_info = dict(best["engine_info"])

    # Cascade: extra compute ONLY for missing / low-confidence / invalid fields.
    # Optional fields (gestational_week, visit_date) do not trigger extra
    # compute passes — a missing optional field is normal, not a defect.
    from mlcore.constants import FEATURES as REQUIRED_FEATURES

    def _wanted():
        return [
            name for name in REQUIRED_FEATURES
            if name not in fields
            or fields[name].get("value") is None
            or fields[name].get("valid") is False
            or float(fields[name].get("confidence") or 0) < CONFIDENT_THRESHOLD
        ]

    passes_ran = [best["pass"]]
    llm_used = False
    vlm_used = False
    raw_text = "\n".join(line.get("text", "") for line in best_lines)

    wanted = _wanted()
    if wanted and file_type != "pdf" and getattr(settings, "OCR_ENABLE_CLAHE", True):
        # Extra preprocessing variant: CLAHE + background normalization.
        try:
            name2, lines2, info2, img2 = _extra_variant(content, level=1)
            passes_ran.append(name2)
            f2, _w2 = parser.parse_lines(lines2)
            f2, _s2 = validate.validate_fields(f2)
            _absorb_pass(fields, f2, name2, filled_from, warnings)
            if img2 is not None and processed_img is None:
                processed_img = img2
        except Exception:
            logger.exception("CLAHE variant pass failed; continuing")

        # Field-level crop re-read + cross-engine (EasyOCR) check, then ONE
        # merge pass. Collection happens first so the merge can require
        # corroboration between the two deterministic sources.
        still_wanted = _wanted()
        reread = {}
        easy_fields = {}
        if still_wanted:
            if processed_img is not None:
                try:
                    reread = _reread_fields(best_lines, processed_img, still_wanted)
                    if reread:
                        passes_ran.append("reread")
                except Exception:
                    logger.exception("Crop re-read pass failed; continuing")
            if getattr(settings, "OCR_SECOND_ENGINE", True) and _wanted():
                try:
                    from ocr.services import engine_easyocr

                    if engine_easyocr.easyocr_available():
                        result2 = engine_easyocr.ocr_image_easyocr(content)
                        lines2 = result2[0]
                        f2, _w2 = parser.parse_lines(lines2)
                        f2, _s2 = validate.validate_fields(f2)
                        passes_ran.append("easyocr")
                        easy_fields = {
                            name: entry for name, entry in f2.items()
                            if name not in ("gestational_week", "visit_date")
                        }
                except Exception:
                    logger.exception("Second-engine (EasyOCR) pass failed; continuing")

            for name in still_wanted:
                existing = fields.get(name)
                rr = reread.get(name)
                ez = easy_fields.get(name)
                ez_valid = bool(ez and ez.get("value") is not None and ez.get("valid", False))

                if existing is None or existing.get("value") in (None, ""):
                    # MISSING: targeted crop re-read wins, else cross-engine.
                    if rr is not None:
                        fields[name] = dict(rr)
                        try:
                            validate.validate_fields({name: fields[name]})
                        except Exception:
                            logger.exception("Validation of reread field %s failed", name)
                        fields[name]["source"] = "reread"
                        warnings.append(f"Field {name} was recovered from a crop re-read — verify.")
                    elif ez is not None:
                        _merge_candidate(fields, warnings, name, ez, raw_text="")
                    continue

                if not existing.get("valid", False):
                    # IMPLAUSIBLE regex reading: replace with the targeted
                    # crop re-read, else with a plausible EasyOCR value.
                    # Displaced value stays as a candidate; field stays amber.
                    adopted = False
                    if rr is not None:
                        rr_entry = dict(rr)
                        try:
                            validate.validate_fields({name: rr_entry})
                        except Exception:
                            logger.exception("Validation of reread field %s failed", name)
                        adopted = _adopt_invalid(fields, warnings, name, rr_entry, "reread")
                    if not adopted and ez_valid:
                        adopted = _adopt_invalid(fields, warnings, name, ez, "EasyOCR")
                    if not adopted:
                        if rr is not None:
                            _merge_candidate(fields, warnings, name, rr, raw_text="")
                        elif ez is not None:
                            _merge_candidate(fields, warnings, name, ez, raw_text="")
                    continue

                # Plausible but low confidence: only replace when BOTH
                # deterministic sources agree on a different value; a single
                # contradicting source is recorded as a red-flag candidate.
                rr_val = rr.get("value") if rr else None
                agree_rr = rr_val is not None and _same_value(rr_val, existing.get("value"))
                agree_ez = ez_valid and _same_value(ez.get("value"), existing.get("value"))
                if agree_rr or agree_ez:
                    existing.setdefault("also_found_by", []).append(
                        "reread" if agree_rr else "easyocr")
                    existing["confidence"] = max(float(existing.get("confidence") or 0), 0.9)
                    continue
                both_agree = (
                    rr_val is not None and ez_valid
                    and _same_value(rr_val, ez.get("value"))
                    and not _same_value(rr_val, existing.get("value"))
                )
                if both_agree:
                    _adopt_invalid(
                        fields, warnings, name, {**rr, "valid": True},
                        "reread+EasyOCR", require_invalid=False,
                    )
                else:
                    if rr_val is not None and not _same_value(rr_val, existing.get("value")):
                        _merge_candidate(fields, warnings, name, rr, raw_text="")
                    if ez_valid and not _same_value(ez.get("value"), existing.get("value")):
                        _merge_candidate(fields, warnings, name, ez, raw_text="")

    # Re-validate after merging so cross-field rules (dia<sys) still hold.
    fields, summary = validate.validate_fields(fields)
    raw_text = "\n".join(line.get("text", "") for line in best_lines)

    from ocr.services import vision_extract  # imported before its use below
    from mlcore.constants import FEATURES as REQUIRED_FEATURES

    # Step 4: the LLM stage runs ONLY for fields that are entirely MISSING —
    # it never overrides or flags a valid Tesseract value.
    wanted = [
        name for name in REQUIRED_FEATURES
        if name not in fields or fields[name].get("value") is None
    ]
    if wanted and settings.LLM_BASE_URL:
        from ocr.services.llm_extract import llm_extract_fields

        llm_fields, llm_model = llm_extract_fields(raw_text, wanted)
        llm_used = bool(llm_fields)
        for name, entry in llm_fields.items():
            _merge_candidate(fields, warnings, name, entry, raw_text)

        if vision_extract.vision_enabled() and image_png is not None:


            still_missing = [
                name for name in wanted
                if name not in fields or fields[name].get("value") is None
            ]
            if still_missing:
                vlm_fields, _vlm_model = vision_extract.vision_extract_fields(image_png, still_missing)
                vlm_used = bool(vlm_fields)
                for name, entry in vlm_fields.items():
                    _merge_candidate(
                        fields, warnings, name, {**entry, "confidence": vision_extract.VLM_CONFIDENCE}, raw_text
                    )
        if llm_used or vlm_used:
            engine_info["llm_model"] = llm_model if llm_used else None
            engine_info["stages"] = [s for s, used in (("llm", llm_used), ("vlm", vlm_used)) if used]

    missing = validate.build_missing(fields, TARGET_FIELDS)
    duration_ms = int((time.perf_counter() - started) * 1000)

    # Per-field source crops: let the operator compare each value against the
    # exact region it was read from.
    if processed_img is not None:
        for name, entry in fields.items():
            if entry.get("source", "").startswith("qr"):
                continue
            crop = _crop_image_for_field(best_lines, processed_img, name)
            if crop:
                entry["crop_image"] = crop

    warnings = quality_warnings + warnings
    return {
        "fields": fields,
        "missing": missing,
        "warnings": warnings,
        "raw_text": raw_text,
        "engine_info": {
            **engine_info,
            "passes": passes_ran,
            "duration_ms": duration_ms,
        },
        "summary": summary,
    }


def _adopt_invalid(fields, warnings, name, entry, engine, require_invalid=True):
    """Replace a regex reading with a plausible reading from a second
    deterministic source (digit-whitelist crop re-read / EasyOCR cross-engine).

    Rules:
    - the incoming reading must pass validation;
    - by default applies ONLY when the current reading is implausible
      (valid=False); with require_invalid=False it may also replace a valid
      but low-confidence reading that BOTH deterministic sources contradict —
      a confident first reading is never touched;
    - the displaced value is kept as a candidate and the field stays amber
      ("verify"), so nothing is silently corrected.

    Returns True when the value was adopted."""
    if entry.get("value") is None or not entry.get("valid", False):
        return False
    existing = fields.get(name)
    if existing is None or existing.get("value") in (None, ""):
        return False
    if require_invalid and existing.get("valid", False):
        return False
    old_value = existing.get("value")
    old_source = existing.get("source", "regex")
    merged = dict(entry)
    merged["candidates"] = [
        {"value": old_value, "source": old_source, "confidence": existing.get("confidence")},
        {"value": entry.get("value"), "source": entry.get("source", engine), "confidence": entry.get("confidence")},
    ]
    note = (
        f"Value re-read by the {engine} engine ({entry.get('value')} replaces "
        f"{old_value}, which was implausible) — verify."
    )
    merged["warning"] = (merged.get("warning", "") + "; " + note).strip("; ")
    fields[name] = merged
    if note not in warnings:
        warnings.append(note)
    return True


def _absorb_pass(fields, pass_fields, pass_name, filled_from, warnings):
    """Merge a variant pass into the current fields: fill missing fields and
    REPLACE invalid readings with valid ones from this pass (the displaced
    value is kept as a candidate for the operator)."""
    for name, entry in pass_fields.items():
        if entry.get("value") is None:
            continue
        existing = fields.get(name)
        if existing is None or existing.get("value") in (None, ""):
            merged = dict(entry)
            merged["source"] = f"{merged.get('source', 'tesseract')}+{pass_name}"
            fields[name] = merged
            filled_from.append(name)
        elif not existing.get("valid", False) and entry.get("valid", False):
            old_value = existing.get("value")
            old_source = existing.get("source", "tesseract")
            fields[name] = dict(entry)
            fields[name]["candidates"] = [
                {"value": old_value, "source": old_source, "confidence": existing.get("confidence")},
                {"value": entry.get("value"), "source": entry.get("source", "tesseract"), "confidence": entry.get("confidence")},
            ]
            note = f"Value taken from the {pass_name} pass (previous read {old_value} was invalid) — verify."
            fields[name]["warning"] = (fields[name].get("warning", "") + "; " + note).strip("; ")
            if note not in warnings:
                warnings.append(note)


def _merge_candidate(fields, warnings, name, entry, raw_text):
    """Merge an LLM/VLM/reread value into fields.

    - Field absent -> accept the value (marked low confidence, its source).
    - Field present and values AGREE -> keep the regex value, note the
      second source in provenance.
    - Values DISAGREE -> flag the field red and return both candidates.
    """
    from ocr.services.validate import validate_fields

    value = entry.get("value")
    if value is None:
        return
    existing = fields.get(name)
    if existing is None or existing.get("value") in (None, ""):
        fields[name] = {
            "value": value,
            "confidence": float(entry.get("confidence", 0.55)),
            "raw_text": entry.get("raw_text", ""),
            "source": entry.get("source", "llm"),
        }
        try:
            validate_fields({name: fields[name]})
        except Exception:
            logger.exception("Validation of merged field %s failed", name)
        return
    if existing.get("valid", False) and entry.get("source") == "llm":
        # Step 4 guarantee: the LLM never overrides a valid Tesseract value.
        existing.setdefault("also_found_by", []).append("llm")
        return

    if _same_value(existing.get("value"), value):
        existing.setdefault("also_found_by", []).append(entry.get("source", "llm"))
        return

    existing["valid"] = False
    cands = existing.get("candidates") or [
        {"value": existing.get("value"), "source": existing.get("source", "regex"), "confidence": existing.get("confidence")},
    ]
    if not any(_same_value(c.get("value"), value) for c in cands):
        cands.append({"value": value, "source": entry.get("source", "llm"), "confidence": entry.get("confidence")})
    existing["candidates"] = cands
    extra = f"Two sources disagree for {name}: {existing.get('source')} vs {entry.get('source')} — verify manually."
    existing["warning"] = (existing.get("warning") + "; " + extra).strip("; ")
    if extra not in warnings:
        warnings.append(extra)


def _same_value(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()
