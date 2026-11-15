"""Fine-tune the EasyOCR recognition model on the report corpus (GPU).

Usage:
    python manage.py ocr_train                      # defaults: 6 epochs, CUDA
    python manage.py ocr_train --epochs 10 --lr 5e-4

Requires the crop dataset (ocr_build_crops) and CUDA. The best checkpoint is
written to ocr/models/easyocr/user_network/<name>.pth (+ yaml + architecture
module) and installed where EasyOCR loads custom networks from.
"""
from django.core.management.base import BaseCommand

from ocr.training.train import export_config, install_model, train


class Command(BaseCommand):
    help = "Fine-tune the EasyOCR recognizer on report/reports crops (CUDA)."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default="ocr/training_data")
        parser.add_argument("--out", default="ocr/models/easyocr/user_network")
        parser.add_argument("--name", default="aimhra_report")
        parser.add_argument("--epochs", type=int, default=6)
        parser.add_argument("--batch-size", type=int, default=32)
        parser.add_argument("--lr", type=float, default=3e-5)
        parser.add_argument("--workers", type=int, default=0)
        parser.add_argument("--cpu", action="store_true", help="force CPU training")
        parser.add_argument("--scratch", action="store_true", help="train from scratch")
        parser.add_argument("--freeze-cnn", action="store_true", help="train only LSTM+classifier (less forgetting)")

    def handle(self, *args, **options):
        from types import SimpleNamespace

        best_acc = train(SimpleNamespace(**options))
        export_config(options["out"], options["name"])
        install_model(options["out"], options["name"])
        self.stdout.write(self.style.SUCCESS(
            f"model '{options['name']}' exported to {options['out']} "
            f"(best internal val word acc {best_acc:.4f})"))
