#!/usr/bin/env python3
"""
Lab Report Generator  (HbA1c / Biochemistry report, A4, PDF + PNG)
===================================================================

Reads Mathernal_Risk.csv (one report per row) OR lets you type the patient
details yourself, and produces for every patient:

    <out>/pdf/<ID>_<Name>.pdf      (vector A4 PDF)
    <out>/png/<ID>_<Name>.png      (image of the same page)

USAGE
-----
  python lab_report_generator.py                       -> asks: CSV or manual entry
  python lab_report_generator.py --csv Mathernal_Risk.csv
  python lab_report_generator.py --csv Mathernal_Risk.csv --limit 20
  python lab_report_generator.py --csv Mathernal_Risk.csv --ids 101 102 250
  python lab_report_generator.py --csv Mathernal_Risk.csv --merge      (also one combined PDF)
  python lab_report_generator.py --manual                -> type name / values yourself

OPTIONS
  --out DIR        output folder (default: reports)
  --no-png         only PDFs          --no-pdf   only PNG images
  --dpi N          PNG resolution (default 150)
  --workers N      parallel processes for big CSV runs (default: all CPUs)
  --sex M|F --title "Ms." --referred-by "Dr. X (MBBS)"   defaults used for CSV rows

Values are printed exactly as they appear in the CSV / as you type them (no conversion).

Edit the LAB dictionary below to change letterhead, signatures, phone, etc.

REQUIREMENTS:  pip install reportlab pypdfium2 pandas pypdf
"""
import argparse
import csv
import io
import os
import re
import sys
from datetime import datetime
from multiprocessing import Pool, cpu_count

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# ----------------------------------------------------------------------------
# 1. LAB / LETTERHEAD SETTINGS  (edit freely)
# ----------------------------------------------------------------------------
LAB = {
    "name_line1": "Labsmart Software",
    "name_line2": "Sample Letterhead",
    "regd_no": "XXXX54826XX",
    "phone": "+91 12345 67890",
    "email": "yourlabname@gmail.com",
    "website": "https://www.yourlabname.in/",
    "qr_base_url": "https://www.yourlabname.in/report/",   # QR = this + registration no.
    "timings": "Monday to Sunday, 8 am to 8 pm",
    # image = path to a PNG of the signature (transparent background is best).
    # If None, the name is drawn in an italic "signature" style.
    "signers": [
        {"name": "Mr. Sachin Sharma", "title": "DMLT, Lab Incharge", "image": None},
        {"name": "Dr. A. K. Asthana", "title": "MBBS, MD Pathologist", "image": None},
    ],
    "default_title": "Ms.",
    "default_sex": "F",
    "default_referred_by": "Dr. Sachin Patil (MBBS)",
}

# ----------------------------------------------------------------------------
# 2. PAGE GEOMETRY  (everything is designed on a 1018 x 1442 px canvas, the
#    size of the sample image, and scaled to A4)
# ----------------------------------------------------------------------------
PW, PH = 1018.0, 1442.0
NAVY = HexColor("#0C3F6E")
NAVY_LIGHT = HexColor("#1D5C94")
PANEL = HexColor("#E8EEF6")
GREY = Color(0.33, 0.33, 0.33)
SOFT = HexColor("#D9E5F1")
R_, B_ = "Helvetica", "Helvetica-Bold"


class Pen:
    """Tiny helper: draw using top-left pixel coordinates of the sample image."""

    def __init__(self, c):
        self.c = c
        self.W, self.H = A4
        self.sx, self.sy = self.W / PW, self.H / PH

    def X(self, x): return x * self.sx
    def Y(self, y): return self.H - y * self.sy

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=1, dash=None):
        c = self.c
        c.saveState()
        if fill is not None: c.setFillColor(fill)
        if stroke is not None:
            c.setStrokeColor(stroke); c.setLineWidth(lw * self.sx)
            if dash: c.setDash(*[d * self.sx for d in dash])
        c.rect(self.X(x), self.Y(y + h), w * self.sx, h * self.sy,
               fill=fill is not None, stroke=stroke is not None)
        c.restoreState()

    def line(self, x1, y1, x2, y2, lw=1, color=black, dash=None, cap=0):
        c = self.c
        c.saveState()
        c.setStrokeColor(color); c.setLineWidth(lw * self.sx); c.setLineCap(cap)
        if dash: c.setDash(*[d * self.sx for d in dash])
        c.line(self.X(x1), self.Y(y1), self.X(x2), self.Y(y2))
        c.restoreState()

    def text(self, x, y, s, size, font=R_, color=black, align="l"):
        """y = vertical CENTRE of the text line (as measured on the sample)."""
        c = self.c
        c.saveState()
        c.setFillColor(color)
        c.setFont(font, size * self.sx)
        yy = self.Y(y + 0.36 * size)
        if align == "l": c.drawString(self.X(x), yy, s)
        elif align == "r": c.drawRightString(self.X(x), yy, s)
        else: c.drawCentredString(self.X(x), yy, s)
        c.restoreState()

    @staticmethod
    def width(s, size, font=R_): return stringWidth(s, font, size)


