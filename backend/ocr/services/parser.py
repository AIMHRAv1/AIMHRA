"""Regex-based report-card parser.

Input: ordered text lines from the OCR engine ({"text", "conf", "source"}).
Output: {field: {"value", "confidence", "raw_text", "source"}} — raw values,
no validation and no unit conversion here (units handled by units.py,
plausibility by validate.py).

Handles:
- label synonyms (BP / Blood Pressure / Systolic / Diastolic / Pulse /
  Heart rate / Temp / Temperature / HbA1c / FBS / Fasting glucose / BMI /
  Age / Gestational age / GA / weeks ...)
- "120/80" combined blood-pressure format
- Devanagari digits -> ASCII
- decimal comma -> decimal point
- common OCR confusions (O->0, l/I->1, S->5) applied ONLY inside number
  tokens that were already matched in a numeric context
"""
import re
from difflib import SequenceMatcher

from mlcore.constants import FEATURES

# Fields the parser looks for: the 8 model features + gestational_week +
# visit_date (both optional on the assessment).
TARGET_FIELDS = list(FEATURES) + ["gestational_week", "visit_date"]

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
# Lines are lowercased before parsing, so both cases are mapped.
_DIGIT_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5", "s": "5"})

# Label synonyms per canonical field. Case-insensitive.
_LABELS = {
    "systolic_bp": [r"systolic", r"\bsbp\b", r"\bsys\.?\b(?!\w)", r"bp\s*\(?syst"],
    "diastolic_bp": [r"diastolic", r"\bdbp\b", r"\bdia\.?\b(?!\w)", r"bp\s*\(?dia"],
    "heart_rate": [r"pulse(?:\s*rate)?", r"heart\s*rate", r"\bhr\b", r"\bpulse\b"],
    "body_temperature": [r"body\s*temp", r"temperature", r"\btemp\b"],
    "bmi": [r"\bb\.?\s*m\.?\s*i\.?\b", r"body\s*mass\s*index"],
    "age": [r"\bage\b", r"age\s*\(?\s*years?\s*\)?"],
    "hba1c": [r"hb\s*a\s*1\s*c", r"hba1c", r"hba\s*1c", r"hba[i1l]c", r"glycated\s*haemoglobin", r"glycosylated"],
    "fasting_glucose": [
        r"fasting\s*(?:blood\s*)?(?:glucose|sugar)",
        r"\bfbs\b",
        r"\bf\.?\s*b\.?\s*s\.?\b",
        r"glucose\s*\(?\s*fasting",
        r"blood\s*sugar\s*\(?\s*fasting",
    ],
    "gestational_week": [
        r"gestational\s*(?:age|week|period)",
        r"\bga\b",
        r"weeks?\s*(?:pregnant|gestation)",
        r"\bpoa\b",
        r"period\s*of\s*amenorrhoea",
    ],
}

_NUM = r"[0-9०-९OoIlS|.,]{1,8}"
_DATE_ISO = r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
_DATE_DMY = r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})"
_DATE_TEXT = r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})"
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def clean_number(token: str):
    """Normalize a numeric token found in a numeric context."""
    t = (token or "").strip().translate(_DEVANAGARI)
    t = re.sub(r"[^0-9OoIlSs|.,]", "", t).translate(_DIGIT_CONFUSIONS)
    t = t.replace(",", ".")
    if t.count(".") > 1:
        head, *rest = t.split(".")
        t = head + "." + "".join(rest)
    t = t.strip(".")
    if not t or not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    return t


def _as_number(token: str):
    cleaned = clean_number(token)
    if cleaned is None:
        return None
    return float(cleaned) if "." in cleaned else int(cleaned)


def _match_label(line_text, field):
    for pattern in _LABELS[field]:
        m = re.search(pattern, line_text, flags=re.IGNORECASE)
        if m:
            return m
    return None


def _bp_after_label(hay):
    """First N/N blood-pressure pair after the BP label that is not a
    reference bound ("< 140 / 90"). Returns the re match or None."""
    for m in re.finditer(
        r"(?:bp|blood\s*pressure|b\.p\.?)\D{0,10}?(\d{2,3})\s*[/\\]\s*(\d{2,3})", hay
    ):
        before = hay[max(0, m.start(1) - 3):m.start(1)]
        if _REF_PREFIX.search(before):
            continue
        return m
    return None


