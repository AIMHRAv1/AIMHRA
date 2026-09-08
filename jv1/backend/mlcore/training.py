"""Training pipeline: stratified split -> fit preprocessing -> train RF & XGB
-> evaluate on test only -> persist artifacts -> register versions.

Class imbalance note: the dataset is close to balanced (32.8% / 33.5% / 33.7%),
so resampling (SMOTE) is unnecessary and would only inject synthetic noise.
Both models still use class weights as a safeguard; the decision is recorded
in the training config stored on each ModelVersion row.
"""
import json
import logging
import time
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from mlcore import evaluation as ev
from mlcore.constants import FEATURES, PLAUSIBILITY_RANGES, RISK_LEVELS, RISK_LEVEL_ORDER
from mlcore.dataset import clean_dataset, dataset_md5, feature_matrix, load_raw_dataset, validate_dataset
from mlcore.preprocessing import Preprocessor

logger = logging.getLogger(__name__)

RANDOM_STATE = 42


def _make_random_forest():
    return RandomForestClassifier(
        n_estimators=400,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )


def _make_xgboost():
    return XGBClassifier(
        n_estimators=400,
        learning_rate=0.08,
        max_depth=6,
        subsample=0.9,
        colsample_bytree=0.8,
        tree_method="hist",
        random_state=RANDOM_STATE,
        eval_metric="mlogloss",
    )


def build_models():
    return {"RandomForest": _make_random_forest(), "XGBoost": _make_xgboost()}


TRAIN_CONFIG = {
    "split": {"train": 0.70, "validation": 0.15, "test": 0.15, "stratified": True, "random_state": RANDOM_STATE},
    "class_imbalance": {
        "strategy": "class_weights",
        "rationale": "Classes are near-balanced (33/33/33); resampling rejected to avoid synthetic noise.",
    },
    "preprocessing": "median imputation fitted on training split only",
    "models": {
        "RandomForest": {"n_estimators": 400, "min_samples_leaf": 2, "class_weight": "balanced_subsample"},
        "XGBoost": {"n_estimators": 400, "learning_rate": 0.08, "max_depth": 6, "subsample": 0.9, "colsample_bytree": 0.8},
    },
    "evaluation": "held-out test split only; high-risk recall prioritized for model selection",
}


def train_all(dataset_path, artifacts_dir, quick=False):
    """Run the full pipeline. `quick=True` trains tiny models (used by tests
    and smoke checks, never registered as production)."""
    import pathlib

    artifacts_dir = pathlib.Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    md5 = dataset_md5(dataset_path)
    raw = load_raw_dataset(dataset_path)
    validation_report = validate_dataset(raw, RISK_LEVELS)
    df, cleaning_stats = clean_dataset(raw)
    logger.info("Dataset cleaned: %s", cleaning_stats)

    X = feature_matrix(df)
    y = df["risk_level"].to_numpy()
    # XGBoost requires integer labels. Encode into indices of RISK_LEVELS so
    # probabilities always align with the canonical class list (both models).
    y_enc = np.array([RISK_LEVEL_ORDER[v] for v in y])

    # Stratified 70/15/15 split. Validation is used only for training-time
    # sanity checks; all reported metrics come from the test split.
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X, y_enc, test_size=0.15, stratify=y_enc, random_state=RANDOM_STATE
    )
    relative_val = 0.15 / 0.85
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=relative_val, stratify=y_trainval, random_state=RANDOM_STATE
    )

    preprocessor = Preprocessor().fit(X_train)
    X_train_p = preprocessor.transform(X_train)
    X_val_p = preprocessor.transform(X_val)
    X_test_p = preprocessor.transform(X_test)

    # Human-readable labels for evaluation output.
    decode = np.array(RISK_LEVELS)
    y_train_lbl, y_val_lbl, y_test_lbl = decode[y_train], decode[y_val], decode[y_test]

    results = []
    builders = build_models()
    if quick:
        builders = {
            "RandomForest": RandomForestClassifier(n_estimators=10, random_state=RANDOM_STATE, n_jobs=-1),
            "XGBoost": XGBClassifier(n_estimators=10, max_depth=3, tree_method="hist", random_state=RANDOM_STATE, eval_metric="mlogloss"),
        }

    for name, model in builders.items():
        started = time.time()
        model.fit(X_train_p, y_train)
        val_metrics = ev.evaluate_classifier(y_val_lbl, decode[model.predict(X_val_p)])
        y_pred = decode[model.predict(X_test_p)]
        y_proba = model.predict_proba(X_test_p)
        test_metrics = ev.evaluate_classifier(y_test_lbl, y_pred, y_proba)
        train_seconds = round(time.time() - started, 2)

        artifact_path = artifacts_dir / f"{name.lower()}_{'quick' if quick else 'full'}.joblib"
        bundle = {
            "model_name": name,
            "model": model,
            "preprocessor": preprocessor.to_dict(),
            "features": FEATURES,
            # Classes in probability-column order: model.classes_ are indices
            # into RISK_LEVELS; store the canonical names for readability.
            "classes": RISK_LEVELS,
            "dataset_md5": md5,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "train_config": TRAIN_CONFIG,
        }
        joblib.dump(bundle, artifact_path)

        results.append(
            {
                "name": name,
                "artifact_path": str(artifact_path),
                "bundle": bundle,
                "validation_metrics": val_metrics,
                "test_metrics": test_metrics,
                "train_seconds": train_seconds,
            }
        )
        logger.info("%s trained in %ss | test f1_macro=%.4f high_risk_recall=%.4f",
                    name, train_seconds, test_metrics["f1_macro"], test_metrics["high_risk_recall"])

    return {
        "dataset_md5": md5,
        "dataset_validation": validation_report,
        "cleaning_stats": cleaning_stats,
        "split_sizes": {
            "train": int(X_train.shape[0]),
            "validation": int(X_val.shape[0]),
            "test": int(X_test.shape[0]),
        },
        "train_config": TRAIN_CONFIG,
        "plausibility_ranges": {k: list(v) for k, v in PLAUSIBILITY_RANGES.items()},
        "results": results,
    }