# ----------------------------------------------------------------------------
# 3. PATIENT DATA, CONVERSIONS, FLAGS
# ----------------------------------------------------------------------------
def to_float(v):
    try:
        if v is None or str(v).strip() == "": return None
        return float(str(v).strip())
    except ValueError:
        return None


def fnum(x, nd=1):
    """6.0 -> '6',  5.85 -> '5.9'"""
    s = f"{x:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def build_patient(raw, opts):
    """raw: dict with keys name, age, id, hba1c, glucose, temp, hr, sys, dia, bmi, status ..."""
    p = dict(raw)
    p["title"] = p.get("title") or opts.get("title") or LAB["default_title"]
    p["sex"] = (p.get("sex") or opts.get("sex") or LAB["default_sex"]).upper()[:1]
    p["referred_by"] = p.get("referred_by") or opts.get("referred_by") or LAB["default_referred_by"]

    # ---- values are kept EXACTLY as entered (no unit conversion) --------
    h = to_float(p.get("hba1c"))
    p["hba1c_txt"] = str(p.get("hba1c") or "").strip()
    p["fbs_txt"] = str(p.get("glucose") or "").strip()
    # eAG / ADA-table highlight only make sense when the value is a % (<= 20)
    p["pct"] = h if (h is not None and h <= 20) else None
    p["eag"] = 28.7 * h - 46.7 if p["pct"] is not None else None
    p["fbs"] = to_float(p.get("glucose"))

    for k in ("age", "temp", "hr", "sys", "dia", "bmi"):
        p[k] = to_float(p.get(k))
    return p


# plausible ranges -> used only to LOG suspicious CSV rows (report is still made)
PLAUSIBLE = {"age": (10, 60), "temp": (90, 110), "hr": (30, 220), "sys": (60, 260),
             "dia": (30, 150), "bmi": (12, 50)}


def data_warnings(p):
    out = []
    for k, (lo, hi) in PLAUSIBLE.items():
        v = p.get(k)
        if v is not None and not (lo <= v <= hi):
            out.append(f"{k}={fnum(v, 2)} outside plausible range {lo}-{hi}")
    return out


