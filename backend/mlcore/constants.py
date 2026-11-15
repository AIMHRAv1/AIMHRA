"""
Dataset contract, feature selection and leakage documentation.

Dataset: Mathernal_Risk.csv (md5 6ad779f622f39cc28646d92a01270dab)
 - 6,103 rows, 11 columns, no missing values.
 - Target `Status`: three classes -> "low risk" (2001), "mid risk" (2043),
   "high risk" (2059). Genuinely three-class, so the production model is a
   3-class classifier.

LEAKAGE REVIEW (see ML_PIPELINE.md for the full write-up):
 The dataset contains no delivery/newborn/post-delivery outcome columns. All
 eight features are point-of-assessment measurements that would be known at
 prediction time. Therefore LEAKAGE_FEATURES is empty; identifiers are
 excluded as UNUSED_FEATURES below.
"""

# Canonical label set produced by the training dataset. Do not invent others.
RISK_LEVELS = ["low risk", "mid risk", "high risk"]
RISK_LEVEL_ORDER = {level: i for i, level in enumerate(RISK_LEVELS)}

# Canonical model feature set (order matters — artifacts store vectors in this order).
FEATURES = [
    "age",
    "body_temperature",
    "heart_rate",
    "systolic_bp",
    "diastolic_bp",
    "bmi",
    "hba1c",
    "fasting_glucose",
]

# Dataset header -> canonical feature name
COLUMN_MAP = {
    "Age": "age",
    "Body Temperature(F)": "body_temperature",
    "Heart rate(bpm)": "heart_rate",
    "Systolic Blood Pressure(mm Hg)": "systolic_bp",
    "Diastolic Blood Pressure(mm Hg)": "diastolic_bp",
    "BMI(kg/m 2)": "bmi",
    "Blood Glucose(HbA1c)": "hba1c",
    "Blood Glucose(Fasting hour-mg/dl)": "fasting_glucose",
    "Status": "risk_level",
}

# Documented feature-selection result.
SAFE_FEATURES = list(FEATURES)
LEAKAGE_FEATURES = []  # none detected; documented above and in ML_PIPELINE.md
UNUSED_FEATURES = {
    "Patient ID": "Row identifier — not a clinical measurement; would not generalize.",
    "Name": "Free-text PII — not predictive; excluded for privacy and generalization.",
}

# Plausibility bounds. Used BOTH to filter impossible training rows
# (age=250, body temp=39.6F, diastolic=9 exist in the raw file) and to
# validate inference input. Ranges are deliberately permissive: they reject
# only values that cannot occur physically, they are not clinical cut-offs.
PLAUSIBILITY_RANGES = {
    "age": (14, 55),
    "body_temperature": (95.0, 106.0),   # Fahrenheit
    "heart_rate": (40, 200),
    "systolic_bp": (70, 250),
    "diastolic_bp": (40, 150),
    "bmi": (12.0, 60.0),
    "hba1c": (20.0, 60.0),               # observed 30-50 mmol/mol
    "fasting_glucose": (2.0, 20.0),      # observed 3.5-8.9 mmol/L
}

# Human-readable labels for the assessment form / explanations.
FEATURE_LABELS = {
    "age": "Age",
    "body_temperature": "Body temperature (F)",
    "heart_rate": "Heart rate (bpm)",
    "systolic_bp": "Systolic blood pressure (mm Hg)",
    "diastolic_bp": "Diastolic blood pressure (mm Hg)",
    "bmi": "BMI (kg/m2)",
    "hba1c": "HbA1c (mmol/mol)",
    "fasting_glucose": "Fasting blood glucose (mmol/L)",
}

# The CSV glucose headers are ambiguous/inconsistent with the research paper.
# Per the dataset's feature definitions, values are treated as mmol/mol for
# HbA1c and mmol/L for fasting glucose. Values are used unchanged; no
# conversion is performed.
DATASET_NOTES = [
    "Glucose feature units are standardized as HbA1c mmol/mol and fasting blood glucose mmol/L; raw numeric values are used unchanged without conversion.",
    "Implausible training rows (outside PLAUSIBILITY_RANGES) are dropped and counted in the inspection report.",
    "Only exact full-row duplicates (including identifiers) are removed; records with identical clinical features and labels but different identifiers are retained.",
]
