"""Evaluation utilities. Models are evaluated on the held-out test split only."""
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from mlcore.constants import RISK_LEVELS

HIGH = "high risk"


def evaluate_classifier(y_true, y_pred, y_proba=None, labels=None):
    """Full metric set. `y_proba` (n, n_classes) enables ROC-AUC (OVR macro).

    High-risk recall is reported separately because a missed high-risk
    maternal case is the costliest error class in this domain.
    """
    labels = labels or RISK_LEVELS
    present = [l for l in labels if l in set(y_true) or l in set(y_pred)]
    per_class_recall = recall_score(y_true, y_pred, labels=present, average=None, zero_division=0)
    per_class = {
        label: {
            "precision": float(precision_score(y_true, y_pred, labels=[label], average="macro", zero_division=0)),
            "recall": float(per_class_recall[i]),
            "f1": float(f1_score(y_true, y_pred, labels=[label], average="macro", zero_division=0)),
        }
        for i, label in enumerate(present)
    }
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "high_risk_recall": float(
            recall_score(y_true, y_pred, labels=[HIGH], average="macro", zero_division=0)
            if HIGH in present else 0.0
        ),
        "per_class": per_class,
        "confusion_matrix": {
            "labels": present,
            "matrix": confusion_matrix(y_true, y_pred, labels=present).tolist(),
        },
    }
    if y_proba is not None and len(present) > 1:
        try:
            # sklearn expects probability columns ordered by sorted(present);
            # our columns follow the canonical RISK_LEVELS order, so reorder.
            import numpy as np

            proba = np.asarray(y_proba)
            order = [RISK_LEVELS.index(l) for l in sorted(present)]
            metrics["roc_auc_ovr_macro"] = float(
                roc_auc_score(y_true, proba[:, order], multi_class="ovr", average="macro", labels=sorted(present))
            )
        except ValueError:
            metrics["roc_auc_ovr_macro"] = None
    else:
        metrics["roc_auc_ovr_macro"] = None
    return metrics


def selection_score(metrics, criterion):
    """Configurable production-model criterion. Accuracy is never the sole basis.

    high_risk_recall_then_f1 (default): prioritize catching high-risk cases,
      break ties with macro F1, then AUC.
    macro_f1 / accuracy: explicit alternatives for experiments.
    """
    if criterion == "macro_f1":
        return (metrics["f1_macro"], metrics.get("roc_auc_ovr_macro") or 0.0)
    if criterion == "accuracy":
        return (metrics["accuracy"], metrics["f1_macro"])
    # default: high_risk_recall_then_f1
    return (
        metrics["high_risk_recall"],
        metrics["f1_macro"],
        metrics.get("roc_auc_ovr_macro") or 0.0,
    )
