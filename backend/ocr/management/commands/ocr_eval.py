"""OCR evaluation harness (Phase 3).

Generates a synthetic corpus (12 layouts x N patients, degraded copies,
fixed seed), runs each method over it, and reports field-level accuracy,
per-field / per-degradation accuracy, dangerous errors, latency and peak
memory to CSV + markdown.

Methods:
  tesseract_regex   — Tesseract + regex + validation (production regex path)
  tesseract_regex_<ablation> — preprocessing ablations (no_deskew, no_threshold,
                      no_denoise, no_resize)
  easyocr_regex     — EasyOCR + regex (only when easyocr is installed)
  tesseract_llm     — hybrid pipeline incl. the local-LLM stage (Ollama)
  vlm               — only when OCR_VISION_ENABLED=1

Real phone photos from ocr/eval_data/real_photos/ (with <name>.json ground
truth) are evaluated when present.

IMPORTANT: synthetic degradations only APPROXIMATE real photos.
"""
import csv
import json
import statistics
import time
import tracemalloc
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from ocr.eval import cardgen, degrade, metrics
from ocr.services import ocr_engine, parser, validate


class Command(BaseCommand):
    help = "Evaluate OCR extraction methods over a synthetic + real corpus."

    def add_arguments(self, parser):
        parser.add_argument("--patients", type=int, default=4, help="CSV rows per layout")
        parser.add_argument("--layouts", type=int, default=0, help="Limit to first N layouts (0 = all 12)")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--out", default="ocr/eval_results", help="Output directory")
        parser.add_argument("--skip-llm", action="store_true", help="Skip the LLM hybrid method")
        parser.add_argument("--split", default="dev", choices=["dev", "test", "all"],
                            help="dev = tuning split, test = held-out split (eval hygiene)")
        parser.add_argument("--no-qr", action="store_true", help="Disable the QR fast path (measure pure OCR)")
        parser.add_argument("--ablation", default="full",
                            choices=["baseline", "upscale", "clahe", "tessbest",
                                     "second_engine", "gate", "full"],
                            help="Which Step-3 fixes are active (ablation table)")
        parser.add_argument("--skip-ablations", action="store_true")

    def handle(self, *args, **options):
        self._detail_rows = []
        base = Path(settings.BASE_DIR)
        out_dir = base / options["out"]
        out_dir.mkdir(parents=True, exist_ok=True)
        dataset = base / settings.DATASET_PATH

        n_layouts = options["layouts"] or len(cardgen.LAYOUT_NAMES)
        cardgen.LAYOUT_NAMES = cardgen.LAYOUT_NAMES[:n_layouts]
        self.stdout.write(f"Generating corpus: {len(cardgen.LAYOUT_NAMES)} layouts x {options['patients']} patients...")
        split = options["split"]
        manifest = cardgen.build_corpus(
            dataset, out_dir / f"corpus_{split}",
            patients=options["patients"], seed=options["seed"], split=split,
        )
        self.stdout.write(f"Corpus ({split}): {len(manifest)} cards")

        ablation = options["ablation"]
        overrides = {}
        if options["no_qr"]:
            overrides["OCR_ENABLE_QR"] = False
        overrides.update({
            "baseline": {"OCR_ENABLE_UPSCALE": False, "OCR_ENABLE_CLAHE": False,
                         "OCR_TESSDATA_BEST": False, "OCR_SECOND_ENGINE": False,
                         "OCR_ENABLE_FUZZY": False, "OCR_ENABLE_SUGGESTIONS": False},
            "upscale": {"OCR_ENABLE_UPSCALE": True, "OCR_ENABLE_CLAHE": False,
                        "OCR_TESSDATA_BEST": False, "OCR_SECOND_ENGINE": False,
                        "OCR_ENABLE_FUZZY": False, "OCR_ENABLE_SUGGESTIONS": False},
            "clahe": {"OCR_ENABLE_UPSCALE": True, "OCR_ENABLE_CLAHE": True,
                      "OCR_TESSDATA_BEST": False, "OCR_SECOND_ENGINE": False,
                      "OCR_ENABLE_FUZZY": False, "OCR_ENABLE_SUGGESTIONS": False},
            "tessbest": {"OCR_ENABLE_UPSCALE": True, "OCR_ENABLE_CLAHE": True,
                         "OCR_TESSDATA_BEST": True, "OCR_SECOND_ENGINE": False,
                         "OCR_ENABLE_FUZZY": False, "OCR_ENABLE_SUGGESTIONS": False},
            "second_engine": {"OCR_ENABLE_UPSCALE": True, "OCR_ENABLE_CLAHE": True,
                              "OCR_TESSDATA_BEST": True, "OCR_SECOND_ENGINE": True,
                              "OCR_ENABLE_FUZZY": False, "OCR_ENABLE_SUGGESTIONS": False},
            "gate": {"OCR_ENABLE_UPSCALE": True, "OCR_ENABLE_CLAHE": True,
                     "OCR_TESSDATA_BEST": True, "OCR_SECOND_ENGINE": True,
                     "OCR_ENABLE_FUZZY": True, "OCR_ENABLE_SUGGESTIONS": False},
            "full": {},
        }[ablation])
        self.stdout.write(f"Ablation preset '{ablation}': overrides={overrides}")

        # --- methods -------------------------------------------------------
        methods = [
            ("tesseract_regex", self._run_tesseract_regex, {}),
        ]
        if not options["skip_ablations"]:
            for ablated_step in ("no_deskew", "no_threshold", "no_denoise", "no_resize"):
                flags = {ablated_step.replace("no_", ""): False}
                methods.append((f"tesseract_regex_{ablated_step}", self._run_tesseract_regex, {"preprocess_flags": flags}))
        if options["skip_llm"] or not settings.LLM_BASE_URL:
            self.stdout.write("LLM hybrid method skipped (--skip-llm or LLM_BASE_URL unset).")
        else:
            methods.append(("tesseract_llm_hybrid", self._run_pipeline, {}))
        try:
            import easyocr  # noqa: F401

            # Head-to-head standalone EasyOCR runs only where relevant (it
            # costs ~15s/card on CPU; the cross-engine vote is separately
            # enabled by the second_engine/full presets).
            if ablation in ("second_engine", "full"):
                methods.append(("easyocr_regex", self._run_easyocr_regex, {}))
        except ImportError:
            self.stdout.write("EasyOCR not installed — easyocr_regex skipped (pip install easyocr).")
        if getattr(settings, "OCR_VISION_ENABLED", False):
            methods.append(("vlm", self._run_vlm, {}))
        else:
            self.stdout.write("VLM method skipped (OCR_VISION_ENABLED is not 1).")

        # --- run -------------------------------------------------------------
        from django.test import override_settings

        rows = []
        for method_name, runner, kwargs in methods:
            with override_settings(**overrides):
                stats = self._run_method(method_name, runner, kwargs, manifest)
            rows.extend(stats)
            self.stdout.write(self.style.SUCCESS(
                f"{method_name}: field acc {stats[0]['field_accuracy']:.1%} | "
                f"dangerous/card {stats[0]['dangerous_per_card']:.2f} | "
                f"latency {stats[0]['avg_latency_ms']:.0f} ms"
            ))

        # real photos (optional): real_photos/dev and real_photos/test
        for real_split in ("dev", "test"):
            if real_split != split:
                continue
            real_dir = base / "ocr" / "eval_data" / "real_photos" / real_split
            real_count = self._run_real_photos(real_dir, rows)
            if real_count:
                self.stdout.write(f"Real photos evaluated ({real_split}): {real_count}")
            else:
                self.stdout.write(
                    f"No ground-truthed real photos in ocr/eval_data/real_photos/{real_split}/ "
                    "(add JPGs + matching <name>.json truth files)."
                )

        self._write_outputs(rows, out_dir)
        self.stdout.write(self.style.SUCCESS(f"Results written to {out_dir}"))

    # ------------------------------------------------------------------ #
    def _run_method(self, method_name, runner, kwargs, manifest):
        per_field_hits = {}
        per_field_total = {}
        per_degradation = {}
        correct_total = fields_total = dangerous_total = 0
        latencies = []
        peak_mem = 0
        detail_rows = []

        for card in manifest:
            content = Path(card["png_path"]).read_bytes()
            started = time.perf_counter()
            tracemalloc.start()
            try:
                fields, engine_info = runner(content, **kwargs)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"{method_name} failed on {card['card_id']}: {exc}"))
                fields = {}
                engine_info = {}
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_mem = max(peak_mem, peak)
            latency_ms = (time.perf_counter() - started) * 1000
            latencies.append(latency_ms)

            per_card, correct, dangerous = metrics.compare_card(card["truth"], fields)
            correct_total += correct
            dangerous_total += dangerous
            fields_total += len(card["truth"])
            deg = card["degradation"]
            per_degradation.setdefault(deg, [0, 0])
            per_degradation[deg][0] += correct
            per_degradation[deg][1] += len(card["truth"])
            for field, res in per_card.items():
                per_field_total[field] = per_field_total.get(field, 0) + 1
                per_field_hits[field] = per_field_hits.get(field, 0) + int(res["correct"])
                detail_rows.append({
                    "method": method_name, "card_id": card["card_id"], "layout": card["layout"],
                    "degradation": deg, "field": field, "truth": res["truth"],
                    "extracted": res["extracted"], "correct": res["correct"],
                    "dangerous": res["dangerous"], "flagged": res["flagged"],
                    "latency_ms": round(latency_ms, 1),
                })

        summary = {
            "method": method_name,
            "field_accuracy": correct_total / max(fields_total, 1),
            "dangerous_per_card": dangerous_total / max(len(manifest), 1),
            "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
            "peak_memory_mb": peak_mem / (1024 * 1024),
            "per_field": {f: per_field_hits[f] / per_field_total[f] for f in per_field_total},
            "per_degradation": {d: f"{h}/{t}" for d, (h, t) in per_degradation.items()},
            "cards": len(manifest),
        }
        self._detail_rows.extend(detail_rows)
        return [summary]

    # --- method runners (regex path = parser + validator, no LLM) -------- #
    def _run_tesseract_regex(self, content, preprocess_flags=None):
        lines, engine_info = ocr_engine.ocr_image(content, preprocess_flags=preprocess_flags)
        fields, _warnings = parser.parse_lines(lines)
        fields, _summary = validate.validate_fields(fields)
        return fields, engine_info

    def _run_easyocr_regex(self, content):
        from ocr.services import engine_easyocr

        lines, engine_info = engine_easyocr.ocr_image_easyocr(content)
        fields, _warnings = parser.parse_lines(lines)
        fields, _summary = validate.validate_fields(fields)
        return fields, engine_info

    def _run_pipeline(self, content):
        from ocr.services.pipeline import extract

        payload = extract("png", content)
        return payload["fields"], payload["engine_info"]

    def _run_vlm(self, content):
        from ocr.services import vision_extract

        wanted = ["age", "body_temperature", "heart_rate", "systolic_bp", "diastolic_bp",
                  "bmi", "hba1c", "fasting_glucose", "gestational_week", "visit_date"]
        extracted, _model = vision_extract.vision_extract_fields(content, wanted)
        fields = {
            name: {"value": e["value"], "confidence": vision_extract.VLM_CONFIDENCE,
                   "raw_text": e["raw_text"], "source": "vlm"}
            for name, e in extracted.items()
        }
        fields, _summary = validate.validate_fields(fields)
        return fields, {"engine": "vlm"}

    def _run_real_photos(self, real_dir, rows):
        real_dir = Path(real_dir)
        if not real_dir.exists():
            return 0
        count = 0
        for image in sorted(real_dir.glob("*.jpg")) + sorted(real_dir.glob("*.png")):
            truth_file = image.with_suffix(".json")
            if not truth_file.exists():
                self.stdout.write(self.style.WARNING(f"Real photo {image.name} has no .json ground truth — skipped."))
                continue
            truth = json.loads(truth_file.read_text(encoding="utf-8")).get("fields", {})
            content = image.read_bytes()
            started = time.perf_counter()
            fields, _info = self._run_tesseract_regex(content)
            latency = (time.perf_counter() - started) * 1000
            per_card, correct, dangerous = metrics.compare_card(truth, fields)
            rows.append([{
                "method": "real_photo_tesseract_regex",
                "field_accuracy": correct / max(len(truth), 1),
                "dangerous_per_card": dangerous,
                "avg_latency_ms": latency,
                "peak_memory_mb": 0,
                "per_field": {f: int(r["correct"]) for f, r in per_card.items()},
                "per_degradation": {"real_photo": f"{correct}/{len(truth)}"},
                "cards": 1,
            }])
            count += 1
        return count

    # ------------------------------------------------------------------ #
    def _write_outputs(self, summaries, out_dir):
        out_dir = Path(out_dir)
        # CSV: summary per method
        csv_path = out_dir / "ocr_eval_summary.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                "method", "cards", "field_accuracy", "dangerous_per_card", "avg_latency_ms",
                "peak_memory_mb", "per_field", "per_degradation",
            ])
            writer.writeheader()
            for s in summaries:
                writer.writerow({k: json.dumps(v) if isinstance(v, (dict,)) else v for k, v in s.items()})

        # Markdown
        lines = [
            "# OCR evaluation results",
            "",
            "Synthetic degradations only **approximate** real phone photos; "
            "corpus is fictional with exact ground truth.",
            "",
            "| method | cards | field accuracy | dangerous errors/card | avg latency (ms) | peak mem (MB) |",
            "|---|---|---|---|---|---|",
        ]
        for s in summaries:
            lines.append(
                f"| {s['method']} | {s['cards']} | {s['field_accuracy']:.1%} | "
                f"{s['dangerous_per_card']:.2f} | {s['avg_latency_ms']:.0f} | {s['peak_memory_mb']:.0f} |"
            )
        lines.append("")
        lines.append("## Per-field accuracy")
        all_fields = sorted({f for s in summaries for f in s["per_field"]})
        lines.append("| method | " + " | ".join(all_fields) + " |")
        lines.append("|---" * (len(all_fields) + 1) + "|")
        for s in summaries:
            cells = [f"{s['per_field'].get(f, float('nan')):.0%}" if f in s["per_field"] else "—" for f in all_fields]
            lines.append(f"| {s['method']} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("## Accuracy per degradation")
        all_degs = sorted({d for s in summaries for d in s["per_degradation"]})
        lines.append("| method | " + " | ".join(all_degs) + " |")
        lines.append("|---" * (len(all_degs) + 1) + "|")
        for s in summaries:
            cells = [s["per_degradation"].get(d, "—") for d in all_degs]
            lines.append(f"| {s['method']} | " + " | ".join(cells) + " |")

        (out_dir / "ocr_eval_summary.md").write_text("\n".join(lines), encoding="utf-8")
