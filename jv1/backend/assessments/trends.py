"""Longitudinal risk-trend computation from the patient's prediction series.

This is descriptive analytics over stored predictions — the system does NOT
predict future risk (no temporal model is trained; the dataset has no
visit-level fields).
"""
from mlcore.constants import RISK_LEVEL_ORDER


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