_NUM_TOKEN = re.compile(r"([OolI|]?[0-9०-९.,][0-9०-९OoIlSs|.,]*)\s*(°?\s*[CFfc])?")
_RANGE_CONT = re.compile(r"\s*[-–]\s*[0-9०-९.,][0-9०-९OoIlSs|.,]*")
_REF_PREFIX = re.compile(r"[<>≤≥]\s*$")


def _find_value_after_label(line_text, label_end):
    """Best number-looking token after the label match. The token must
    contain at least one real digit — label words like "glycosylated" contain
    OCR-confusable letters (s, l) and must never be read as numbers.

    The token must effectively START with a digit: a leading letter before
    the digits is graphics bleed from a neighbouring barcode/box
    ("Age / Sex  S20 YRS" — the S is barcode noise, not a 5). ONE digit-look
    alike glyph (O, o, l, I, |) may precede the digits — those are genuine
    1/0 misreads ("l20 bpm" = 120); letters like S never look like digits.
    Trailing confusable letters stay eligible (real digits misread at the END
    of a number do happen).

    Reference ranges on the same row ("< 140 / 90", "18.5 - 24.9",
    "60 - 100") must NOT be read as the value: tokens that start a
    dash-range or follow a comparison sign are deprioritized — a plain
    token anywhere in the line wins over a range-like one, and the first
    plain token wins over a later plain one. Returns
    (token_or_None, raw, only_ref_left) where only_ref_left means the line
    offered nothing but reference-like tokens."""
    tail = line_text[label_end:]
    first_plain = None
    first_any = None
    i = 0
    while True:
        m = _NUM_TOKEN.search(tail, i)
        if not m:
            break
        start = m.start()
        end = m.end()
        is_ref = False
        cont = _RANGE_CONT.match(tail, end)
        if cont:
            end = cont.end()
            is_ref = True  # first element of a dash range: "18.5 - 24.9"
        before = tail[max(0, start - 3):start]
        if _REF_PREFIX.search(before):
            is_ref = True  # comparison bound: "< 140 / 90"
        if first_any is None:
            first_any = m.group(0).strip()
        if not is_ref and first_plain is None:
            first_plain = m.group(0).strip()
        i = end
    if first_plain is not None:
        return first_plain, first_plain, False
    if first_any is not None:
        return first_any, first_any, True
    return None, "", True


def _temperature_unit(line_text, value):
    """Detect an explicit C/F unit on the line; None when no unit is stated."""
    unit_m = re.search(r"(\d+(?:\.\d+)?)\s*°?\s*([CF])\b", line_text, flags=re.IGNORECASE)
    if unit_m:
        return unit_m.group(2).lower()
    return None


