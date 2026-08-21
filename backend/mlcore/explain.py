"""SHAP explainability for tree ensembles.

Explanation wording rule (SAFETY.md): SHAP values describe which features
contributed most to the MODEL'S PREDICTION. They are never medical causation
statements about the patient.
"""
import logging

import numpy as np

from mlcore.constants import FEATURE_LABELS

logger = logging.getLogger(__name__)

EXPLANATION_DISCLAIMER = (
    "These features contributed most to the model's prediction. "
    "They are statistical contributions, not medical causes."
)


def explain_prediction(bundle, vector):
    """Return top contributing features for the predicted class.

    bundle: persisted joblib bundle (dict with model, preprocessor, features).
    vector: preprocessed 1-D feature vector in canonical order.
    """
    try:
        import shap

        model = bundle["model"]
        features = bundle["features"]
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(np.asarray(vector, dtype=np.float64).reshape(1, -1))

        # sklearn/xgboost API differences: shap returns either
        # list-per-class (n_features, n_classes) or (n_samples, n_features, n_classes)
        predicted_class = bundle.get("_predicted_index", 0)
        sv = np.asarray(shap_values)
        if sv.ndim == 3:  # (1, n_features, n_classes)
            values = sv[0, :, predicted_class]
        elif sv.ndim == 2 and sv.shape[-1] == len(features):  # binary or per-class list case
            values = sv[0]
        elif isinstance(shap_values, list):  # legacy list layout: per-class (1, n_features)
            values = np.asarray(shap_values[predicted_class])[0]
        else:
            values = sv[0]

        order = np.argsort(-np.abs(values))[:8]
        explanation = [
            {
                "feature": features[i],
                "label": FEATURE_LABELS.get(features[i], features[i]),
                "value": float(vector[i]),
                "impact": round(float(values[i]), 4),
                "direction": "increasing" if values[i] > 0 else ("decreasing" if values[i] < 0 else "neutral"),
            }
            for i in order
        ]
        return {
            "method": "SHAP (TreeExplainer)",
            "target_class": bundle.get("_predicted_label"),
            "features": explanation,
            "disclaimer": EXPLANATION_DISCLAIMER,
        }
    except Exception:
        # Explainability must never take the prediction endpoint down.
        logger.exception("SHAP explanation failed; returning fallback importance")
        return {
            "method": "unavailable",
            "target_class": bundle.get("_predicted_label"),
            "features": [],
            "disclaimer": EXPLANATION_DISCLAIMER,
            "note": "Feature-level explanation could not be computed for this prediction.",
        }
