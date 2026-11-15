"""Synthetic report-card generator for OCR evaluation.

Renders fictional report cards (12 layout variants) from Mathernal_Risk.csv
ground truth with reportlab, plus JSON ground truth per card. Devanagari
labels use the Nirmala UI font when present; reportlab does not perform
complex text shaping, so Nepali conjuncts render approximately — the cards
are bilingual (English label always present) and only approximate real
Nepali reports.

Honesty note: all institutions/patients are fictional; the value of this
corpus is layout diversity with EXACT ground truth, not realism.
"""
import csv
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings

from mlcore.constants import FEATURES

NP_FONT_CANDIDATES = ["C:/Windows/Fonts/Nirmala.ttc", "C:/Windows/Fonts/mangal.ttf"]

# Human label wording per layout family. {np: ...} renders a Devanagari
# second line when a Devanagari-capable font is available.
LABEL_SETS = {
    "standard": {
        "age": "Age", "body_temperature": "Body Temperature", "heart_rate": "Heart Rate",
        "systolic_bp": "Blood Pressure (Sys)", "diastolic_bp": "Blood Pressure (Dia)",
        "bmi": "BMI", "hba1c": "HbA1c", "fasting_glucose": "Fasting Blood Glucose",
        "gestational_week": "Gestational Age", "visit_date": "Visit Date",
    },
    "clinical": {
        "age": "Age (years)", "body_temperature": "Temp", "heart_rate": "Pulse",
        "systolic_bp": "Systolic BP", "diastolic_bp": "Diastolic BP",
        "bmi": "Body Mass Index", "hba1c": "HbA1c (Glycosylated)", "fasting_glucose": "FBS",
        "gestational_week": "GA", "visit_date": "Date",
    },
    "bilingual": {
        "age": "Age / उमेर", "body_temperature": "Temperature / तापक्रम",
        "heart_rate": "Pulse / नाडी", "systolic_bp": "BP Systolic / सिस्टोलिक",
        "diastolic_bp": "BP Diastolic / डायस्टोलिक", "bmi": "BMI",
        "hba1c": "HbA1c", "fasting_glucose": "Fasting Sugar / खाली पेट",
        "gestational_week": "Gestational Week / गर्भावस्था", "visit_date": "Date / मिति",
    },
    "compact": {
        "age": "AGE", "body_temperature": "TEMP", "heart_rate": "HR",
        "systolic_bp": "SBP", "diastolic_bp": "DBP", "bmi": "BMI",
        "hba1c": "HBAIC", "fasting_glucose": "FBS", "gestational_week": "GA", "visit_date": "DATE",
    },
}

LAYOUT_NAMES = [
    "list-colon",        # 1 list style, "Label : value"
    "list-plain",        # 2 list style, "Label value"
    "table-2col",        # 3 two-column table
    "table-3col-unit",   # 4 Test | Result | Unit table
    "syn-clinical",      # 5 clinical wording (Pulse/Temp/SBP)
    "syn-bilingual",     # 6 bilingual English/Nepali
    "syn-compact",       # 7 compact wording (HBAIC etc.), no space after colon
    "unit-celsius",      # 8 temperature printed in Celsius
    "unit-explicit",     # 9 units printed and matching the value scale
    "decimal-comma",     # 10 decimal comma values
    "two-column",        # 11 shuffled two-column arrangement
    "list-dashes",       # 12 list style with dash separators
    "qr",                # 13 QR code encoding the fields + minimal print
]


def _devanagari_font():
    for candidate in NP_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _register_fonts(pdf_canvas):
    registered = {"np": None}
    np_font = _devanagari_font()
    if np_font:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        try:
            pdfmetrics.registerFont(TTFont("NirmalaEval", np_font, subfontIndex=0))
            registered["np"] = "NirmalaEval"
        except Exception:
            pass
    return registered


def _format_value(field, value, layout):
    """Render the printed string for a value under a layout's unit/format
    conventions. Returns (printed_string, unit_string, truth_value)."""
    if value is None:
        return "-", "", None
    if layout == "unit-celsius" and field == "body_temperature":
        c = (value - 32) * 5 / 9
        return f"{c:.1f}", "°C", round(c, 1)
    if field == "fasting_glucose" and layout == "unit-explicit":
        return f"{value}", "mmol/L", value
    if field == "hba1c" and layout == "unit-explicit":
        return f"{value}", "mmol/mol", value
    if layout == "decimal-comma" and isinstance(value, float):
        return f"{value:.1f}".replace(".", ","), "", value
    if field == "body_temperature":
        return f"{value:.1f}", "°F", value
    return str(value), "", value