def parse_lines(lines):
    """Extract fields from OCR/direct-text lines.

    Returns (fields, warnings) where fields maps canonical name ->
    {"value", "confidence", "raw_text", "source"} (value may be int/float/
    string-for-date). No plausibility validation happens here.

    Layout tolerance: many report cards (and most PDF text layers) put the
    label on one line and the value on the next ("HBA1C\\n41"), so if a label
    has no value on its own line, the next two lines are checked.
    """
    fields = {}
    warnings = []
    texts = [(line.get("text") or "").strip() for line in lines]
    confs = [float(line.get("conf", 0.0)) for line in lines]
    sources = [line.get("source", "tesseract") for line in lines]

    for i, text in enumerate(texts):
        conf = confs[i]
        source = sources[i]
        low = text.lower()
        if not text:
            continue

        # --- combined "120/80" blood pressure -----------------------------
        bp_m = _bp_after_label(low)
        bp_lookahead_used = False
        if bp_m is None:
            lookahead = " ".join(texts[i + 1:i + 3]).lower()
            if lookahead:
                bp_m = _bp_after_label(lookahead)
                bp_lookahead_used = bp_m is not None
        if bp_m:
            raw_bp = text if not bp_lookahead_used else " / ".join(texts[i + 1:i + 3])
            _set_if_absent(fields, "systolic_bp", _as_number(bp_m.group(1)), raw_bp, conf, source)
            _set_if_absent(fields, "diastolic_bp", _as_number(bp_m.group(2)), raw_bp, conf, source)

        # --- per-label fields ---------------------------------------------
        matched_exact = False
        for field in TARGET_FIELDS:
            if field in ("visit_date",) or field in fields:
                continue
            label_m = _match_label(low, field)
            if not label_m:
                continue
            matched_exact = True
            if field in ("systolic_bp", "diastolic_bp") and (bp_m or "/" in text):
                continue  # combined BP already handled
            token, _raw, only_ref = _find_value_after_label(low, label_m.end())
            token_line = low
            token_conf, token_source = conf, source
            if (not token or only_ref) and i + 1 < len(texts):
                # Label/value on separate lines (PDF text layers, sparse
                # layouts), or the own-line token was only a reference range —
                # a plain token on a following line wins over the range.
                plain_next = ref_next = None
                for j in (i + 1, i + 2):
                    if j >= len(texts):
                        break
                    nxt = texts[j].lower()
                    if not nxt or _any_label_match(nxt):
                        break  # next line starts another field — stop looking
                    tok, _raw2, nxt_ref = _find_value_after_label(nxt, 0)
                    if tok:
                        if plain_next is None and not nxt_ref:
                            plain_next = (tok, nxt, confs[j], sources[j])
                            break
                        if ref_next is None:
                            ref_next = (tok, nxt, confs[j], sources[j])
                if plain_next:
                    token, token_line, token_conf, token_source = plain_next
                elif ref_next and not token:
                    token, token_line, token_conf, token_source = ref_next

            if not token:
                continue

            if field == "body_temperature":
                try:
                    raw_value = float(clean_number(token).replace(",", "."))
                except (AttributeError, ValueError):
                    continue
                from ocr.services.units import normalize_temperature

                unit_context = token_line if token_line != low else text
                value, temp_warning, temp_suggestion = normalize_temperature(
                    raw_value, _temperature_unit(unit_context + " " + text, raw_value)
                )
                if temp_warning:
                    warnings.append(temp_warning)
                _set_if_absent(fields, field, value, text, token_conf, token_source)
                if temp_suggestion and field in fields:
                    fields[field]["suggestion"] = temp_suggestion
                continue

            if field == "gestational_week":
                value = _as_number(token)
                _set_if_absent(fields, field, value, text, token_conf, token_source)
                continue

            value = _as_number(token)
            if value is None:
                continue
            from ocr.services.units import glucose_unit_warning, hba1c_unit_warning

            unit_line = token_line if token_line != low else text
            extra_warning = None
            invalid_unit = False
            if field == "fasting_glucose":
                extra_warning, invalid_unit = glucose_unit_warning("Fasting glucose", unit_line, value)
            elif field == "hba1c":
                extra_warning = hba1c_unit_warning(unit_line, value)
            if extra_warning:
                warnings.append(extra_warning)
            _set_if_absent(fields, field, value, text, token_conf, token_source)
            if invalid_unit and field in fields:
                fields[field]["valid"] = False
                fields[field]["warning"] = (fields[field].get("warning", "") + "; " + extra_warning).strip("; ")

        # --- fuzzy label rescue (garbled labels, e.g. "BOOS TEMPERATURE") --
        from django.conf import settings

        fuzzy_on = getattr(settings, "OCR_ENABLE_FUZZY", True)
        if fuzzy_on and not matched_exact and re.search(r"[0-9०-९]", text) and len(text) >= 8:
            fuzzy_field, ratio, ambiguous = _fuzzy_match_field(low)
            if fuzzy_field and fuzzy_field != "visit_date" and fuzzy_field not in fields:
                digit_m = re.search(r"[0-9०-९]", text)
                token, _raw, _ref = _find_value_after_label(low, digit_m.start())
                if token:
                    value = _as_number(token)
                    if value is not None:
                        conf_penalty = 0.85 if ratio >= 0.85 else 0.7
                        _set_if_absent(fields, fuzzy_field, value, text, conf * conf_penalty, source)
                        if fuzzy_field in fields:
                            fields[fuzzy_field]["fuzzy"] = True
                            fuzzy_warning = (
                                f"Label matched approximately ({int(ratio * 100)}%) — "
                                "verify the field name and value."
                            )
                            fields[fuzzy_field]["warning"] = (
                                fields[fuzzy_field].get("warning", "") + "; " + fuzzy_warning
                            ).strip("; ")
                            warnings.append(fuzzy_warning)
                            if ambiguous:
                                fields[fuzzy_field]["suggestion_candidates"] = [fuzzy_field, ambiguous]
                                warnings.append(
                                    f"Garbled label could be '{fuzzy_field}' or '{ambiguous}' — verify."
                                )

        # --- visit date (first parseable date wins) ------------------------
        if "visit_date" not in fields:
            date_value, date_warning = _parse_date(low)
            if date_value:
                if date_warning:
                    warnings.append(date_warning)
                fields["visit_date"] = {
                    "value": date_value, "confidence": conf, "raw_text": text, "source": source,
                }

    return fields, warnings


