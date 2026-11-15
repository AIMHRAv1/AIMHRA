# ML Data Card — Mathernal_Risk.csv

Scope: `mlcore` training data (`DATASET_PATH`, md5 `6ad779f622f39cc28646d92a01270dab`,
6,103 rows × 11 columns). This card documents data-quality facts and their
consequences for the risk-classification model. It is a factual record of the
dataset as supplied — **none of the metrics below constitute clinical
validation.**

## 1. Label provenance (limitation)

- The target `Status` ("low risk" / "mid risk" / "high risk", 2001/2043/2059
  rows) is **supplied by the source dataset**. The derivation rule — who
  labelled it, from what clinical criteria, at what point of care — is
  **unknown and undocumented in the source**.
- Consequence: the model learns to reproduce an unknown labelling procedure.
  Its outputs are a statistical estimate of that procedure, not an
  independently verified clinical risk score.
- Verified on this copy: no identical feature vector carries conflicting
  labels (0 conflicts on all 8 exact features).

## 2. Units inconsistency (glucose columns)

- `Blood Glucose(HbA1c)` holds values 30–50 — the header suggests mg/dL or %,
  neither matches; consistent interpretation is mmol/mol (HbA1c units).
- `Blood Glucose(Fasting hour-mg/dl)` holds 3.5–8.9 — consistent with
  **mmol/L**, not the mg/dL in the header.
- Decision: values are used **as provided** (same scale for training and
  inference; the assessment form documents the observed ranges). No
  conversion is invented.
- Enforcement: `validate_dataset()` now fails training when a glucose column's
  magnitudes leave the documented ranges (`DOCUMENTED_GLUCOSE_RANGES` in
  `mlcore/constants.py`) for more than 0.5% of rows — a future "unit-corrected"
  CSV cannot silently invalidate the deployed model.

## 3. Duplicates and near-duplicates

- 1 exact duplicate feature+label row: dropped by `clean_dataset` (counted).
- **Near-duplicate clusters** (all 8 features equal when rounded to whole
  numbers): 91 groups covering 195 rows; **11 groups contain conflicting
  labels**. These are plausibly the same clinical presentation recorded more
  than once.
- Mitigation: `near_duplicate_groups()` + `grouped_split_indices()` keep every
  cluster inside ONE split (train/val or test), so near-identical rows cannot
  straddle the test boundary and inflate metrics. Stratification is
  approximate (majority label per group decides placement). Verified: 0
  groups shared across splits after splitting.
- Residual risk: rows differing by tiny measurement noise but >0.5 rounding
  are not grouped; their volume is small relative to 6,103 rows.

## 4. Plausibility filtering

`PLAUSIBILITY_RANGES` are **physical** bounds, not clinical thresholds (e.g.
body temperature 95–106 °F, age 14–55). Rows outside them (e.g. diastolic 9)
cannot occur physiologically and are dropped and counted in
`cleaning_stats`. No clinical cut-offs are applied anywhere in the ML layer.

## 5. What these metrics do NOT mean

All accuracy/recall/AUC/calibration numbers produced by `mlcore.evaluation`
describe performance **on this dataset's internal splits only**. They do not
establish clinical validity, generalization to other populations, or fitness
for any real-world deployment. The `Status` labels themselves are of
unverified provenance (§1). External, clinically reviewed evaluation is
required before any clinical use.