def build_corpus(dataset_path, out_dir, patients=3, seed=42, degrade_cycle=("clean", "rot", "blur", "lowres", "lighting", "jpeg", "noise", "perspective"), split="dev"):
    """Render the evaluation corpus. Returns a manifest list of dicts:
    {card_id, layout, degradation, png_path, pdf_path, truth: {field: value}}.

    Each layout gets `patients` cards; degradation type cycles per card so
    every degradation appears in every layout while keeping the total bounded.

    Eval hygiene: patients are deterministically split into a dev half (used
    for tuning) and a test half (held out) — `split="dev"|"test"`. Tune only
    on dev; report final numbers on test.
    """
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_rows(dataset_path, patients, rng)
    # Deterministic dev/test split of the patient rows: first half dev.
    if split in ("dev", "test"):
        half = (len(rows) + 1) // 2
        rows = rows[:half] if split == "dev" else rows[half:]
    manifest = []
    for layout in LAYOUT_NAMES:
        for idx, row in enumerate(rows):
            degradation = degrade_cycle[idx % len(degrade_cycle)]
            card_id = f"{layout}_{idx:02d}_{degradation}"
            truth = dict(row["values"])
            printed = {k: _format_value(k, v, layout) for k, v in truth.items()}
            png, pdf = _render_card(layout, row, printed, card_id, out_dir)
            truth_printed = {f: printed[f][2] for f in truth}
            truth_printed["visit_date"] = row["values"]["visit_date"]
            (out_dir / f"{card_id}.json").write_text(
                json.dumps({"card_id": card_id, "layout": layout, "degradation": degradation, "truth": truth_printed}, indent=1),
                encoding="utf-8",
            )
            manifest.append({
                "card_id": card_id, "layout": layout, "degradation": degradation,
                "png_path": str(png), "pdf_path": str(pdf), "truth": truth_printed,
            })
    return manifest


def _load_rows(dataset_path, patients, rng):
    """Pick `patients` rows and build printed values incl. visit_date and
    gestational_week (the CSV has neither — dates/weeks are generated)."""
    import pandas as pd

    from mlcore.constants import COLUMN_MAP, PLAUSIBILITY_RANGES

    df = pd.read_csv(dataset_path)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=COLUMN_MAP)
    clean = df[
        df["age"].between(*PLAUSIBILITY_RANGES["age"])
        & df["body_temperature"].between(*PLAUSIBILITY_RANGES["body_temperature"])
        & df["systolic_bp"].between(*PLAUSIBILITY_RANGES["systolic_bp"])
        & df["diastolic_bp"].between(*PLAUSIBILITY_RANGES["diastolic_bp"])
    ]
    sample = clean.sample(n=min(patients, len(clean)), random_state=rng.randrange(1 << 30))
    rows = []
    for _, r in sample.iterrows():
        rows.append({
            "name": str(r.get("name", ""))[:12],
            "values": {
                **{f: r[f] for f in FEATURES},
                "gestational_week": rng.randint(12, 40),
                "visit_date": (date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))).isoformat(),
            },
        })
    return rows


