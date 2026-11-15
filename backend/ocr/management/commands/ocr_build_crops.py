"""Build the OCR training-crop dataset from the report/reports corpus.

Usage:
    python manage.py ocr_build_crops
    python manage.py ocr_build_crops --png-dir ../report/reports/png \
        --pdf-dir ../report/reports/pdf --out ocr/training_data --max-per-page 48
"""
from django.core.management.base import BaseCommand

from ocr.training.crops import build_corpus


class Command(BaseCommand):
    help = "Render (crop, label) training pairs from the report corpus PDF text layers."

    def add_arguments(self, parser):
        parser.add_argument("--png-dir", default="../report/reports/png")
        parser.add_argument("--pdf-dir", default="../report/reports/pdf")
        parser.add_argument("--out", default="ocr/training_data")
        parser.add_argument("--max-per-page", type=int, default=48,
                            help="max word crops per page (digit tokens prioritized)")

    def handle(self, *args, **options):
        n_train, n_eval = build_corpus(
            options["png_dir"], options["pdf_dir"], options["out"],
            max_per_page=options["max_per_page"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"crop dataset written to {options['out']} — train {n_train}, eval(held-out) {n_eval}"))
