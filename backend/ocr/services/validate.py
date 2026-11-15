"""Plausibility validation for OCR-extracted values.

Reuses mlcore.constants.PLAUSIBILITY_RANGES — the SAME documented ranges the
training data was cleaned with and the API serializer enforces. This module
only FLAGS fields (valid / warning); it never corrects values.
"""
from datetime import date as date_type

from django.utils import timezone

from mlcore.constants import PLAUSIBILITY_RANGES


def validate_fields(fields, today=None):
    """Annotate each field entry with valid/warning. Returns (fields, summary).

    fields: parser output {name: {"value", ...}} (mutated in place with
    "valid" and "warning" keys). summary counts are for audit logging.
    """
    today = today or timezone.localdate()
    flagged = 0

    for name, entry in fields.items():
        value = entry.get("value")
        warnings = []

        if name == "visit_date":
            try:
                parsed = date_type.fromisoformat(str(value))
            except (TypeError, ValueError):
                parsed = None
            if parsed and parsed > today:
                warnings.append("Visit date is in the future — please correct.")
                entry["valid"] = False
            else:
                entry["valid"] = True
            entry["warning"] = "; ".join(warnings)
            continue

        if name == "gestational_week":
            if value is not None and not (1 <= float(value) <= 45):
                warnings.append(f"Gestational week {value} is outside 1-45 — please correct.")
                entry["valid"] = False
            else:
                entry["valid"] = True
            entry["warning"] = "; ".join(warnings)
            continue

        if name in PLAUSIBILITY_RANGES:
            low, high = PLAUSIBILITY_RANGES[name]
            if value is None:
                entry["valid"] = False
            elif not (low <= float(value) <= high):
                warnings.append(f"Value {value} is outside the plausible range {low}-{high} — please correct.")
                entry["valid"] = False
                # Decimal suggestion: an implausible value that becomes
                # plausible with a decimal point inserted (365 -> 36.5,
                # 975 -> 97.5) is offered as an amber SUGGESTION — never
                # auto-applied (the raw value stays and valid stays False).
                from django.conf import settings

                suggestion = (
                    decimal_suggestion(name, value)
                    if getattr(settings, "OCR_ENABLE_SUGGESTIONS", True)
                    else None
                )
                if suggestion is not None:
                    entry["suggestion"] = {"value": suggestion}
                    warnings.append(
                        f"Possible missing decimal point — did you mean {suggestion}? (suggestion only, not applied)"
                    )
            else:
                entry["valid"] = True

        entry["warning"] = "; ".join(warnings)

    # Cross-field: diastolic must not exceed systolic (same rule as the API).
    sys_bp = fields.get("systolic_bp", {}).get("value")
    dia_bp = fields.get("diastolic_bp", {}).get("value")
    if sys_bp is not None and dia_bp is not None and float(dia_bp) > float(sys_bp):
        for name in ("systolic_bp", "diastolic_bp"):
            entry = fields[name]
            entry["valid"] = False
            extra = "Diastolic BP exceeds systolic BP — one of the two is wrong."
            entry["warning"] = (entry.get("warning") + "; " + extra).strip("; ")

    # Count flagged FIELDS (not individual rule hits).
    flagged = sum(1 for entry in fields.values() if not entry.get("valid", False))
    summary = {
        "fields_extracted": len(fields),
        "fields_flagged": flagged,
    }
    return fields, summary


# Field-specific format rules: how many decimal places each measurement is
# expected to have on a report card (used for the missing-decimal suggestion).
EXPECTED_DECIMALS = {
    "body_temperature": 1,   # 97.5
    "bmi": 1,                # 22.1
    "fasting_glucose": 1,    # 5.7
    "hba1c": 0,              # 41 (integer in dataset units)
    "age": 0, "heart_rate": 0, "systolic_bp": 0, "diastolic_bp": 0,
}


def decimal_suggestion(field, value):
    """Return the plausible value obtained by inserting a decimal point into
    `value` (value / 10^k), rounded to the field's expected decimals, or
    None. Suggestion only — the caller must never apply it automatically."""
    if field not in PLAUSIBILITY_RANGES:
        return None
    low, high = PLAUSIBILITY_RANGES[field]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    dp = EXPECTED_DECIMALS.get(field, 1)
    for k in (1, 2, 3):
        candidate = round(v / (10 ** k), dp)
        if low <= candidate <= high:
            return candidate
    return None


def build_missing(fields, target_fields):
    """Target fields without a usable value."""
    return [name for name in target_fields if not fields.get(name, {}).get("value")]
