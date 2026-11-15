"""Field-level accuracy metrics for the OCR evaluation.

- Exact match for integer-like fields (age, heart_rate, systolic_bp,
  diastolic_bp, hba1c, gestational_week).
- Tolerance for floats: body_temperature ±0.15 (rounding), bmi ±0.11,
  fasting_glucose ±0.11.
- "Dangerous error": the extracted value is WRONG (beyond tolerance) but
  still passes the PLAUSIBILITY_RANGES validation — the worst failure mode,
  because it looks trustworthy in the UI.
"""
from mlcore.constants import PLAUSIBILITY_RANGES

INT_FIELDS = {"age", "heart_rate", "systolic_bp", "diastolic_bp", "hba1c", "gestational_week"}
FLOAT_TOL = {"body_temperature": 0.15, "bmi": 0.11, "fasting_glucose": 0.11}


def value_correct(field, truth, extracted):
    if extracted is None:
        return False
    try:
        t, e = float(truth), float(extracted)
    except (TypeError, ValueError):
        return str(truth).strip() == str(extracted).strip()
    if field in INT_FIELDS:
        return abs(t - e) < 0.5
    return abs(t - e) <= FLOAT_TOL.get(field, 0.11)


def passes_validation(field, value):
    """True when a (wrong) value would still look plausible to the validator."""
    if field not in PLAUSIBILITY_RANGES:
        return True
    low, high = PLAUSIBILITY_RANGES[field]
    try:
        return low <= float(value) <= high
    except (TypeError, ValueError):
        return False


def compare_card(truth, extracted_fields):
    """Compare one card. Returns (per_field dict, n_correct, n_dangerous)."""
    per_field = {}
    correct = 0
    dangerous = 0
    for field, truth_value in truth.items():
        entry = extracted_fields.get(field) or {}
        value = entry.get("value")
        ok = value_correct(field, truth_value, value)
        wrong_but_plausible = (not ok) and value is not None and passes_validation(field, value)
        per_field[field] = {
            "truth": truth_value,
            "extracted": value,
            "correct": ok,
            "dangerous": wrong_but_plausible,
            "flagged": entry.get("valid") is False,
        }
        correct += int(ok)
        dangerous += int(wrong_but_plausible)
    return per_field, correct, dangerous
