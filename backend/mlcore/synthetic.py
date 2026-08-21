"""OPTIONAL RESEARCH MODULE: synthetic longitudinal (temporal) data.

The production dataset has no visit-level fields, so longitudinal sequences
are simulated for research experiments only. Rules:
 - Synthetic records are ALWAYS flagged (is_synthetic=true column).
 - They are never mixed into production training.
 - Quality gates (distribution/correlation/class-distribution checks) must
   pass before any experiment uses them.

Method: per-class feature means/covariances are estimated from the real data;
each synthetic patient draws a starting vector from the class distribution
(Cholesky sampling) and evolves across 4 visits with small random drift and
bounded noise. This is a documented statistical approximation — it is NOT a
generative deep model like TimeGAN, and reports must describe it as such.
"""
import numpy as np
import pandas as pd

from mlcore.constants import FEATURES
from mlcore.dataset import clean_dataset, feature_matrix, load_raw_dataset

VISITS = 4
DRIFT_SCALE = 0.02
NOISE_SCALE = 0.03


def generate_synthetic_temporal(dataset_path, n_patients=200, random_state=42):
    """Return a DataFrame with one row per (patient, visit) plus quality report."""
    rng = np.random.default_rng(random_state)
    raw = load_raw_dataset(dataset_path)
    df, _ = clean_dataset(raw)

    rows = []
    for label in ("low risk", "mid risk", "high risk"):
        sub = df[df["risk_level"] == label]
        X = feature_matrix(sub)
        mean = X.mean(axis=0)
        cov = np.cov(X, rowvar=False)
        cov += np.eye(cov.shape[0]) * 1e-6  # numerical stability
        chol = np.linalg.cholesky(cov)

        for i in range(n_patients // 3 + 1):
            start = mean + chol @ rng.standard_normal(len(FEATURES))
            # Small plausible drift toward slightly worse measurements with
            # probability, plus bounded visit-to-visit noise.
            drift = rng.normal(0, DRIFT_SCALE, len(FEATURES)) * (np.abs(mean) + 1)
            current = start
            for visit in range(1, VISITS + 1):
                noise = rng.normal(0, NOISE_SCALE, len(FEATURES)) * (np.abs(mean) + 1)
                current = current + drift + noise
                row = dict(zip(FEATURES, np.round(current, 3)))
                row.update({"risk_level": label, "visit": visit, "patient_index": f"SYN-{label[0].upper()}{i:04d}"})
                rows.append(row)

    syn = pd.DataFrame(rows)
    syn["is_synthetic"] = True
    quality = quality_report(df, syn)
    return syn, quality


def quality_report(real_df, syn_df):
    """Compare synthetic vs real per-feature distributions, correlations and
    class distribution. Gates: mean |mean diff| and |std diff| ratios."""
    report = {"features": {}, "gates_passed": True, "gate_reasons": []}
    for f in FEATURES:
        real = real_df[f].astype(float)
        syn = syn_df[f].astype(float)
        mean_ratio = abs(syn.mean() - real.mean()) / (abs(real.mean()) + 1e-9)
        std_ratio = abs(syn.std() - real.std()) / (real.std() + 1e-9)
        report["features"][f] = {
            "real_mean": round(float(real.mean()), 3),
            "syn_mean": round(float(syn.mean()), 3),
            "mean_diff_ratio": round(float(mean_ratio), 4),
            "std_diff_ratio": round(float(std_ratio), 4),
        }
        # Generous gates — the module is research-only; experiments must pass
        # these before synthetic data is used anywhere.
        if mean_ratio > 0.35 or std_ratio > 0.60:
            report["gates_passed"] = False
            report["gate_reasons"].append(f"{f}: distribution too far from real data")

    real_corr = real_df[FEATURES].astype(float).corr().to_numpy()
    syn_corr = syn_df[FEATURES].astype(float).corr().to_numpy()
    report["correlation_mae"] = round(float(np.mean(np.abs(real_corr - syn_corr))), 4)
    real_dist = real_df["risk_level"].value_counts(normalize=True).round(3).to_dict()
    syn_dist = syn_df["risk_level"].value_counts(normalize=True).round(3).to_dict()
    report["class_distribution_real"] = real_dist
    report["class_distribution_synthetic"] = syn_dist
    return report
