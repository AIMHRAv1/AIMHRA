"""OCR diagnosis harness (STEP 1 of the decimal/degradation investigation).

READ-ONLY with respect to production behavior: builds a small corpus, runs
the Tesseract+regex path, and produces an error breakdown:
  - per-field / per-degradation error table
  - decimal-error categorization (dot dropped / misplaced / extra digit /
    wrong digit / missing digits) with concrete examples
  - per-preprocessing-stage trace for the 5 worst cards (at which stage the
    decimal point disappears)
  - parser substitution audit (O->0, l->1, S->5, comma handling)
Outputs: markdown report + debug stage images under ocr/eval_results/diagnosis/.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from ocr.eval import cardgen, degrade, metrics
from ocr.services import ocr_engine, parser, validate

FLOAT_FIELDS = {"body_temperature", "bmi", "fasting_glucose"}


def _digit_runs(s):
    return "".join(re.findall(r"\d", str(s)))


def classify_decimal_error(truth, extracted):
    """Categorize a wrong float extraction."""
    t_digits, e_digits = _digit_runs(truth), _digit_runs(extracted)
    if e_digits == t_digits:
        return "dot-moved-or-formatted"  # digits identical: formatting issue
    if e_digits == t_digits.replace(".", "") and "." not in str(extracted):
        return "dot-dropped"
    if sorted(e_digits) == sorted(t_digits) and len(e_digits) == len(t_digits):
        return "dot-misplaced"
    if len(e_digits) > len(t_digits):
        return "extra-digit"
    if len(e_digits) < len(t_digits):
        return "digit(s)-missing"
    return "wrong-digit"


class Command(BaseCommand):
    help = "Diagnose OCR decimal-loss and degradation failures (no fixes)."

    def add_arguments(self, parser):
        parser.add_argument("--layouts", type=int, default=6)
        parser.add_argument("--patients", type=int, default=2)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--out", default="ocr/eval_results/diagnosis")

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        out_dir = base / options["out"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cardgen.LAYOUT_NAMES = cardgen.LAYOUT_NAMES[: options["layouts"]]
        manifest = cardgen.build_corpus(
            base / settings.DATASET_PATH, out_dir / "corpus",
            patients=options["patients"], seed=options["seed"],
        )
        self.stdout.write(f"Corpus: {len(manifest)} cards")

        field_stats = defaultdict(lambda: [0, 0])
        deg_stats = defaultdict(lambda: [0, 0])
        decimal_errors = []       # (card_id, layout, degradation, field, truth, extracted, raw, category)
        substitution_cases = []   # (card_id, field, raw_token, parsed, correct?)
        failing_cards = []        # (card_id, wrong_count, content, truth, fields)

        t0 = __import__("time").perf_counter()
        for card in manifest:
            content = Path(card["png_path"]).read_bytes()
            try:
                lines, _info = ocr_engine.ocr_image(content)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"{card['card_id']}: OCR failed: {exc}"))
                continue
            raw_text = "\n".join(l["text"] for l in lines)
            fields, _warnings = parser.parse_lines(lines)
            fields, _summary = validate.validate_fields(fields)

            per_card, correct, dangerous = metrics.compare_card(card["truth"], fields)
            wrong_fields = [f for f, r in per_card.items() if not r["correct"]]
            failing_cards.append((card, wrong_fields, content, raw_text, fields, per_card))

            for field, res in per_card.items():
                field_stats[field][0] += int(res["correct"])
                field_stats[field][1] += 1
                deg_stats[card["degradation"]][0] += int(res["correct"])
                deg_stats[card["degradation"]][1] += 1

                if not res["correct"] and field in FLOAT_FIELDS and res["extracted"] is not None:
                    raw_lines = [l["text"] for l in lines if _label_hint(field) in l["text"].lower()]
                    decimal_errors.append({
                        "card_id": card["card_id"], "layout": card["layout"],
                        "degradation": card["degradation"], "field": field,
                        "truth": res["truth"], "extracted": res["extracted"],
                        "raw": " | ".join(raw_lines)[:160] or "(label line not found)",
                        "category": classify_decimal_error(res["truth"], res["extracted"]),
                        "flagged": res["flagged"], "dangerous": res["dangerous"],
                    })

            # parser substitution audit: tokens that used confusable letters
            for line in lines:
                for m in re.finditer(r"[0-9OoIlSs|.,]{2,}", line["text"]):
                    token = m.group(0)
                    if any(ch in token for ch in "OoIlSs") and any(ch.isdigit() for ch in token):
                        cleaned = parser.clean_number(token)
                        if cleaned is None:
                            substitution_cases.append((card["card_id"], token, "DROPPED"))
                        else:
                            substitution_cases.append((card["card_id"], token, cleaned))
        self.stdout.write(f"OCR pass done in {__import__('time').perf_counter() - t0:.0f}s")

        # ---- 5 worst failing cards: stage-by-stage decimal trace ----------
        failing_cards.sort(key=lambda x: -len(x[1]))
        stage_report = []
        stage_flags = [
            ("grayscale", {"denoise": False, "deskew": False, "threshold": False, "resize": False}),
            ("+denoise", {"denoise": True, "deskew": False, "threshold": False, "resize": False}),
            ("+deskew", {"denoise": True, "deskew": True, "threshold": False, "resize": False}),
            ("+threshold", {"denoise": True, "deskew": True, "threshold": True, "resize": False}),
            ("+resize (full)", {}),
        ]
        from ocr.services.preprocess import decode_image, preprocess_image
        import cv2

        for card, wrong_fields, content, raw_text, fields, per_card in failing_cards[:5]:
            card_dir = out_dir / "debug" / card["card_id"]
            card_dir.mkdir(parents=True, exist_ok=True)
            img = decode_image(content)
            decimal_trace = []
            for stage_name, flags in stage_flags:
                processed = preprocess_image(img, **flags)
                cv2.imwrite(str(card_dir / f"stage_{stage_name.replace('+', '').replace(' ', '_')}.png"), processed)
                ok, buf = cv2.imencode(".png", processed)
                lines, _info = ocr_engine.ocr_image(buf.tobytes())
                stage_text = "\n".join(l["text"] for l in lines)
                for field in [f for f in wrong_fields if f in FLOAT_FIELDS]:
                    truth = card["truth"][field]
                    dot_kept = f"{truth}" in stage_text or f"{truth:.1f}" in stage_text
                    digits_kept = _digit_runs(truth) in _digit_runs(stage_text).replace(".", "") or \
                        _digit_runs(truth) in _digit_runs(stage_text)
                    decimal_trace.append({
                        "field": field, "truth": truth, "stage": stage_name,
                        "decimal_visible": dot_kept, "digits_visible": bool(digits_kept),
                    })
            stage_report.append({
                "card_id": card["card_id"], "layout": card["layout"],
                "degradation": card["degradation"], "wrong_fields": wrong_fields,
                "trace": decimal_trace,
            })

        # ---- report -------------------------------------------------------
        report = ["# OCR diagnosis report", ""]

        report += ["## Field accuracy (tesseract+regex, raw)", "| field | correct | total | acc |", "|---|---|---|---|"]
        for f, (h, t) in sorted(field_stats.items()):
            report.append(f"| {f} | {h} | {t} | {h / t:.0%} |")

        report += ["", "## Per degradation", "| degradation | correct | total | acc |", "|---|---|---|---|"]
        for d, (h, t) in sorted(deg_stats.items()):
            report.append(f"| {d} | {h} | {t} | {h / t:.0%} |")

        report += ["", f"## Decimal errors ({len(decimal_errors)})",
                   "| card | layout | degradation | field | truth | parsed | category | flagged | dangerous | raw OCR |",
                   "|---|---|---|---|---|---|---|---|---|---|"]
        for e in decimal_errors:
            report.append(
                f"| {e['card_id']} | {e['layout']} | {e['degradation']} | {e['field']} | "
                f"{e['truth']} | {e['extracted']} | {e['category']} | {e['flagged']} | {e['dangerous']} | "
                f"`{e['raw']}` |"
            )
        cats = Counter(e["category"] for e in decimal_errors)
        report += ["", "**Decimal error categories:** " + ", ".join(f"{k}: {v}" for k, v in cats.most_common())]

        report += ["", "## Parser substitution audit",
                   f"{len(substitution_cases)} numeric tokens contained confusable letters.",
                   "Sample (token -> parsed):"]
        for card_id, token, parsed in substitution_cases[:15]:
            report.append(f"- `{token}` -> `{parsed}` ({card_id})")

        report += ["", "## Stage-by-stage decimal trace (5 worst cards)"]
        for s in stage_report:
            report.append(f"### {s['card_id']} ({s['layout']}, {s['degradation']}) — wrong: {', '.join(s['wrong_fields'])}")
            for t in s["trace"]:
                report.append(
                    f"- {t['field']} truth {t['truth']} @ {t['stage']}: "
                    f"decimal {'VISIBLE' if t['decimal_visible'] else 'LOST'}, "
                    f"digits {'present' if t['digits_visible'] else 'LOST'}"
                )
            report.append(f"  (debug stage images: ocr/eval_results/diagnosis/debug/{s['card_id']}/)")

        (out_dir / "diagnosis.md").write_text("\n".join(report), encoding="utf-8")
        (out_dir / "decimal_errors.json").write_text(json.dumps(decimal_errors, indent=1), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Diagnosis written to {out_dir / 'diagnosis.md'}"))
        for line in report:
            if line.startswith("**Decimal") or line.startswith("| dot") or "acc |" in line and report.index(line) > 2:
                pass
        self.stdout.write("\n".join(report[-6:]))


def _label_hint(field):
    hints = {
        "body_temperature": "temp", "bmi": "bmi", "fasting_glucose": "fbs",
        "systolic_bp": "blood pressure", "heart_rate": "pulse", "age": "age", "hba1c": "hba",
    }
    return hints.get(field, field)
