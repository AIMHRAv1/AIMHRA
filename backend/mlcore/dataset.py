"""Dataset loading, validation and reproducible cleaning.

Every cleaning decision here is counted and reported — nothing is removed
silently (see management command `inspect_dataset`).
"""
import hashlib
import logging

import numpy as np
import pandas as pd

from mlcore.constants import COLUMN_MAP, FEATURES, PLAUSIBILITY_RANGES

logger = logging.getLogger(__name__)


def dataset_md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def load_raw_dataset(path):
    """Load the CSV and normalize column names via COLUMN_MAP."""
    df = pd.read_csv(path)
    # Strip accidental whitespace in headers (e.g. 'Body Temperature(F) ').
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing expected columns: {missing}")
    df = df.rename(columns=COLUMN_MAP)
    df["risk_level"] = df["risk_level"].str.strip().str.lower()
    return df


def validate_dataset(df, expected_levels):
    """Structural validation: labels, dtypes, missing values, duplicates."""
    report = {"rows": int(len(df)), "columns": int(df.shape[1])}
    bad_labels = sorted(set(df["risk_level"].unique()) - set(expected_levels))
    if bad_labels:
        raise ValueError(f"Unexpected target labels: {bad_labels}. Allowed: {expected_levels}")
    report["class_distribution"] = df["risk_level"].value_counts().to_dict()
    report["missing_values"] = {c: int(n) for c, n in df.isna().sum().items() if n > 0}
    for f in FEATURES:
        coerced = pd.to_numeric(df[f], errors="coerce")
        n_bad = int(coerced.isna().sum())
        if n_bad:
            raise ValueError(f"{n_bad} non-numeric values found in feature '{f}'")
    return report


def clean_dataset(df):
    """Drop exact duplicates and implausible rows. Returns (clean_df, stats)."""
    stats = {"rows_in": int(len(df))}

    dedup_keys = FEATURES + ["risk_level"]
    before = len(df)
    df = df.drop_duplicates(subset=dedup_keys, keep="first")
    stats["exact_duplicates_dropped"] = before - len(df)

    dropped_by_feature = {}
    mask = pd.Series(True, index=df.index)
    for feature, (low, high) in PLAUSIBILITY_RANGES.items():
        values = pd.to_numeric(df[feature], errors="coerce")
        bad = ~values.between(low, high)
        n = int(bad.sum())
        if n:
            dropped_by_feature[feature] = n
        mask &= ~bad
    stats["implausible_rows_dropped_by_feature"] = dropped_by_feature
    stats["implausible_rows_dropped_total"] = int((~mask).sum())
    df = df[mask]

    stats["rows_out"] = int(len(df))
    stats["class_distribution_out"] = df["risk_level"].value_counts().to_dict()
    return df, stats


def feature_matrix(df):
    """Return X (n_samples, n_features) in canonical FEATURES order."""
    return df[FEATURES].to_numpy(dtype=np.float64)
