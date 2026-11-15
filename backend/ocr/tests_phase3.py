"""Phase 3 tests: corpus generation consistency, degradation behavior and
metric math (no OCR engine needed — fast)."""
import json
import shutil
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from ocr.eval import cardgen, degrade, metrics


class CardGenTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(settings.BASE_DIR) / "ocr" / "eval_results" / "_test_corpus"

    def test_corpus_manifest_and_truth_consistency(self):
        manifest = cardgen.build_corpus(
            settings.BASE_DIR / settings.DATASET_PATH, self.tmp, patients=2, seed=7, split="all"
        )
        self.assertEqual(len(manifest), len(cardgen.LAYOUT_NAMES) * 2)
        for card in manifest:
            truth = json.loads(Path(card["png_path"]).with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(truth["truth"], card["truth"])
            self.assertTrue(Path(card["png_path"]).exists())
            self.assertTrue(Path(card["pdf_path"]).exists())
            # Bilingual layout declares Devanagari-capable rendering when available
            if card["layout"] == "syn-bilingual":
                self.assertIn("syn-bilingual", card["card_id"])
        # Reproducible seed: same patients chosen again
        manifest2 = cardgen.build_corpus(
            settings.BASE_DIR / settings.DATASET_PATH, self.tmp, patients=2, seed=7, split="all"
        )
        self.assertEqual([c["truth"] for c in manifest], [c["truth"] for c in manifest2])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()


class DegradeTests(TestCase):
    def test_each_degradation_changes_the_image_deterministically(self):
        buf = Path(settings.BASE_DIR) / "ocr" / "eval_results" / "_degrade_src.png"
        buf.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (600, 400), "white")
        draw = ImageDraw.Draw(img)
        for i in range(10):
            draw.rectangle([30, 30 + i * 34, 560, 52 + i * 34], outline="black")
        img.save(buf)
        content = buf.read_bytes()
        for kind in degrade.DEGRADATIONS:
            out1 = degrade.degrade(content, kind, seed=3)
            out2 = degrade.degrade(content, kind, seed=3)
            self.assertNotEqual(out1, content, f"{kind} should alter the image")
            self.assertEqual(out1, out2, f"{kind} should be deterministic")
        buf.unlink()

    def test_unknown_degradation_rejected(self):
        import io as _io

        from PIL import Image

        b = _io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(b, format="PNG")
        with self.assertRaises(ValueError):
            degrade.degrade(b.getvalue(), "nope")


class MetricsTests(TestCase):
    def test_exact_for_ints_and_tolerance_for_floats(self):
        self.assertTrue(metrics.value_correct("age", 28, 28))
        self.assertFalse(metrics.value_correct("age", 28, 29))       # int: exact
        self.assertTrue(metrics.value_correct("body_temperature", 97.5, 97.6))  # within 0.15
        self.assertFalse(metrics.value_correct("body_temperature", 97.5, 97.7))
        self.assertTrue(metrics.value_correct("fasting_glucose", 5.8, 5.75))
        self.assertFalse(metrics.value_correct("hba1c", 41, 42))     # int-like: exact

    def test_dangerous_error_classification(self):
        per_card, correct, dangerous = metrics.compare_card(
            {"systolic_bp": 161, "bmi": 24.9},
            {"systolic_bp": {"value": 130, "valid": True},    # wrong but plausible -> dangerous
             "bmi": {"value": 8, "valid": False}},            # wrong and implausible -> not dangerous
        )
        self.assertFalse(per_card["systolic_bp"]["correct"])
        self.assertTrue(per_card["systolic_bp"]["dangerous"])
        self.assertFalse(per_card["bmi"]["dangerous"])
        self.assertEqual(correct, 0)
        self.assertEqual(dangerous, 1)

    def test_missing_field_counts_wrong_not_dangerous(self):
        per_card, correct, dangerous = metrics.compare_card({"age": 28}, {})
        self.assertFalse(per_card["age"]["correct"])
        self.assertFalse(per_card["age"]["dangerous"])
        self.assertEqual(correct, 0)
        self.assertEqual(dangerous, 0)
