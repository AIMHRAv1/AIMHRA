"""Longitudinal risk-trend computation from the patient's prediction series.

This is descriptive analytics over stored predictions — the system does NOT
predict future risk (no temporal model is trained; the dataset has no
visit-level fields).
"""
from mlcore.constants import RISK_LEVEL_ORDER

MEASUREMENT_FIELDS = (
    "systolic_bp",
    "diastolic_bp",
    "heart_rate",
    "body_temperature",
    "bmi",
    "hba1c",
    "fasting_glucose",
)


def compute_trend(predictions):
    """Compare optional risk classifications from oldest-first visit records."""
    if not predictions:
        return {"current": None, "previous": None, "direction": "unknown", "status": "no_data"}

    current = predictions[-1].get("risk_level")
    previous = predictions[-2].get("risk_level") if len(predictions) >= 2 else None

    if current is None:
        direction, status = "unknown", "no_data"
    elif previous is None:
        direction, status = "unknown", "baseline"
    else:
        diff = RISK_LEVEL_ORDER[current] - RISK_LEVEL_ORDER[previous]
        direction = "increasing" if diff > 0 else ("decreasing" if diff < 0 else "stable")
        status = {"increasing": "increasing", "decreasing": "improving", "stable": "stable"}[direction]

    series = [p["risk_level"] for p in predictions if p.get("risk_level") is not None]
    return {
        "current": current,
        "previous": previous,
        "direction": direction,
        "status": status,
        "sequence": series,
        "visits": len(predictions),
    }


def _triggered_measurement_rules(feature, value):
    if value is None:
        return []

    from assessments.rules.engine import evaluate, load_rules

    feature_rule_ids = {
        rule["id"]
        for rule in load_rules()["rules"]
        if rule.get("type") == "vital" and rule.get("feature") == feature
    }
    outcome = evaluate({feature: value}, [])
    return [rule for rule in outcome["triggered"] if rule["id"] in feature_rule_ids]


def compute_measurement_trends(history):
    """Compare adjacent chronological assessments without adding thresholds."""
    if not history:
        return []

    previous = history[-2] if len(history) >= 2 else None
    current = history[-1]
    changes = []

    for feature in MEASUREMENT_FIELDS:
        before = previous.get(feature) if previous else None
        after = current.get(feature)
        if before is None or after is None:
            direction = "baseline" if previous is None else "unavailable"
            difference = None
        else:
            difference = round(float(after) - float(before), 2)
            direction = "increased" if difference > 0 else ("decreased" if difference < 0 else "unchanged")

        current_rules = _triggered_measurement_rules(feature, after)
        previous_rule_ids = {
            rule["id"] for rule in _triggered_measurement_rules(feature, before)
        }
        newly_triggered_rules = (
            [rule for rule in current_rules if rule["id"] not in previous_rule_ids]
            if previous is not None and before is not None else []
        )
        if after is None:
            rule_status = "measurement_unavailable"
        elif previous is None:
            rule_status = "baseline"
        elif before is None:
            rule_status = "previous_value_unavailable"
        elif newly_triggered_rules:
            rule_status = "newly_triggered"
        elif current_rules:
            rule_status = "ongoing"
        else:
            rule_status = "no_trigger"
        changes.append({
            "feature": feature,
            "previous": before,
            "current": after,
            "difference": difference,
            "direction": direction,
            "rule_status": rule_status,
            "current_triggered_rules": current_rules,
            "newly_triggered_rules": newly_triggered_rules,
        })

    return changes
