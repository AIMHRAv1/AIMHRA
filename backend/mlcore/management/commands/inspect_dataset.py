"""Dataset inspection command (requirement #50).

Reports rows, columns, dtypes, missing values, duplicates, class distribution,
constant/near-empty features, leakage review, temporal fields and the effect
of plausibility cleaning. Writes a JSON report next to the dataset.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mlcore.constants import (
    DATASET_NOTES, FEATURES, LEAKAGE_FEATURES, PLAUSIBILITY_RANGES,
    RISK_LEVELS, SAFE_FEATURES, UNUSED_FEATURES,
)
from mlcore.dataset import clean_dataset, dataset_md5, load_raw_dataset, validate_dataset


class Command(BaseCommand):
    help = "Inspect the maternal risk dataset and write a JSON analysis report."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=settings.DATASET_PATH)
        parser.add_argument("--output", default="data/dataset_report.json")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_absolute():
            path = settings.BASE_DIR / path
        if not path.exists():
            raise CommandError(f"Dataset not found at {path}")

        df = load_raw_dataset(path)
        report = {
            "dataset": str(path),
            "md5": dataset_md5(path),
            "rows": int(len(df)),
            "columns": int(df.shape[1]),
            "feature_names": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
            "missing_values": {c: int(n) for c, n in df.isna().sum().items() if n > 0},
            "class_distribution": df["risk_level"].value_counts().to_dict(),
            "target_labels": RISK_LEVELS,
            "constant_features": [c for c in df.columns if df[c].nunique(dropna=False) <= 1],
            "near_empty_features": [c for c in df.columns if df[c].notna().mean() < 0.5],
            "temporal_visit_fields": [],
            "feature_selection": {
                "SAFE_FEATURES": SAFE_FEATURES,
                "LEAKAGE_FEATURES": LEAKAGE_FEATURES,
                "UNUSED_FEATURES": UNUSED_FEATURES,
                "leakage_review": (
                    "No post-outcome columns exist in this dataset; all SAFE_FEATURES are "
                    "point-of-assessment measurements. Identifiers excluded as UNUSED."
                ),
            },
            "plausibility_ranges": {k: list(v) for k, v in PLAUSIBILITY_RANGES.items()},
            "notes": DATASET_NOTES,
        }

        report["validation"] = validate_dataset(df, RISK_LEVELS)
        _, cleaning = clean_dataset(df)
        report["cleaning"] = cleaning

        # Numeric summaries for the safe features.
        report["numeric_summary"] = {
            f: {
                "min": float(df[f].min()),
                "max": float(df[f].max()),
                "mean": round(float(df[f].mean()), 3),
                "unique": int(df[f].nunique()),
            }
            for f in FEATURES
        }

        out = Path(options["output"])
        if not out.is_absolute():
            out = settings.BASE_DIR / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))

        self.stdout.write(self.style.SUCCESS(f"Inspected {path.name}: {report['rows']} rows, {report['columns']} columns"))
        self.stdout.write(f"Class distribution: {report['class_distribution']}")
        self.stdout.write(f"Cleaning: {cleaning}")
        self.stdout.write(f"Report written to {out}")
