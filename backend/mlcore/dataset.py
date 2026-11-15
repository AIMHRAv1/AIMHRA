"""Dataset loading, validation and reproducible cleaning.

Every cleaning decision here is counted and reported — nothing is removed
silently (see management command `inspect_dataset`).
"""
import hashlib
import logging

import numpy as np
import pandas as pd

from mlcore.constants import COLUMN_MAP, DOCUMENTED_GLUCOSE_RANGES, FEATURES, PLAUSIBILITY_RANGES

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
    """Structural validation: labels, dtypes, missing values, glucose units."""
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
    report["unit_check"] = _unit_check(df)
    return report


def _unit_check(df, max_fraction_outside=0.005):
    """Verify the glucose columns keep the magnitudes the production model
    was trained on (see DATASET_NOTES: headers say mg/dL but values are
    mmol/L-scale). A future 'corrected' CSV in true mg/dL magnitudes would
    silently invalidate the model — so a bulk mismatch is a hard error, while
    a handful of stray values (dropped later by cleaning) is tolerated."""
    check = {}
    for feature, (low, high) in DOCUMENTED_GLUCOSE_RANGES.items():
        values = pd.to_numeric(df[feature], errors="coerce")
        observed_low, observed_high = float(values.min()), float(values.max())
        fraction_outside = float((~values.between(low, high)).mean())
        check[feature] = {
            "documented_range": [low, high],
            "observed_range": [round(observed_low, 2), round(observed_high, 2)],
            "fraction_outside_documented_range": round(fraction_outside, 5),
            "consistent": fraction_outside <= max_fraction_outside,
        }
        if not check[feature]["consistent"]:
            raise ValueError(
                f"Feature '{feature}' magnitudes (observed {observed_low}-{observed_high}) are "
                f"outside the documented range {low}-{high} for more than "
                f"{max_fraction_outside:.1%} of rows. The dataset unit contract changed — "
                "the model must be retrained and re-validated before use. "
                "See ML_DATA_CARD.md (Units)."
            )
    return check


def near_duplicate_groups(df):
    """Group ids for rows that share ALL eight features when rounded to whole
    numbers (a conservative proxy for the same clinical presentation recorded
    twice). Rows in the same group are kept in the same split so near
    duplicates cannot inflate test metrics. Exact feature+label duplicates
    are already dropped by clean_dataset; this catches the remaining
    near-identical clusters (verified on this dataset: 91 groups / 195 rows,
    11 of them with conflicting labels)."""
    rounded = df[FEATURES].round(0)
    codes, _ = pd.factorize(rounded.apply(tuple, axis=1))
    return np.asarray(codes, dtype=np.int64)


def grouped_split_indices(y, groups, test_size, seed=42):
    """Group-aware, approximately stratified split.

    Returns (train_idx, test_idx). Every near-duplicate group lands entirely
    in one side; per-class test row targets are filled proportionally so the
    split stays close to stratified even for the few groups whose rows carry
    conflicting labels (majority label decides placement). Deterministic for
    a fixed seed. Rows within a group always keep their original order."""
    y = np.asarray(y)
    groups = np.asarray(groups)
    rng = np.random.RandomState(seed)

    unique_groups = np.unique(groups)
    # Majority label per group (conflicting groups are assigned to their
    # dominant class for stratification purposes).
    group_majority = {}
    group_indices = {}
    for g in unique_groups:
        idx = np.where(groups == g)[0]
        group_indices[g] = idx
        labels, counts = np.unique(y[idx], return_counts=True)
        group_majority[g] = labels[np.argmax(counts)]

    test_indices = []
    for label in np.unique(y):
        label_groups = [g for g in unique_groups if group_majority[g] == label]
        rng.shuffle(label_groups)
        label_total = sum(len(group_indices[g]) for g in label_groups)
        target = int(round(test_size * label_total))
        taken = 0
        for g in label_groups:
            if taken >= target:
                break
            test_indices.extend(group_indices[g].tolist())
            taken += len(group_indices[g])

    test_mask = np.zeros(len(y), dtype=bool)
    if test_indices:
        test_mask[np.asarray(test_indices, dtype=int)] = True
    train_idx = np.where(~test_mask)[0]
    test_idx = np.where(test_mask)[0]
    return train_idx, test_idx


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
