"""Model registry: loads the production model, serves predictions with
SHAP explanations, records which model version made each prediction."""
import logging
import threading

import joblib
import numpy as np

from django.conf import settings
from mlcore.constants import FEATURES, RISK_LEVELS
from mlcore.exceptions import ModelUnavailableError

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE = {"bundle": None, "version": None, "model_id": None}


def _production_row():
    from mlcore.models import ModelVersion

    return (
        ModelVersion.objects.filter(status=ModelVersion.STATUS_PRODUCTION)
        .order_by("-trained_at")
        .first()
    )


def get_production_bundle(force_reload=False):
    """Thread-safe cached load of the production model artifact."""
    with _LOCK:
        row = _production_row()
        if row is None:
            raise ModelUnavailableError(
                "No production model is registered. Run `python manage.py train_models` first."
            )
        if not force_reload and _CACHE["model_id"] == row.id and _CACHE["bundle"] is not None:
            return _CACHE["bundle"], row

        import pathlib

        path = pathlib.Path(row.artifact_path)
        if not path.is_absolute():
            path = settings.BASE_DIR / row.artifact_path
        if not path.exists():
            raise ModelUnavailableError(
                f"Model artifact for {row.name} {row.version} is missing at {path}. "
                "Retrain the model or restore the artifacts directory."
            )
        try:
            bundle = joblib.load(path)
        except Exception as exc:
            raise ModelUnavailableError(f"Model artifact could not be loaded: {exc}")

        _CACHE.update(bundle=bundle, version=row.version, model_id=row.id)
        return bundle, row


def predict(features_dict):
    """Predict risk for one patient.

    features_dict: {age, body_temperature, heart_rate, systolic_bp, diastolic_bp,
                    bmi, hba1c, fasting_glucose}
    Returns dict with risk_level, probabilities, per-class confidence, model
    info and SHAP explanation.
    """
    from mlcore.explain import explain_prediction
    from mlcore.preprocessing import Preprocessor

    missing = [f for f in FEATURES if f not in features_dict or features_dict[f] is None]
    if missing:
        raise ModelUnavailableError(f"Missing required features for prediction: {missing}")

    bundle, row = get_production_bundle()
    preprocessor = Preprocessor.from_dict(bundle["preprocessor"])

    raw = np.array([[float(features_dict[f]) for f in FEATURES]], dtype=np.float64)
    X = preprocessor.transform(raw)

    model = bundle["model"]
    proba = model.predict_proba(X)[0]
    classes = list(bundle["classes"])
    best = int(np.argmax(proba))
    predicted = classes[best]

    # Attach prediction context for the SHAP layer.
    bundle["_predicted_index"] = best
    bundle["_predicted_label"] = predicted

    explanation = explain_prediction(bundle, X[0])

    return {
        "risk_level": predicted,
        "probabilities": {cls: round(float(p), 4) for cls, p in zip(classes, proba)},
        "probability": round(float(proba[best]), 4),
        "model": {"name": row.name, "version": row.version, "id": row.id},
        "explanation": explanation,
    }


def feature_importance(bundle=None):
    """Global feature importance for the production (or given) model."""
    if bundle is None:
        bundle, _row = get_production_bundle()
    model = bundle["model"]
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return []
    order = np.argsort(-importances)
    return [
        {"feature": bundle["features"][i], "importance": round(float(importances[i]), 4)}
        for i in order
    ]
