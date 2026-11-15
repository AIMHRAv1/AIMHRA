"""Unit handling for OCR-extracted values.

UNIT POLICY (see also ocr/UNIT_POLICY.md):

Temperature
- Convert Celsius -> Fahrenheit ONLY when an explicit C/°C unit is detected
  on the line, AND the raw value is itself a plausible Celsius reading
  (30-45 °C). Nonsense raw values are never converted.
- If NO unit is present, never guess from the value: keep the raw value,
  flag it amber ("unit unclear"), and attach the Fahrenheit conversion as a
  SUGGESTION for the operator. The suggestion is never auto-applied.

Glucose / HbA1c
- Unit text and the plausible range are evaluated TOGETHER. The dataset's
  glucose columns hold mmol/L-like values (3.5-8.9) and HbA1c mmol/mol-like
  values (30-50), despite the source header saying mg/dl (see
  mlcore/constants.DATASET_NOTES).
- A mg/dL label next to an in-range mmol-scale value is AMBIGUOUS: amber
  warning, never silently converted.
- A value outside the plausible range is invalid regardless of the printed
  unit; the decimal-suggestion layer (validate.py) may propose a decimal
  fix for the operator.

No function here ever silently converts glucose or HbA1c.
"""


def celsius_to_fahrenheit(value: float) -> float:
    return round(value * 9.0 / 5.0 + 32.0, 1)


def normalize_temperature(value: float, unit):
    """Return (value, warning, suggestion).

    value     — what the parser should store (raw unless explicit C).
    warning   — amber text or None ("" means no warning).
    suggestion— {"value": fahrenheit} offered to the operator when no unit
                was present and the raw value looks like Celsius, or None.
    """
    unit_l = (unit or "").strip().lower()
    if unit_l in ("c", "°c", "celcius", "celsius"):
        # Validate BEFORE converting: only a plausible Celsius reading converts.
        if not (30.0 <= value <= 45.0):
            return value, f"Temperature {value} says °C but is not a plausible Celsius value — please correct.", None
        return celsius_to_fahrenheit(value), None, None
    if unit_l in ("f", "°f", "fahrenheit"):
        return round(value, 1), None, None
    # No unit stated: never guess. Keep raw, flag amber, offer the conversion.
    warning = f"Temperature {value} has no unit — unclear whether °C or °F. Please verify."
    suggestion = {"value": celsius_to_fahrenheit(value)} if value < 45 else None
    return value, warning, suggestion


def glucose_unit_warning(label: str, line_text: str, value):
    """Warning for glucose/HbA1c values, evaluating unit text and the
    plausible scale together. Never converts.

    Returns (warning_or_empty, invalid_bool).
    """
    text = (line_text or "").lower().replace(" ", "")
    label_l = label.lower()
    # Dataset scales: fasting glucose ~2-20 (mmol/L-like), HbA1c ~20-60
    # (mmol/mol-like) — the same ranges as PLAUSIBILITY_RANGES.
    mmol_scale = 2.0 <= float(value) <= 20.0 if label_l.startswith("fasting") else 20.0 <= float(value) <= 60.0

    if "mg/dl" in text or "mg%" in text:
        if mmol_scale:
            return (f"{label}: the card says mg/dL but the value {value} matches the system's "
                    "mmol-scale range. Units are ambiguous — please verify (value NOT converted)."), False
        return (f"{label}: card says mg/dL and value {value} does not match the system's scale — "
                "please correct."), True
    if "mmol" in text:
        return "", False
    # No unit on the line: plausibility alone decides (validator handles it).
    return "", False


def hba1c_unit_warning(line_text: str, value):
    """HbA1c-specific ambiguity: a '%' label next to an mmol/mol-scale value."""
    text = (line_text or "").lower().replace(" ", "")
    if "%" in text and 20.0 <= float(value) <= 60.0:
        return (f"HbA1c: card shows % but value {value} matches the system's mmol/mol-like scale. "
                "Units are ambiguous — please verify (value NOT converted).")
    return None
