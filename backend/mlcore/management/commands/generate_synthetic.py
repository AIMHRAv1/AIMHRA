"""Generate the OPTIONAL synthetic temporal research dataset.

Usage: python manage.py generate_synthetic --patients 300 --output data/synthetic_temporal.csv

Output is clearly flagged (is_synthetic column) and is NEVER used by the
production model. The printed quality report gates any experimental use.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mlcore.synthetic import generate_synthetic_temporal


class Command(BaseCommand):
    help = "Generate flagged synthetic longitudinal data for research experiments."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default=settings.DATASET_PATH)
        parser.add_argument("--patients", type=int, default=300)
        parser.add_argument("--output", default="data/synthetic_temporal.csv")
        parser.add_argument("--report", default="data/synthetic_quality_report.json")

    def handle(self, *args, **options):
        dataset = Path(options["dataset"])
        if not dataset.is_absolute():
            dataset = settings.BASE_DIR / dataset
        if not dataset.exists():
            raise CommandError(f"Dataset not found at {dataset}")

        syn, quality = generate_synthetic_temporal(dataset, n_patients=options["patients"])

        out = Path(options["output"])
        if not out.is_absolute():
            out = settings.BASE_DIR / out
        out.parent.mkdir(parents=True, exist_ok=True)
        syn.to_csv(out, index=False)

        report_path = Path(options["report"])
        if not report_path.is_absolute():
            report_path = settings.BASE_DIR / report_path
        report_path.write_text(json.dumps(quality, indent=2))

        self.stdout.write(self.style.SUCCESS(f"Generated {len(syn)} synthetic visit rows -> {out}"))
        self.stdout.write(f"Quality gates passed: {quality['gates_passed']}")
        if quality["gate_reasons"]:
            for reason in quality["gate_reasons"]:
                self.stdout.write(self.style.WARNING(f"  gate: {reason}"))
        self.stdout.write(f"Quality report -> {report_path}")
        if not quality["gates_passed"]:
            self.stdout.write(self.style.ERROR(
                "Quality gates FAILED: this synthetic dataset must NOT be used in experiments."
            ))