# ----------------------------------------------------------------------------
# 4. DRAWING
# ----------------------------------------------------------------------------
def draw_logo(pen):
    """Simple white microscope icon."""
    c = pen.c
    c.saveState()
    c.setFillColor(white); c.setStrokeColor(white)
    # base
    pen.rect(52, 130, 52, 10, fill=white)
    # stage
    pen.rect(60, 116, 34, 5, fill=white)
    # arm (thick arc)
    c.setLineWidth(8 * pen.sx); c.setLineCap(1)
    p = c.beginPath()
    p.moveTo(pen.X(72), pen.Y(100))
    p.curveTo(pen.X(48), pen.Y(104), pen.X(46), pen.Y(130), pen.X(72), pen.Y(130))
    c.drawPath(p, stroke=1, fill=0)
    # tube (rotated)
    c.translate(pen.X(86), pen.Y(92)); c.rotate(-28)
    c.setLineWidth(0)
    c.roundRect(-8 * pen.sx, -34 * pen.sx, 16 * pen.sx, 62 * pen.sx, 3 * pen.sx, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(-8 * pen.sx, -6 * pen.sx, 16 * pen.sx, 3 * pen.sx, fill=1, stroke=0)
    c.restoreState()


def draw_icons(pen, y, kind):
    c = pen.c
    cx, cy = 655, y
    c.saveState()
    c.setStrokeColor(white); c.setFillColor(white)
    if kind == "phone":
        c.setLineWidth(5 * pen.sx); c.setLineCap(1)
        p = c.beginPath()
        p.moveTo(pen.X(cx - 7), pen.Y(cy - 5))
        p.curveTo(pen.X(cx - 7), pen.Y(cy + 8), pen.X(cx + 2), pen.Y(cy + 9), pen.X(cx + 8), pen.Y(cy + 7))
        c.drawPath(p, stroke=1, fill=0)
    elif kind == "mail":
        pen.rect(cx - 9, cy - 7, 18, 14, fill=white)
        c.setStrokeColor(NAVY); c.setLineWidth(1.4 * pen.sx)
        p = c.beginPath()
        p.moveTo(pen.X(cx - 8), pen.Y(cy - 6)); p.lineTo(pen.X(cx), pen.Y(cy + 1)); p.lineTo(pen.X(cx + 8), pen.Y(cy - 6))
        c.drawPath(p, stroke=1, fill=0)
    else:  # globe
        c.setLineWidth(1.6 * pen.sx)
        c.circle(pen.X(cx), pen.Y(cy), 8 * pen.sx, stroke=1, fill=0)
        c.ellipse(pen.X(cx - 3.5), pen.Y(cy + 8), pen.X(cx + 3.5), pen.Y(cy - 8), stroke=1, fill=0)
        c.line(pen.X(cx - 8), pen.Y(cy), pen.X(cx + 8), pen.Y(cy))
    c.restoreState()


def draw_header(pen):
    pen.rect(0, 0, PW, 222, fill=NAVY)
    pen.text(1012, 20, f"Regd. No.: {LAB['regd_no']}", 18.1, B_, white, "r")
    draw_logo(pen)
    pen.text(133, 85, LAB["name_line1"], 45.8, R_, white)
    pen.text(133, 140, LAB["name_line2"], 45.8, R_, white)
    for y, kind, key in ((77, "phone", "phone"), (113, "mail", "email"), (147, "globe", "website")):
        draw_icons(pen, y, kind)
        pen.text(678, y, LAB[key], 18.4, R_, SOFT)


def draw_barcode(pen, value, x, y, w, h):
    bc = code128.Code128(str(value), barWidth=1, barHeight=h * pen.sy, quiet=False)
    bw = (w * pen.sx) / bc.width
    bc = code128.Code128(str(value), barWidth=bw, barHeight=h * pen.sy, quiet=False)
    bc.drawOn(pen.c, pen.X(x), pen.Y(y + h))


def draw_qr(pen, data, x, y, size):
    qr = QrCodeWidget(data)
    b = qr.getBounds()
    s = size * pen.sx
    d = Drawing(s, s, transform=[s / (b[2] - b[0]), 0, 0, s / (b[3] - b[1]), 0, 0])
    d.add(qr)
    renderPDF.draw(d, pen.c, pen.X(x), pen.Y(y + size))


def draw_patient_block(pen, p, when):
    full = f"{p['title']} {p['name']}".strip()
    pen.text(32, 255, full, 20.8, B_)
    labels = [("Age / Sex", 280), ("Referred by", 302), ("Reg. no.", 324)]
    for lab, y in labels:
        pen.text(32, y, lab, 14.5)
    age = f"{int(round(p['age']))} YRS" if p.get("age") is not None else "-"
    pen.text(126, 280, f": {age} / {p['sex']}", 14.5)
    ref = p["referred_by"]
    m = re.match(r"^(.*?)(\s*\(.*\))$", ref)
    if m:
        pen.text(126, 302, f": {m.group(1)}", 14.5)
        pen.text(126 + pen.width(f": {m.group(1)}", 14.5) + 3, 302, m.group(2).strip(), 11)
    else:
        pen.text(126, 302, f": {ref}", 14.5)
    pen.text(126, 324, f": {p['reg']}", 14.5, B_)

    pen.line(502, 233, 502, 350, 1)
    pen.line(821, 233, 821, 350, 1)
    draw_barcode(pen, p["reg"], 527, 235, 105, 23)
    pen.text(640, 249, str(p["reg"]), 10.5)
    d_full = when.strftime("%d/%m/%Y %I:%M %p")
    d_day = when.strftime("%d/%m/%Y")
    for lab, val, y in (("Registered on", d_full, 274), ("Collected on", d_day, 295),
                        ("Received on", d_day, 315), ("Reported on", d_full, 336)):
        pen.text(528, y, lab, 14.5)
        pen.text(630, y, f": {val}", 14.5)
    pen.text(908, 235, "Scan to download", 8.5, R_, black, "c")
    draw_qr(pen, LAB["qr_base_url"] + str(p["reg"]), 858, 245, 102)
    pen.line(22, 356, 996, 356, 1)


# ----- result rows ---------------------------------------------------------
def result_rows(p):
    """Build the rows of the BIOCHEMISTRY table. (kind, label, value, unit, ref, abnormal)"""
    rows = []
    if p["hba1c_txt"]:
        rows.append(("group", "HBA1C (GLYCOSYLATED HEMOGLOBIN)"))
        rows.append(("sub", "HBA1C", p["hba1c_txt"], "%" if p["pct"] is not None else "", "", False))
        if p["eag"] is not None:
            rows.append(("sub", "ESTIMATED AVERAGE GLUCOSE", f"{p['eag']:.2f}", "mg/dL", "", False))
    if p["fbs_txt"]:
        rows.append(("single", "FASTING BLOOD GLUCOSE", p["fbs_txt"], "mg/dL", "", False))
    vit = []
    if p["temp"] is not None:
        vit.append(("sub", "BODY TEMPERATURE", fnum(p["temp"], 1), "\xb0F", "97.0 - 99.0", not 97 <= p["temp"] <= 99))
    if p["hr"] is not None:
        vit.append(("sub", "HEART RATE", fnum(p["hr"], 0), "bpm", "60 - 100", not 60 <= p["hr"] <= 100))
    if p["sys"] is not None and p["dia"] is not None:
        vit.append(("sub", "BLOOD PRESSURE", f"{fnum(p['sys'], 0)} / {fnum(p['dia'], 0)}", "mmHg", "< 140 / 90",
                    p["sys"] >= 140 or p["dia"] >= 90))
    if p["bmi"] is not None:
        vit.append(("sub", "BODY MASS INDEX (BMI)", fnum(p["bmi"], 1), "kg/m\xb2", "18.5 - 24.9", not 18.5 <= p["bmi"] <= 24.9))
    if vit:
        rows.append(("group", "MATERNAL HEALTH PARAMETERS"))
        rows += vit
    return rows


def draw_results_table(pen, p):
    top, x0, x1 = 397, 25, 995
    pen.text(510, 381, "BIOCHEMISTRY", 19.6, B_, black, "c")
    rows = result_rows(p)
    y_head = top + 22
    n = len(rows)
    bottom = y_head + 15 + 24 * (n - 1) + 15 if n else y_head + 6
    pen.rect(x0, top, x1 - x0, bottom - top, stroke=black, lw=2)
    pen.line(x0, y_head, x1, y_head, 1.5)
    for x, t in ((30, "TEST"), (418, "VALUE"), (612, "UNIT"), (757, "REFERENCE")):
        pen.text(x, top + 11, t, 15.6, B_)
    for i, row in enumerate(rows):
        cy = y_head + 15 + 24 * i
        kind = row[0]
        if kind == "group":
            pen.text(30, cy, row[1], 16.7)
            continue
        _, label, val, unit, ref, abn = row
        pen.text(77 if kind == "sub" else 30, cy, label, 16.7, R_)
        pen.text(418, cy, val, 16.7, B_ if abn else R_)
        pen.text(612, cy, unit, 16.7)
        pen.text(757, cy, ref, 16.7)
    return bottom


def dashed_grid(pen, xs, ys):
    for y in ys:
        pen.line(xs[0], y, xs[-1], y, 1, black, (2.2, 2.2))
    for x in xs:
        pen.line(x, ys[0], x, ys[-1], 1, black, (2.2, 2.2))


def draw_interpretation(pen, p, top):
    """Light-blue ADA panel. Layout is relative to `top`. Returns bottom y."""
    FS = 15.7
    bottom = top + 449
    pen.rect(24, top, 972, bottom - top, fill=PANEL)
    pen.text(40, top + 32, "Interpretation as per American Diabetes Association (ADA) Guidelines", FS, B_)

    # --- table 1 ---
    t1 = top + 43
    xs = [41, 170, 400, 556, 711, 979]
    ys = [t1, t1 + 43, t1 + 66]
    dashed_grid(pen, xs, ys)
    heads = [("Reference", "Group"), ("Non-Diabetic adults >= 18", "years"), ("At Risk", "(Prediabetes)"),
             ("Diagnosing", "Diabetes"), ("Therapeutic goals for glycemic", "control")]
    for i, (a, b) in enumerate(heads):
        pen.text(xs[i] + 5, t1 + 10, a, FS)
        pen.text(xs[i] + 5, t1 + 30, b, FS)
    for i, v in enumerate(("HbA1c in%", "4.0-5.6", "5.7-6.4", ">= 6.5", "<7.0")):
        pen.text(xs[i] + 5, t1 + 54, v, FS)

    # --- clinical significance ---
    ty = t1 + 66 + 30
    pen.text(40, ty, "Clinical significance:", FS, B_)
    para = ["Hemoglobin A1c (HbA1c) level reflects the mean glucose concentration over the previous period (approximately 8-12 weeks). The",
            "following ranges may be used for interpretation of results. However, factors such as duration of diabetes, adherence to therapy and the",
            "age of the patient should also be considered in assessing the degree of blood glucose control."]
    for i, line in enumerate(para):
        pen.text(40, ty + 18 + 18.6 * i, line, FS)

    # --- table 2 (patient's band is highlighted in bold) ---
    t2 = ty + 18 + 18.6 * 2 + 14
    xs2 = [41, 254, 406, 501, 730]
    pitch = 23.8
    ys2 = [t2 + pitch * i for i in range(7)]          # 6 rows -> 7 horizontal lines
    dashed_grid(pen, xs2, ys2)
    table2 = [("Haemoglobin A1c (%) NSGP", "mmol/mol/IFCC Unit", "eAG (mg/dl)", "Degree of Glucose Control Unit"),
              (">8", ">63.9", ">183", "Action Suggested*"),
              ("7-8", "53.0 - 63.9", "154-183", "Fair Control"),
              ("<7", "<63.9", "<154", "Goal**"),
              ("6-7", "42.1 - 63.9", "126-154", "Near-normal glycemia"),
              ("<6", "<42.1", "<126", "Non-Diabetic level")]
    hit = None
    if p["pct"] is not None:
        v = p["pct"]
        hit = 1 if v > 8 else 2 if v >= 7 else 4 if v >= 6 else 5
    for r, row in enumerate(table2):
        for c_, cell in enumerate(row):
            pen.text(xs2[c_] + 6, t2 + pitch * r + 10.5, cell, FS, B_ if r == hit else R_)

    # --- footnotes ---
    fy = t2 + pitch * 6 + 30
    pen.text(40, fy, "*High risk of developing long term complications such as Retinopathy, Nephropathy, Neuropathy etc.", FS)
    pen.text(40, fy + 37, "**Some danger of hypoglycemic reaction in Type 1 diabetics. Some glucose intolerant individuals and \"subclinical\" diabetics may", FS)
    pen.text(40, fy + 55, "demonstrate HbA1c levels in this area.", FS)
    return bottom


def draw_signature(pen, sig, x_name, align):
    img = sig.get("image")
    if img and os.path.exists(img):
        w, h = 130, 60
        x = x_name if align == "l" else x_name - w
        pen.c.drawImage(img, pen.X(x), pen.Y(1176 + h), w * pen.sx, h * pen.sy, mask="auto", preserveAspectRatio=True)
    else:
        name = re.sub(r"^(Mr\.|Mrs\.|Ms\.|Dr\.)\s*", "", sig["name"])
        c = pen.c
        c.saveState()
        c.setFillColor(HexColor("#1B2A4A"))
        c.setFont("Times-BoldItalic", 30 * pen.sx)
        txt = name.split()[-1] if len(name) > 14 else name
        w = stringWidth(txt, "Times-BoldItalic", 30 * pen.sx)
        x = x_name + 10 if align == "l" else x_name - 30 - w / pen.sx
        c.translate(pen.X(x), pen.Y(1222)); c.rotate(7)
        c.drawString(0, 0, txt)
        c.restoreState()


def draw_footer(pen):
    s1, s2 = LAB["signers"]
    draw_signature(pen, s1, 55, "l")
    draw_signature(pen, s2, 982, "r")
    pen.text(47, 1250, s1["name"], 14.4, B_)
    pen.text(46, 1271, s1["title"], 14.4)
    pen.text(982, 1250, s2["name"], 14.4, B_, black, "r")
    pen.text(982, 1271, s2["title"], 14.4, R_, black, "r")
    pen.text(510, 1272, "Page 1 of 1", 14.5, R_, black, "c")
    pen.rect(0, 1284, PW, 7, fill=NAVY)
    pen.text(510, 1313, "NOT VALID FOR MEDICO LEGAL PURPOSE", 13.5, B_, Color(.15, .15, .15), "c")
    a, b = "Work timings: ", LAB["timings"]
    wa, wb = pen.width(a, 14.8), pen.width(b, 14.8, B_)
    x = 510 - (wa + wb) / 2
    pen.text(x, 1345, a, 14.8, R_, GREY)
    pen.text(x + wa, 1345, b, 14.8, B_, Color(.2, .2, .2))
    pen.text(510, 1377, "Please correlate clinically. Although the test results are checked thoroughly, in case of any unexpected test results which", 14.9, R_, GREY, "c")
    pen.text(510, 1394, "could be due to machine error or typing error or any other reason please contact the lab immediately for a free evaluation.", 14.9, R_, GREY, "c")
    pen.rect(0, 1415, PW, 27, fill=NAVY)
    pen.rect(338, 1415, 342, 27, fill=NAVY_LIGHT)


def draw_report(c, p, when):
    pen = Pen(c)
    draw_header(pen)
    draw_patient_block(pen, p, when)
    tbl_bottom = draw_results_table(pen, p)
    panel_top = tbl_bottom + 11
    panel_bottom = draw_interpretation(pen, p, panel_top)
    pen.text(510, panel_bottom + 19, "~~~ End of report ~~~", 16.7, R_, black, "c")
    draw_footer(pen)
    c.setTitle(f"Report {p['reg']} - {p['name']}")
    c.setAuthor(LAB["name_line1"])


def make_pdf_bytes(p, when):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    draw_report(c, p, when)
    c.showPage()
    c.save()
    return buf.getvalue()


def pdf_to_png(pdf_bytes, path, dpi):
    try:
        import pypdfium2 as pdfium
        page = pdfium.PdfDocument(pdf_bytes)[0]
        page.render(scale=dpi / 72).to_pil().save(path)
    except ImportError:  # fallback to poppler
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as t:
            t.write(pdf_bytes)
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", t.name, path[:-4]], check=True)
        os.unlink(t.name)


# ----------------------------------------------------------------------------
# 5. BATCH / INTERACTIVE FRONT-END
# ----------------------------------------------------------------------------
def safe(s): return re.sub(r"[^A-Za-z0-9_-]+", "_", str(s)).strip("_") or "patient"


def render_one(job):
    raw, opts = job
    p = build_patient(raw, opts)
    when = datetime.now()
    base = f"{safe(p['reg'])}_{safe(p['name'])}"
    pdf = make_pdf_bytes(p, when)
    pdf_path = png_path = None
    if opts["pdf"]:
        pdf_path = os.path.join(opts["out"], "pdf", base + ".pdf")
        with open(pdf_path, "wb") as f: f.write(pdf)
    if opts["png"]:
        png_path = os.path.join(opts["out"], "png", base + ".png")
        pdf_to_png(pdf, png_path, opts["dpi"])
    return p["reg"], p["name"], pdf_path, png_path, data_warnings(p)


def read_csv(path):
    """Header names are matched loosely, so small spelling/spacing changes don't matter."""
    def key(h):
        h = h.strip().lower()
        for k, pat in (("reg", "patient id"), ("name", "name"), ("age", "age"), ("temp", "temperature"),
                       ("hr", "heart"), ("sys", "systolic"), ("dia", "diastolic"), ("bmi", "bmi"),
                       ("hba1c", "hba1c"), ("glucose", "fasting"), ("status", "status")):
            if pat in h: return k
        return None
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        cols = {h: key(h) for h in rd.fieldnames}
        for line in rd:
            r = {cols[h]: (v or "").strip() for h, v in line.items() if cols.get(h)}
            if r.get("name") or r.get("reg"): rows.append(r)
    return rows


def ask(prompt, default=None, required=False):
    while True:
        s = input(f"{prompt}" + (f" [{default}]" if default not in (None, "") else "") + ": ").strip()
        if s: return s
        if default not in (None, ""): return str(default)
        if not required: return ""
        print("  (required)")


def manual_entry():
    print("\n--- Manual entry (press Enter to keep the [default] or to skip optional fields) ---")
    r = {}
    r["title"] = ask("Title", LAB["default_title"])
    r["name"] = ask("Patient name", required=True)
    r["age"] = ask("Age (years)", required=True)
    r["sex"] = ask("Sex (M/F)", LAB["default_sex"])
    r["referred_by"] = ask("Referred by", LAB["default_referred_by"])
    r["reg"] = ask("Registration / Patient ID", required=True)
    r["hba1c"] = ask("HbA1c value", required=True)
    r["glucose"] = ask("Fasting glucose (mg/dL) - optional")
    r["temp"] = ask("Body temperature (F) - optional")
    r["hr"] = ask("Heart rate (bpm) - optional")
    r["sys"] = ask("Systolic BP (mmHg) - optional")
    r["dia"] = ask("Diastolic BP (mmHg) - optional")
    r["bmi"] = ask("BMI (kg/m2) - optional")
    return r


def main():
    ap = argparse.ArgumentParser(description="HbA1c / biochemistry lab report generator",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--csv"); ap.add_argument("--manual", action="store_true")
    ap.add_argument("--out", default="reports"); ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*"); ap.add_argument("--merge", action="store_true")
    ap.add_argument("--no-png", action="store_true"); ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--dpi", type=int, default=150); ap.add_argument("--workers", type=int, default=cpu_count())
    ap.add_argument("--sex"); ap.add_argument("--title"); ap.add_argument("--referred-by")
    a = ap.parse_args()

    if not a.csv and not a.manual:
        print("1) Generate reports from the CSV file\n2) Enter patient details manually")
        choice = ask("Choose 1 or 2", "1")
        if choice == "2": a.manual = True
        else:
            here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Mathernal_Risk.csv")
            a.csv = ask("CSV path", "Mathernal_Risk.csv" if os.path.exists("Mathernal_Risk.csv") else here)

    opts = dict(out=a.out, png=not a.no_png, pdf=not a.no_pdf or a.merge, dpi=a.dpi, sex=a.sex, title=a.title,
                referred_by=a.referred_by)
    if a.no_pdf and a.no_png and not a.merge:
        sys.exit("Nothing to do: both --no-pdf and --no-png given.")
    os.makedirs(os.path.join(a.out, "pdf"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "png"), exist_ok=True)

    jobs = []
    if a.manual:
        while True:
            jobs.append((manual_entry(), opts))
            if ask("\nAdd another patient? (y/n)", "n").lower() != "y": break
    if a.csv:
        rows = read_csv(a.csv)
        if a.ids: rows = [r for r in rows if r.get("reg") in set(a.ids)]
        if a.limit: rows = rows[:a.limit]
        jobs += [(r, opts) for r in rows]
    print(f"Generating {len(jobs)} report(s) into '{a.out}/' ...")

    results, warn = [], []
    if len(jobs) > 3 and a.workers > 1:
        with Pool(a.workers) as pool:
            for i, res in enumerate(pool.imap(render_one, jobs, chunksize=8), 1):
                results.append(res)
                if i % 100 == 0 or i == len(jobs): print(f"  {i}/{len(jobs)}", flush=True)
    else:
        results = [render_one(j) for j in jobs]
    for reg, name, pdf, png, w in results:
        if w: warn.append((reg, name, "; ".join(w)))

    if a.merge:
        try:
            from pypdf import PdfWriter
            wr = PdfWriter()
            for _, _, pdf, _, _ in results:
                if pdf: wr.append(pdf)
            with open(os.path.join(a.out, "all_reports.pdf"), "wb") as f: wr.write(f)
            print("Combined PDF: all_reports.pdf")
        except ImportError:
            print("pip install pypdf  to enable --merge")
    if warn:
        wp = os.path.join(a.out, "data_warnings.csv")
        with open(wp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["Patient ID", "Name", "Warning"]); w.writerows(warn)
        print(f"{len(warn)} row(s) have suspicious values (report still created) -> {wp}")
    print("Done.")


if __name__ == "__main__":
    main()