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
        metrics["calibration"] = calibration_metrics(y_true, y_proba, labels=labels)
    else:
        metrics["roc_auc_ovr_macro"] = None
    return metrics


def calibration_metrics(y_true, y_proba, labels=None, n_bins=10):
    """Multiclass calibration: Brier score and expected calibration error.

    Brier (multiclass): mean over samples of sum_c (p_c - 1{y==c})^2; lower
    is better, 0 is perfect. ECE: confidence-binned |accuracy - confidence|
    weighted by bin size (10 equal-width bins over [0, 1]). Pure numpy — no
    additional dependencies. These describe probability quality on THIS
    dataset only; they are not clinical validation."""
    labels = labels or RISK_LEVELS
    proba = np.asarray(y_proba, dtype=np.float64)
    true_idx = np.array([labels.index(t) for t in y_true])
    onehot = np.zeros_like(proba)
    onehot[np.arange(len(true_idx)), true_idx] = 1.0
    brier = float(np.mean(np.sum((proba - onehot) ** 2, axis=1)))

    confidences = proba.max(axis=1)
    predictions = proba.argmax(axis=1)
    accuracies = (predictions == true_idx).astype(np.float64)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        in_bin = (confidences > lo) & (confidences <= hi) if lo > 0 else (confidences >= lo) & (confidences <= hi)
        if in_bin.any():
            ece += float(in_bin.mean() * abs(accuracies[in_bin].mean() - confidences[in_bin].mean()))
    return {
        "brier_multiclass": round(brier, 4),
        "expected_calibration_error": round(ece, 4),
        "n_bins": n_bins,
    }


def bootstrap_ci(y_true, y_pred, metric_fn, n_resamples=200, seed=42):
    """Percentile bootstrap 95% CI for a scalar metric. metric_fn receives
    (y_true_subset, y_pred_subset) and returns a float."""
    rng = np.random.RandomState(seed)
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    n = len(y_true)
    values = []
    for _ in range(n_resamples):
        idx = rng.randint(0, n, size=n)
        values.append(float(metric_fn(y_true[idx], y_pred[idx])))
    values.sort()
    lo = values[int(0.025 * n_resamples)]
    hi = values[int(0.975 * n_resamples) - 1]
    return {"low": round(lo, 4), "high": round(hi, 4), "resamples": n_resamples}


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