def _render_card(layout, row, printed, card_id, out_dir):
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas as rl_canvas

    fonts = _register_fonts(None)
    buffer = io.BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=A5)
    width, height = A5

    c.setFont("Helvetica-Bold", 11)
    c.drawString(30, height - 30, "AIMHRA EVAL LAB (SYNTHETIC SAMPLE)")
    c.setFont("Helvetica", 8)
    c.drawString(30, height - 44, f"Patient: {row['name']}   Card: {card_id}")
    labels = LABEL_SETS.get(layout.split("-", 1)[-1] if layout.startswith(("syn-",)) else layout, LABEL_SETS["standard"]) \
        if layout in LABEL_SETS or layout.startswith("unit-") or layout == "two-column" else LABEL_SETS["standard"]
    if layout == "syn-clinical":
        labels = LABEL_SETS["clinical"]
    elif layout == "syn-bilingual":
        labels = LABEL_SETS["bilingual"]
    elif layout == "syn-compact":
        labels = LABEL_SETS["compact"]

    fields_order = [
        "age", "body_temperature", "heart_rate", "systolic_bp", "diastolic_bp",
        "bmi", "hba1c", "fasting_glucose", "gestational_week", "visit_date",
    ]
    if layout == "two-column":
        rng = random.Random(card_id)
        fields_order = fields_order[:]
        rng.shuffle(fields_order)

    sep = {"list-colon": " : ", "syn-compact": ":", "list-dashes": " - "}.get(layout, " ")
    compact = layout == "syn-compact"

    def draw_line(x, y, field, value_data):
        printed, unit, _truth = value_data
        label = labels[field]
        text = f"{label}{sep}{printed}" + (f" {unit}" if unit else "")
        if compact:
            text = text.replace(" ", "")
        c.setFont("Helvetica", 9)
        c.drawString(x, y, text[:70])
        if fonts["np"] and " / " in label:
            # Approximate Devanagari second line (no complex shaping).
            np_part = label.split(" / ")[1]
            c.setFont(fonts["np"], 8)
            c.drawString(x + 8, y - 11, np_part[:40])

    if layout == "qr":
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing as _Drawing
        from reportlab.graphics import renderPDF as _renderPDF

        payload = json.dumps({"fields": {f: row["values"][f] for f in fields_order}}, ensure_ascii=False)
        widget = QrCodeWidget(payload[:900])
        bounds = widget.getBounds()
        d = _Drawing(120, 120, transform=[120 / (bounds[2] - bounds[0]), 0, 0,
                                          120 / (bounds[3] - bounds[1]), 0, 0])
        d.add(widget)
        c.setFont("Helvetica", 8)
        c.drawString(30, height - 60, "SYNTHETIC EVAL CARD — values also embedded in the QR code")
        _renderPDF.draw(d, c, 30, height - 200)
        c.setFont("Helvetica", 9)
        yy = height - 210
        for f in fields_order:
            printed, unit, _t = _format_value(f, row["values"][f], layout)
            c.drawString(170, yy, f"{labels[f]}: {printed}" + (f" {unit}" if unit else ""))
            yy -= 16
        c.save()
        pdf_bytes = buffer.getvalue()
        pdf_path = out_dir / f"{card_id}.pdf"
        png_path = out_dir / f"{card_id}.png"
        pdf_path.write_bytes(pdf_bytes)
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pix = doc[0].get_pixmap(dpi=220)
        pix.save(str(png_path))
        doc.close()
        return png_path, pdf_path

    # Step 4: every card embeds a QR payload of its fields by default —
    # using the PRINTED values so the QR always matches what is on the page.
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing as _Drawing
    from reportlab.graphics import renderPDF as _renderPDF

    printed_payload = {}
    for f in fields_order:
        printed_str, _unit, truth_val = _format_value(f, row["values"][f], layout)
        printed_payload[f] = truth_val if truth_val is not None else printed_str
    payload = json.dumps({"fields": printed_payload}, ensure_ascii=False)
    widget = QrCodeWidget(payload[:1200])
    bounds = widget.getBounds()
    qr_size = 64
    d = _Drawing(qr_size, qr_size, transform=[qr_size / (bounds[2] - bounds[0]), 0, 0,
                                              qr_size / (bounds[3] - bounds[1]), 0, 0])
    d.add(widget)
    _renderPDF.draw(d, c, width - qr_size - 24, height - qr_size - 24)

    y = height - 70
    if layout.startswith("table"):
        col2 = width * (0.55 if layout == "table-2col" else 0.45)
        col3 = width * 0.75
        c.setFont("Helvetica-Bold", 9)
        c.drawString(30, y, "Test"); c.drawString(col2, y, "Result")
        if layout == "table-3col-unit":
            c.drawString(col3, y, "Unit")
        y -= 16
        for f in fields_order:
            printed, unit, _t = printed_data = _format_value(f, row["values"][f], layout)
            label = labels[f]
            c.setFont("Helvetica", 9)
            c.drawString(30, y, label[:34])
            c.drawString(col2, y, printed)
            if layout == "table-3col-unit":
                c.drawString(col3, y, unit)
            if fonts["np"] and " / " in label:
                c.setFont(fonts["np"], 7)
                c.drawString(38, y - 9, label.split(" / ")[1][:30])
            y -= 22
    else:
        for f in fields_order:
            draw_line(30, y, f, _format_value(f, row["values"][f], layout))
            y -= 26

    c.save()
    pdf_bytes = buffer.getvalue()

    pdf_path = out_dir / f"{card_id}.pdf"
    png_path = out_dir / f"{card_id}.png"
    pdf_path.write_bytes(pdf_bytes)

    # Rasterize at 130 dpi with PyMuPDF for the image-side methods.
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = doc[0].get_pixmap(dpi=220)  # >= gate min width (1200)
    pix.save(str(png_path))
    doc.close()
    return png_path, pdf_path
