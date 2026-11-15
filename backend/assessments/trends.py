"""Longitudinal analytics over stored assessments.

Two clearly separated layers:

- compute_trend: descriptive risk-CLASS trend from the prediction series.
  The system does NOT predict future risk (no temporal model is trained; the
  dataset has no visit-level fields).
- measurement_series / compare_measurements: deterministic arithmetic over
  ACTUAL stored measurements between visit dates. These are plain
  calculations, explicitly NOT machine learning; clinical interpretation is
  left to the separately-configured trend rules (see rules/trend_rules.json,
  disabled until clinically reviewed).
"""
from mlcore.constants import FEATURES, FEATURE_LABELS, RISK_LEVEL_ORDER


def compute_trend(predictions):
    """predictions: list of Prediction-like dicts, oldest first.
    Returns current/previous risk, direction and stable/improving/increasing
    status. 'improving' means a move to a lower-risk class."""
    if not predictions:
        return {"current": None, "previous": None, "direction": "unknown", "status": "no_data"}

    current = predictions[-1]["risk_level"]
    previous = predictions[-2]["risk_level"] if len(predictions) >= 2 else None

    if previous is None:
        direction, status = "unknown", "baseline"
    else:
        diff = RISK_LEVEL_ORDER[current] - RISK_LEVEL_ORDER[previous]
        direction = "increasing" if diff > 0 else ("decreasing" if diff < 0 else "stable")
        status = {"increasing": "increasing", "decreasing": "improving", "stable": "stable"}[direction]

    series = [p["risk_level"] for p in predictions]
    return {
        "current": current,
        "previous": previous,
        "direction": direction,
        "status": status,
        "sequence": series,
        "visits": len(predictions),
    }


def measurement_series(patient):
    """Actual stored measurements per assessment, oldest first.

    Returns {"visits": [...], "features": {...}} — no interpretation here.
    Each visit carries the assessment id, visit_date, gestational_week and
    the 8 raw feature values."""
    from assessments.models import Assessment

    rows = (
        Assessment.objects.filter(patient=patient)
        .order_by("visit_date", "id")
    )
    visits = [
        {
            "assessment_id": a.id,
            "visit_date": a.visit_date.isoformat(),
            "gestational_week": a.gestational_week,
            **{f: getattr(a, f) for f in FEATURES},
        }
        for a in rows
    ]
    return {"visits": visits, "features": list(FEATURES)}


def _pct_change(previous, latest):
    if previous in (None, 0) or latest is None:
        return None
    return round((latest - previous) / abs(previous) * 100.0, 1)


def compare_measurements(series):
    """Previous-vs-latest comparison per feature. Pure arithmetic:
    absolute delta, percent delta and direction. No thresholds, no ML —
    clinical meaning is decided exclusively by the trend-rule engine."""
    visits = (series or {}).get("visits") or []
    features = (series or {}).get("features") or FEATURES
    comparisons = []
    if len(visits) < 2:
        return comparisons
    previous, latest = visits[-2], visits[-1]
    for feature in features:
        prev_value, latest_value = previous[feature], latest[feature]
        delta = None if (prev_value is None or latest_value is None) else round(latest_value - prev_value, 2)
        comparisons.append({
            "feature": feature,
            "label": FEATURE_LABELS.get(feature, feature),
            "previous_visit": previous["visit_date"],
            "latest_visit": latest["visit_date"],
            "previous_value": prev_value,
            "latest_value": latest_value,
            "delta": delta,
            "percent_change": _pct_change(prev_value, latest_value),
            "direction": (
                "increased" if (delta or 0) > 0
                else ("decreased" if (delta or 0) < 0 else "unchanged")
            ),
        })
    return comparisons