def _any_label_match(low_text):
    """True when the line starts a known labeled field (stops lookahead)."""
    return any(_match_label(low_text, f) for f in _LABELS)


def _parse_date(low_text):
    m = re.search(_DATE_ISO, low_text)
    if m:
        yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            warning = None
            if 2040 <= yyyy <= 2200:
                warning = (
                    f"Date year {yyyy} looks like a Bikram Sambat (BS) calendar date — "
                    "please convert to AD and verify."
                )
            return f"{yyyy:04d}-{mm:02d}-{dd:02d}", warning
    m = re.search(_DATE_TEXT, low_text, flags=re.IGNORECASE)
    if m:
        dd, mon, yyyy = int(m.group(1)), _MONTHS.get(m.group(2).lower()), int(m.group(3))
        if mon:
            return f"{yyyy:04d}-{mon:02d}-{dd:02d}", None
    m = re.search(_DATE_DMY, low_text)
    if m:
        first, second, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        bs_warning = None
        if 2040 <= year <= 2200:
            bs_warning = (
                f"Date year {year} looks like a Bikram Sambat (BS) calendar date — "
                "please convert to AD and verify."
            )
        if 1 <= first <= 31 and 1 <= second <= 12 and year >= 1990:
            # Nepal/South-Asia convention is DD/MM/YYYY; state the assumption.
            return (
                f"{year:04d}-{second:02d}-{first:02d}",
                bs_warning or f"Date read as DD/MM/YYYY from '{m.group(0)}' — please verify.",
            )
        if 1 <= first <= 12 and 1 <= second <= 31 and year >= 1990:
            return (
                f"{year:04d}-{second:02d}-{first:02d}",
                bs_warning or f"Date read as MM/DD/YYYY from '{m.group(0)}' — please verify.",
            )
    return None, None


def _set_if_absent(fields, name, value, raw_text, confidence, source):
    if value is None:
        return
    fields[name] = {
        "value": value,
        "confidence": round(min(confidence, 1.0), 3),
        "raw_text": raw_text[:200],
        "source": source,
    }


_FUZZY_PHRASES = [
    ("age", "age"),
    ("body_temperature", "body temperature"), ("body_temperature", "temperature"),
    ("heart_rate", "heart rate"), ("heart_rate", "pulse"),
    ("systolic_bp", "blood pressure"), ("diastolic_bp", "blood pressure"),
    ("systolic_bp", "systolic"), ("diastolic_bp", "diastolic"),
    ("bmi", "body mass index"), ("bmi", "bmi"),
    ("hba1c", "hba1c"), ("hba1c", "glycosylated"), ("hba1c", "hemoglobin"),
    ("fasting_glucose", "fasting blood glucose"), ("fasting_glucose", "fasting glucose"),
    ("fasting_glucose", "blood glucose"), ("fasting_glucose", "glucose"),
    ("fasting_glucose", "blood sugar"),
    ("gestational_week", "gestational"), ("gestational_week", "weeks pregnant"),
    ("visit_date", "date"), ("visit_date", "registered on"),
]
_FUZZY_MIN_RATIO = 0.72
_FUZZY_AMBIGUOUS_GAP = 0.06


def _fuzzy_match_field(line_text):
    """Best fuzzy field for a garbled label line. Returns
    (field_or_None, ratio, ambiguous_field_or_None)."""
    prefix = re.split(r"\d", line_text, 1)[0]
    prefix = re.sub(r"[^a-z ]", " ", prefix).strip()
    prefix = re.sub(r"\s+", " ", prefix)
    if len(prefix) < 4:
        return None, 0.0, None
    scored = []
    for field, phrase in _FUZZY_PHRASES:
        ratio = SequenceMatcher(None, prefix, phrase).ratio()
        if phrase in prefix:
            ratio = max(ratio, 0.95)
        scored.append((ratio, field))
    scored.sort(reverse=True)
    best_ratio, best_field = scored[0]
    if best_ratio < _FUZZY_MIN_RATIO:
        return None, best_ratio, None
    ambiguous = None
    if len(scored) > 1 and best_ratio < 0.9 and scored[1][0] > best_ratio - _FUZZY_AMBIGUOUS_GAP \
            and scored[1][1] != best_field:
        ambiguous = scored[1][1]
    return best_field, best_ratio, ambiguous
