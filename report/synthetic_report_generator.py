#!/usr/bin/env python3
"""
Synthetic Lab-Report Generator for OCR training
================================================
Makes A4 PDF + PNG (+ optional "photographed on a carpet" PNG) + JSON ground truth
(every word with its bounding box) for six report layouts:

  municipal    municipal-hospital biochemistry / haematology list report
  medicare     private-hospital haematology + biochemistry report (hand ticks / circled values)
  clinical     "Clinical Chemistry" report, two signatories
  immuno       diagnostic-centre immunology report with explanatory text, QR, 3 signatories
  special      "Special Test" (ANA) report with NOTE box
  audiogram    ENT audiogram: two audiogram charts, threshold tables, diagnosis

IMPORTANT - what is and is not copied
  * Layouts follow the report types you showed.
  * All hospitals, labs, doctors, registration numbers, patients, phone numbers, logos and
    signatures are FICTIONAL / randomly generated, and every page carries a small
    "SYNTHETIC SAMPLE" line. Nothing here reproduces a real institution or a real person.
  * Dates in the Nepali (BS) calendar are APPROXIMATE (month-length table), good enough for OCR data.

USAGE
  python synthetic_report_generator.py                         # 6 samples, one of each layout
  python synthetic_report_generator.py --count 200             # 200 random reports
  python synthetic_report_generator.py --types audiogram municipal --count 50
  python synthetic_report_generator.py --count 100 --augment   # + photo-style images
  python synthetic_report_generator.py --manual                # type name / values yourself

  CSV MODE (same data file as lab_report_generator.py):
  python synthetic_report_generator.py --csv Mathernal_Risk.csv            # one report per CSV row
  python synthetic_report_generator.py --csv Mathernal_Risk.csv --limit 20
  python synthetic_report_generator.py --csv Mathernal_Risk.csv --ids 101 102 250
  python synthetic_report_generator.py --csv Mathernal_Risk.csv --types municipal --augment
    * Patient ID, name, age and every test value come from the CSV and are printed EXACTLY as in
      the file (no unit conversion). The hospital, signatures, dates and sample numbers stay random.
    * Layouts used for CSV rows (cycled row by row): municipal, medicare, clinical. These are the
      table layouts that can carry the values. immuno / special / audiogram can be requested with
      --types, but then only the patient identity comes from the CSV (their tests are not in the CSV).
    * --sex M|F  --title "Ms."  --referred-by "Dr. X (MBBS)"   defaults for fields the CSV lacks
    * --count is ignored in CSV mode; use --limit / --ids.
    * Suspicious rows (implausible vitals) are still rendered and listed in <out>/data_warnings.csv
Options: --out DIR  --seed N  --dpi N  --workers N  --no-pdf  --augment

Output per report in <out>/:  pdf/ png/ photo/ labels/   (labels/*.json = fields + word boxes)

REQUIREMENTS:  pip install reportlab pypdfium2 pillow numpy
"""
import argparse, csv, io, json, math, os, random, re, sys
from datetime import date, datetime, timedelta
from multiprocessing import Pool, cpu_count

import reportlab
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

W, H = A4
_FD = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
for _n, _f in (("V", "Vera.ttf"), ("VB", "VeraBd.ttf"), ("VI", "VeraIt.ttf"), ("VBI", "VeraBI.ttf")):
    pdfmetrics.registerFont(TTFont(_n, os.path.join(_FD, _f)))

RED, NAVY, GREEN = HexColor("#C4161C"), HexColor("#16306B"), HexColor("#0B7A4B")
GREY, INK = HexColor("#666666"), HexColor("#1A2550")
BLUE_BAND, ORANGE = HexColor("#2F5FA8"), HexColor("#E8A21A")
MARK = "SYNTHETIC SAMPLE  -  GENERATED FOR OCR TRAINING  -  NOT A REAL MEDICAL REPORT"

# =============================================================================
# drawing toolkit  (all coordinates in points, origin TOP-LEFT)
# =============================================================================
class Doc:
    def __init__(s, c):
        s.c, s.words, s.n = c, [], 0

    def T(s, x, y, t, size=8, font="V", color=black, align="l", rec=True):
        """draw text with baseline y; returns width; records word boxes for ground truth"""
        t = str(t)
        w = stringWidth(t, font, size)
        x0 = x if align == "l" else (x - w if align == "r" else x - w / 2)
        s.c.setFillColor(color); s.c.setFont(font, size); s.c.drawString(x0, H - y, t)
        if rec and t.strip():
            s.n += 1
            for m in re.finditer(r"\S+", t):
                a = stringWidth(t[:m.start()], font, size); b = stringWidth(m.group(), font, size)
                s.words.append({"text": m.group(), "box": [x0 + a, y - size * .8, x0 + a + b, y + size * .25], "line": s.n})
        return w

    def fit(s, x, y, t, font, size, maxw, color=black, align="l"):
        w = stringWidth(t, font, size)
        s.T(x, y, t, size * min(1, maxw / w), font, color, align)

    def vtext(s, x, y, t, size, font="VB", color=white, rot=90):
        c = s.c; c.saveState(); c.translate(x, H - y); c.rotate(rot)
        c.setFillColor(color); c.setFont(font, size); c.drawCentredString(0, 0, t); c.restoreState()

    def L(s, x1, y1, x2, y2, lw=.6, color=black, dash=None):
        c = s.c; c.saveState(); c.setStrokeColor(color); c.setLineWidth(lw)
        if dash: c.setDash(*dash)
        c.line(x1, H - y1, x2, H - y2); c.restoreState()

    def R(s, x, y, w, h, fill=None, stroke=None, lw=.6, dash=None, r=0):
        c = s.c; c.saveState()
        if fill is not None: c.setFillColor(fill)
        if stroke is not None: c.setStrokeColor(stroke); c.setLineWidth(lw)
        if dash: c.setDash(*dash)
        kw = dict(stroke=stroke is not None, fill=fill is not None)
        if r: c.roundRect(x, H - y - h, w, h, r, **kw)
        else: c.rect(x, H - y - h, w, h, **kw)
        c.restoreState()

    def C(s, x, y, r, fill=None, stroke=None, lw=.6):
        c = s.c; c.saveState()
        if fill is not None: c.setFillColor(fill)
        if stroke is not None: c.setStrokeColor(stroke); c.setLineWidth(lw)
        c.circle(x, H - y, r, stroke=stroke is not None, fill=fill is not None); c.restoreState()

    def P(s, pts, fill=None, stroke=None, lw=.6, close=True):
        c = s.c; c.saveState()
        if fill is not None: c.setFillColor(fill)
        if stroke is not None: c.setStrokeColor(stroke); c.setLineWidth(lw)
        p = c.beginPath(); p.moveTo(pts[0][0], H - pts[0][1])
        for x, y in pts[1:]: p.lineTo(x, H - y)
        if close: p.close()
        c.drawPath(p, stroke=stroke is not None, fill=fill is not None); c.restoreState()

    def grad(s, x, y, w, h, c1, c2, n=40, vertical=True):
        for i in range(n):
            t = i / (n - 1)
            col = Color(*[c1.rgb()[k] * (1 - t) + c2.rgb()[k] * t for k in range(3)]) if hasattr(c1, "rgb") else c1
            if vertical: s.R(x, y + h * i / n, w, h / n + .6, fill=col)
            else: s.R(x + w * i / n, y, w / n + .6, h, fill=col)

    def barcode(s, val, x, y, w, h):
        bc = code128.Code128(val, barWidth=1, barHeight=h, quiet=False)
        bc = code128.Code128(val, barWidth=w / bc.width, barHeight=h, quiet=False)
        bc.drawOn(s.c, x, H - y - h)

    def qr(s, val, x, y, size):
        q = QrCodeWidget(val); b = q.getBounds(); k = size / (b[2] - b[0])
        dr = Drawing(size, size, transform=[k, 0, 0, k, 0, 0]); dr.add(q)
        renderPDF.draw(dr, s.c, x, H - y - size)

    def scribble(s, x, y, w, h, rng, color=INK, lw=.9):
        """random hand-written looking signature"""
        c = s.c; c.saveState(); c.setStrokeColor(color); c.setLineWidth(lw); c.setLineCap(1)
        p = c.beginPath(); n = rng.randint(5, 8)
        px, py = x, y + h * rng.uniform(.4, .9); p.moveTo(px, H - py)
        for i in range(1, n + 1):
            nx = x + w * i / n; ny = y + h * rng.uniform(.05, .95)
            p.curveTo(px + (nx - px) * .3, H - (py - h * rng.uniform(-.8, .8)), nx - (nx - px) * .3,
                      H - (ny + h * rng.uniform(-.8, .8)), nx, H - ny)
            px, py = nx, ny
        c.drawPath(p, stroke=1, fill=0)
        if rng.random() < .6:
            c.setLineWidth(lw * .8); c.line(x + w * .1, H - (y + h * .95), x + w * rng.uniform(.6, 1), H - (y + h * rng.uniform(.8, 1)))
        c.restoreState()

    def tick(s, x, y, rng, sz=6):
        s.L(x, y, x + sz * .35, y + sz * .4, .8, INK); s.L(x + sz * .35, y + sz * .4, x + sz * 1.1, y - sz * .5, .8, INK)

    def hand_circle(s, x, y, w, h, rng):
        c = s.c; c.saveState(); c.setStrokeColor(INK); c.setLineWidth(.8)
        k = rng.uniform(-1, 1)
        c.ellipse(x - 1 + k, H - y - h - 1, x + w + 1, H - y + 1 + k, stroke=1, fill=0); c.restoreState()

    def mark(s):
        s.T(W / 2, 836, MARK, 5.5, "V", getattr(s, "markcolor", GREY), "c")


# =============================================================================
# fake-data helpers
# =============================================================================
F_NAMES = "Sunita Anita Kamala Radha Sabina Mina Sarita Gita Laxmi Pramila Rekha Sapana Bimala Durga Kalpana Manju Nirmala Parbati Rita Sushila Asmita Binita Sangita".split()
M_NAMES = "Ramesh Suresh Prakash Bikash Deepak Rajan Sanjay Binod Kiran Nabin Hari Krishna Santosh Anil Dinesh Mahesh Roshan Sudip Bishal Amit".split()
SURN = "Shrestha Tamang Gurung Thapa Maharjan Adhikari Karki Basnet Rai Magar Lama Sharma Poudel Bhandari Khadka Dahal Bajracharya Koirala Neupane Subedi".split()
DOC_F = "Anil Rojan Sabin Meera Kamal Sunil Prabha Ganesh Nirmal Sarala Umesh Tara".split()
DOC_L = "Pandey Ghimire Regmi Joshi Acharya Upreti Bista Chalise Ojha Gautam Rijal Wagle".split()
BS_MONTH = [31, 31, 32, 31, 31, 30, 30, 29, 30, 29, 30, 30]


def ad_to_bs(d):
    """APPROXIMATE AD -> BS conversion (fine for synthetic data)"""
    ny, by = date(d.year, 4, 14), d.year + 57
    if d < ny: ny, by = date(d.year - 1, 4, 14), d.year + 56
    n = (d - ny).days
    for m, l in enumerate(BS_MONTH, 1):
        if n < l: return by, m, n + 1
        n -= l
    return by, 12, 30


def bs_str(dt, sep="/", time=True):
    y, m, d = ad_to_bs(dt.date())
    s = f"{y}{sep}{m:02d}{sep}{d:02d}"
    return s + (dt.strftime(" %H:%M:%S") if time else "")


def rand_dt(rng):
    return datetime(2024, 1, 1) + timedelta(seconds=rng.randint(0, int((datetime(2026, 11, 10) - datetime(2024, 1, 1)).total_seconds())))


def digits(rng, n): return "".join(rng.choice("0123456789") for _ in range(n))


def gen_patient(rng, sex=None, age=None):
    sex = (sex or rng.choice("MF")).upper()[:1]
    first = rng.choice(F_NAMES if sex == "F" else M_NAMES)
    sur = rng.choice(SURN)
    title = rng.choice(["Ms.", "Ms.", "Mrs."]) if sex == "F" else "Mr."
    age = int(age) if age else rng.randint(18, 82)
    return dict(title=title, first=first, last=sur, name=f"{first} {sur}".upper(), sex=sex, age=age,
                months=rng.randint(0, 11), phone="98" + digits(rng, 8), pid=digits(rng, 8))


def doc_name(rng, pre="Dr."): return f"{pre} {rng.choice(DOC_F)} {rng.choice(DOC_L)}"


def indian(n):
    s = str(int(n))
    if len(s) <= 3: return s
    head, tail, parts = s[:-3], s[-3:], []
    while len(head) > 2: parts.insert(0, head[-2:]); head = head[:-2]
    if head: parts.insert(0, head)
    return ",".join(parts + [tail])


def t(name, lo, hi, nd=1, unit="", ref=None, method="", comma=False, pad=False):
    return dict(name=name, lo=lo, hi=hi, nd=nd, unit=unit, ref=ref, method=method, comma=comma, pad=pad)


def fmt_val(v, s):
    if s["comma"] and s["nd"] == 0: return indian(v)
    txt = f"{v:.{s['nd']}f}"
    return txt.zfill(2) if s["pad"] else txt


def mk_test(rng, s, abn=.15, indent=True):
    lo, hi = s["lo"], s["hi"]; span = hi - lo
    if rng.random() < abn:
        v = lo - span * rng.uniform(.03, .25) if rng.random() < .5 else hi + span * rng.uniform(.03, .25)
    else:
        v = rng.uniform(lo, hi)
    v = max(0, round(v, s["nd"]))
    ref = s["ref"] or (f"{lo:.{s['nd']}f}-{hi:.{s['nd']}f}" if s["nd"] else f"{lo:g}-{hi:g}")
    return dict(k="test", name=s["name"], value=fmt_val(v, s), unit=s["unit"], ref=ref, method=s["method"],
                indent=indent, flag="L" if v < lo else "H" if v > hi else "", lo=lo, hi=hi, spec=s)


def rows_from(rng, groups, abn=.15):
    rows = []
    for g, specs in groups:
        if g: rows.append(dict(k="group", name=g))
        rows += [mk_test(rng, s, abn, bool(g)) for s in specs]
    return rows


# ---- test catalogue --------------------------------------------------------
SP = dict(
    glu=t("Blood Sugar R", 60, 150, 1, "mg/dl", "60-150", "spectrophotometry"),
    uric=t("Uric Acid", 2.0, 7.0, 1, "mg/dl", None, "spectrophotometry"),
    urea=t("UREA", 15, 45, 1, "mg/dl", "15-45", "spectrophotometry"),
    creat=t("S.Creatinine", 0.5, 1.4, 2, "mg/dl", "0.5-1.4", "spectrophotometry"),
    na=t("SODIUM(NA)", 135, 145, 1, "mEq/L", "135-145", "Ion selective electrode"),
    k=t("POTASSIUM(K)", 3.5, 5.5, 1, "mEq/L", "3.5-5.5", "spectrophotometry"),
    ft3=t("FT3", 3.30, 7.30, 1, "Pmol/L", "3.30-7.30", "(CLIA)"),
    ft4=t("FT4", 12.00, 23.00, 1, "Pmol/L", "12.00-23.00", "(CLIA)"),
    tsh=t("TSH", 0.30, 5.50, 1, "\u00b5IU/ml", "0.30-5.50", "(CLIA)"),
    chol=t("Total Cholesterol", 100, 220, 1, "mg/dl", "100-220"),
    trig=t("Tri-glyceride", 60, 200, 1, "mg/dl", "60-200"),
    hdl=t("HDL Cholesterol", 30, 70, 1, "mg/dl", "30-70"),
    tpo=t("Anti-TPO", .5, 32, 3, "IU/ml", "<32.000", "CLIA"),
    wbc=t("Total WBC Count", 4000, 11000, 0, "cell/cumm", "4000-11000", "Cell Counter", True),
    neu=t("Neutrophils", 45, 75, 0, "%", "45-75", pad=True), lym=t("Lymphocytes", 20, 45, 0, "%", "20-45", pad=True),
    eos=t("Eoslinophil", 1, 6, 0, "%", "1-6", pad=True), mono=t("Monocytes", 2, 10, 0, "%", "2-10", pad=True),
    baso=t("Basophils", 0, 1, 0, "%", "0-1", pad=True),
    hb=t("Hemoglobin(HB)", 12, 18, 1, "", "12-18", "Cell Counter"),
    plt=t("Platelets Count", 150000, 400000, 0, "cell/cumm", "150000-400000", "Cell Counter", True),
    rbc=t("Red Blood Cell (RBC) Count", 3.5, 5.5, 2, "cell/cumm", "3.5-5.5", "Cell Counter"),
    pcv=t("P.C.V.", 36, 47, 1, "%", "36-47", "Cell Counter"),
    mcv=t("Mean Cell Volume (MCV)", 76, 96, 1, "fl", "76-96", "Cell Counter"),
    mch=t("Mean Corpuscular Hemoglobil (MCH)", 27, 32, 1, "pg/cell", "27-32", "Cell Counter"),
    hba1c=t("HbA1c", 4.0, 6.0, 1, "%", "4.0-6.0", "HPLC"),
    tc=t("Total Count (TC)", 4000, 11000, 0, "/cumm", "4000-11000", "", True),
    neu2=t("Neutrophils", 40, 75, 0, "%", "40-75"), lym2=t("Lymphocytes", 20, 45, 0, "%", "20-45"),
    hb2=t("Haemoglobin", 13.5, 18.0, 1, "gm%", "13.5-18.0"), esr=t("ESR (Wintrobe)", 0, 10, 0, "mm/hr", "0-10"),
    glu2=t("Glucose (R)", 75, 140, 0, "mg%", "75-140", "GOD-POD"),
    cpk=t("CPK", 24, 195, 1, "IU/l", "24 - 195"), ldh=t("LDH", 140, 280, 0, "IU/l", "140 - 280"),
    amy=t("Amylase", 28, 100, 0, "U/L", "28 - 100"), ca=t("Calcium", 8.5, 10.5, 1, "mg/dl", "8.5 - 10.5"),
    ast=t("SGOT (AST)", 5, 40, 0, "IU/l", "5 - 40"), alt=t("SGPT (ALT)", 5, 40, 0, "IU/l", "5 - 40"),
    alp=t("Alkaline Phosphatase", 40, 130, 0, "IU/l", "40 - 130"), bil=t("Total Bilirubin", .2, 1.2, 1, "mg/dl", "0.2 - 1.2"),
)


def kv(d, xl, xv, y, label, value, size=8, bold=False, vsize=None):
    d.T(xl, y, label, size); d.T(xv - 7, y, ":", size); d.T(xv, y, value, vsize or size, "VB" if bold else "V")


def draw_rows(d, rows, y, cols, left, right, pitch=13, size=8, sep=True, flag_col=None, hand=None, title_size=9.5, rng=None):
    for r in rows:
        if r["k"] == "title":
            d.T((left + right) / 2, y + pitch * 1.15, r["name"], title_size, "VB", align="c"); y += pitch * 1.7; continue
        base = y + pitch * .72
        if r["k"] == "group":
            d.T(cols["test"], base, r["name"], size, "VB")
        else:
            d.T(cols["indent"] if r["indent"] else cols["test"], base, r["name"], size)
            bold = "VB" if (r["flag"] or r.get("bold")) else "V"
            wv = d.T(cols["value"], base, r["value"], size, bold)
            d.T(cols["unit"], base, r["unit"], size - .5)
            d.T(cols["ref"], base, r["ref"], size - .5)
            if r["method"] and "method" in cols: d.T(cols["method"], base, r["method"], size - 1.5, "V", GREY if size < 8 else black)
            if flag_col and r["flag"]: d.T(cols[flag_col], base, r["flag"], size, "VB")
            if hand and rng is not None:
                if r["flag"] and hand == "circle": d.hand_circle(cols["value"] - 3, y + 2, wv + 7, pitch - 3, rng)
                elif rng.random() < .75: d.tick(cols["value"] + wv + 5, base - 1, rng)
        y += pitch
        if sep: d.L(left + 3, y, right - 3, y, .3, HexColor("#999999"), (1, 1.5))
    return y


# ---- logos ------------------------------------------------------------------
def emblem(d, cx, cy, r):
    for i in range(14):
        a = i * 2 * math.pi / 14
        d.C(cx + r * .88 * math.cos(a), cy + r * .88 * math.sin(a), r * .13, fill=HexColor("#C21B2B"))
    d.C(cx, cy, r * .72, fill=white, stroke=HexColor("#7a1020"), lw=.4)
    d.P([(cx - r * .55, cy + r * .35), (cx - r * .1, cy - r * .35), (cx + r * .15, cy), (cx + r * .3, cy - r * .2), (cx + r * .55, cy + r * .35)], fill=HexColor("#3A62B0"))
    d.P([(cx - r * .55, cy + r * .35), (cx + r * .55, cy + r * .35), (cx + r * .4, cy + r * .55), (cx - r * .4, cy + r * .55)], fill=HexColor("#3E8E3E"))


def pagoda(d, cx, cy, r):
    d.C(cx, cy, r, fill=HexColor("#7BA05B"), stroke=NAVY, lw=1.5)
    for i, wdt in enumerate((.95, .7, .5)):
        yy = cy + r * .25 - i * r * .36
        d.P([(cx - r * wdt, yy), (cx + r * wdt, yy), (cx + r * wdt * .7, yy - r * .3), (cx - r * wdt * .7, yy - r * .3)], fill=HexColor("#D9A21B"))
        d.R(cx - r * wdt * .5, yy, r * wdt, r * .22, fill=HexColor("#8a2d1a"))


def cross_logo(d, x, y, s):
    d.R(x + s * .33, y, s * .34, s, fill=GREEN); d.R(x, y + s * .33, s, s * .34, fill=GREEN)
    for dx in (.52, .72, .92): d.C(x + s * dx, y + s * 1.12, s * .09, fill=RED)


def swoosh(d, x, y, s, c1=NAVY, c2=GREEN):
    d.P([(x, y + s), (x + s * .4, y), (x + s * .55, y + s * .1), (x + s * .2, y + s * .9)], fill=c1)
    d.P([(x + s * .2, y + s), (x + s * .75, y + s * .35), (x + s * .85, y + s * .5), (x + s * .5, y + s)], fill=c2)
    d.C(x + s * .85, y + s * .15, s * .1, fill=c2)


def fb_icon(d, x, y, s=14):
    d.R(x, y, s, s, fill=HexColor("#3B3F8C"), r=3); d.T(x + s * .62, y + s * .88, "f", s * .9, "VB", white, "c", rec=False)


def mail_icon(d, x, y, s=16):
    d.R(x, y, s, s * .72, fill=HexColor("#3B3F8C"), r=2)
    d.L(x + 1, y + 1, x + s / 2, y + s * .42, .8, white); d.L(x + s - 1, y + 1, x + s / 2, y + s * .42, .8, white)


def inst_names(rng):
    a = rng.choice(["Himal", "Lotus", "Sunrise", "Greenfield", "Riverside", "Valley", "Everest", "Annapurna", "Mandala"])
    b = rng.choice(["Valley", "City", "Central", "Metro", "Community", "Bagmati", "Hill"])
    return a, b


# =============================================================================
# 1) MUNICIPAL
# =============================================================================
def gen_municipal(rng):
    p = gen_patient(rng); dt = rand_dt(rng); a, b = inst_names(rng)
    kind = rng.choice(["bio_thy", "tpo", "cbc"])
    if kind == "bio_thy":
        title = "Bio-Chemistry Report"
        rows = [dict(k="title", name=title)] + rows_from(rng, [(None, [SP["glu"], SP["uric"]]), ("Thyroid Function Test", [SP["ft3"], SP["ft4"], SP["tsh"]])])
    elif kind == "tpo":
        title = "Bio-Chemistry Report"
        rows = [dict(k="title", name=title)] + rows_from(rng, [("Anti TPO Antibody", [SP["tpo"]])], .1)
    else:
        title = "Haematology Report"
        rows = [dict(k="title", name=title)] + rows_from(rng, [("COMPLETE BLOOD COUNT", [SP["wbc"]]), ("DIFFERENTIAL COUNT", [SP["neu"], SP["lym"], SP["eos"], SP["mono"], SP["baso"]]),
                                                               (None, [SP["hb"], SP["plt"], SP["rbc"], SP["pcv"], SP["mcv"], SP["mch"]]), ]) \
            + [dict(k="title", name="Bio-Chemistry Report")] + rows_from(rng, [(None, [SP["glu"], SP["urea"], SP["creat"], SP["na"], SP["k"]]), ("LIPID PROFILE", [SP["chol"], SP["trig"], SP["hdl"]])])
    return dict(template="municipal", patient=p, dt=dt, rows=rows, inst=dict(muni=f"{a} {b} Municipality", hosp=f"{a} {b} Hospital", phone=f"01-4{digits(rng, 6)}, 4{digits(rng, 6)}",
                mail=f"hospital.{a.lower()}{b.lower()}@mail.example", fb=f"{a.lower()}hospital"), sample=f"{ad_to_bs(dt.date())[0]}-N{digits(rng, 5)}", pages=1)


def patient_age_gender(p): return f"{p['age']} Y {p['months']} M / {p['sex']}"


def draw_municipal(d, D, rng):
    p, I, dt = D["patient"], D["inst"], D["dt"]
    emblem(d, 100, 72, 31); pagoda(d, 497, 72, 31)
    d.fit(300, 48, I["muni"], "VB", 13, 280, RED, "c") if False else d.fit(300, 48, I["muni"], "VB", 13, 280, RED, "c")
    d.fit(300, 72, I["hosp"], "VB", 19, 300, RED, "c")
    for i, s in enumerate(["Ward No. 4", "Bagmati Province, Kathmandu", I["phone"]]): d.T(300, 88 + i * 10, s, 7.5, "V", RED, "c")
    d.L(74, 114, 521, 114, 1.2, RED)
    y0 = 136
    ar = f"{bs_str(dt)}"
    for i, (l, v, b) in enumerate([("Name", f"{p['title']} {p['name']}", True), ("Patient Type / Ward", "OPD", False), ("Age/Gender", patient_age_gender(p), True), ("Referred by", D.get("refby", ""), False), ("Sample Registered Date", ar, False)]):
        kv(d, 52, 160, y0 + i * 11, l, v, 7.5, b, 8.2 if i == 0 else 7.5)
    d.barcode(p["pid"], 418, 119, 68, 17)
    for i, (l, v) in enumerate([("Patient No.", p["pid"]), ("Sample No.", D["sample"])]):
        d.T(318, y0 + 6 + i * 10, l, 7.5); d.T(412, y0 + 6 + i * 10, ":", 7.5); d.T(418, y0 + 6 + i * 10, v, 7.5, "VB")
    d.T(318, y0 + 26, "Date & Time of Analysis", 7.5); d.T(418, y0 + 26, bs_str(dt + timedelta(hours=4)), 7.5)
    top = 196
    cols = dict(test=52, indent=70, value=205, unit=272, ref=330, method=420)
    for k, x in (("Test", 52), ("Result", 205), ("Unit", 272), ("Ref. Range", 330), ("Method", 420)): d.T(x, top + 10, k, 8, "VB")
    d.L(48, top + 14, 520, top + 14, .5)
    yb = draw_rows(d, D["rows"], top + 16, cols, 48, 520, 13, 8, True)
    d.R(48, top, 472, yb - top + 3, stroke=black, lw=.9)
    d.T(48, yb + 17, "Please correlate with clinical symptoms.", 7.5)
    d.scribble(68, 668, 90, 24, rng); d.L(64, 702, 168, 702, .7); d.T(70, 714, "Lab Technician", 7.5)
    d.L(405, 698, 510, 698, .7); d.T(412, 710, "Lab Technologist", 7.5)
    d.T(300, 752, "---------- End of Report ----------", 7.5, "V", black, "c")
    d.T(64, 778, f"Printed Date/Time :   {(dt + timedelta(days=1)).strftime('%Y/%m/%d')} AD - {bs_str(dt + timedelta(days=1), time=False)} BS{(dt + timedelta(days=1)).strftime('%H:%M:%S')}", 7)
    d.T(420, 774, "Page :1     of 1", 7)
    d.L(92, 800, 506, 800, .9, RED); d.L(92, 796, 92, 804, .9, RED); d.L(506, 796, 506, 804, .9, RED)
    fb_icon(d, 130, 808); d.T(150, 819, I["fb"], 8, "VB", HexColor("#3B3F8C"))
    mail_icon(d, 262, 808); d.T(284, 819, I["mail"], 8, "V", RED)


# =============================================================================
# 2) MEDICARE-like private hospital
# =============================================================================
def gen_medicare(rng):
    p = gen_patient(rng); dt = rand_dt(rng); a, b = inst_names(rng)
    hb = t("Haemoglobin", 12.0, 15.5, 1, "gm%", "12.0-15.5") if p["sex"] == "F" else SP["hb2"]
    rows = [dict(k="title", name="HAEMATOLOGY REPORT")] + rows_from(rng, [(None, [SP["tc"]]), ("Differential Count (DC)", [SP["neu2"], SP["lym2"]]), (None, [hb, SP["esr"]])]) \
        + [dict(k="title", name="BIOCHEMISTRY REPORT")] + rows_from(rng, [(None, [SP["glu2"]])])
    sigs = [(doc_name(rng, ""), "Medical Lab Technician"), (doc_name(rng, ""), "Medical Lab Technician"), (doc_name(rng), "Consultant Pathologist"), (doc_name(rng, "Prof. Dr."), "Consultant Pathologist")]
    return dict(template="medicare", patient=p, dt=dt, rows=rows, sigs=sigs, sample=f"{ad_to_bs(dt.date())[0]}-N{digits(rng, 5)}",
                inst=dict(name=f"{b} National Hospital & Research Centre Ltd.", short=f"{b} National", addr=f"{a} Chowk, Kathmandu, Telephone: 977-1-4{digits(rng, 6)}, 4{digits(rng, 6)}",
                          addr2=f"P.O.Box {digits(rng, 5)}, Kathmandu, Nepal, Fax: 977-1-4{digits(rng, 6)}", mail=f"info@{b.lower()}hospital.example"), enteredby=rng.choice(F_NAMES).upper())


def draw_medicare(d, D, rng):
    p, I, dt = D["patient"], D["inst"], D["dt"]
    d.R(0, 0, W, 842, fill=HexColor("#F1F6FB"))
    cross_logo(d, 24, 40, 40); d.T(44, 108, "Research Centre", 5.5, "VB", GREEN, "c")
    d.fit(84, 66, I["name"], "VB", 18, 470, GREEN)
    d.T(84, 82, I["addr"], 8.3); d.T(84, 94, I["addr2"], 8.3); d.T(84, 106, f"Email: {I['mail']}", 8.3)
    y0 = 148
    for i, (l, v, b) in enumerate([("Name", f"{p['title']} {p['name']}", True), ("Patient Type / Ward", "OPD /", False), ("Age/Gender", f"{p['age']} Y / {p['sex']}", True), ("Referred by", D.get("refby", ""), False), ("Sample Registered Date", bs_str(dt), False)]):
        kv(d, 48, 160, y0 + i * 12, l, v, 8, b, 8.5 if i == 0 else 8)
    d.barcode(p["pid"], 410, 124, 80, 24)
    d.T(310, y0 + 22, "Patient No.", 8); d.T(405, y0 + 22, ":", 8); d.T(412, y0 + 22, p["pid"], 8, "VB")
    d.T(310, y0 + 34, "Sample No.", 8); d.T(405, y0 + 34, ":", 8); d.T(412, y0 + 34, D["sample"], 8, "VB")
    d.T(310, y0 + 46, "Date & Time of Analysis", 8); d.T(405, y0 + 46, ":", 8); d.T(412, y0 + 46, bs_str(dt + timedelta(hours=2)), 8)
    top = 212
    cols = dict(test=48, indent=52, value=236, unit=305, ref=360, method=450)
    for k, x in (("Test", 50), ("Result", 236), ("Unit", 305), ("Ref. Range", 360), ("Method", 450)): d.T(x, top + 10, k, 8.5, "VB")
    d.L(44, top + 14, 502, top + 14, .5)
    for r in D["rows"]:
        if r["k"] == "test": r["indent"] = r["indent"] or True
    yb = draw_rows(d, D["rows"], top + 20, cols, 44, 502, 15, 8.5, True, title_size=10.5, hand=None if D.get("source") == "csv" else "circle", rng=rng)
    d.R(44, top, 458, yb - top + 6, stroke=black, lw=.9)
    xs = [58, 150, 248, 345]
    for i, (nm, ttl) in enumerate(D["sigs"]):
        d.L(xs[i], 690, xs[i] + 92, 690, .6)
        if i < 2: d.scribble(xs[i] + 8, 664, 70, 24, rng)
        d.T(xs[i] + 2, 701, nm, 6, "V"); d.T(xs[i] + 2, 709, ttl, 6, "V"); d.T(xs[i] + 2, 717, f"Reg. No: {rng.choice('AB')}-{digits(rng, 4)}", 6, "V")
    d.T(58, 745, "Entered By", 6.5, "VB"); d.T(105, 745, f":  {D['enteredby']}", 6.5, "VB")
    d.T(58, 757, "The Laboratory report must be interpreted in conjunction with the clinical profile of the patient by a clinician.", 6.5)
    d.T(400, 777, "Page : 1     of 1", 6.5)


# =============================================================================
# 3) CLINICAL CHEMISTRY (single test panel, two signatories)
# =============================================================================
def gen_clinical(rng):
    p = gen_patient(rng); dt = rand_dt(rng); a, b = inst_names(rng)
    specs = rng.sample([SP[k] for k in ("cpk", "ldh", "amy", "ca", "ast", "alt", "alp", "bil")], rng.randint(1, 4))
    rows = [dict(k="title", name="CLINICAL CHEMISTRY")]
    for s in specs:
        r = mk_test(rng, s); rows += [dict(k="group", name=s["name"].split(" (")[0].upper()), dict(r, indent=True)]
    return dict(template="clinical", patient=p, dt=dt, rows=rows, sample=f"{ad_to_bs(dt.date())[0]}-N{digits(rng, 5)}",
                inst=dict(name=f"{a.upper()} HOSPITAL & RESEARCH CENTRE", box=f"GPO Box No. {digits(rng, 5)}, Kathmandu, Nepal", phone=f"Phone : 4{digits(rng, 6)}, Fax : 977-1-4{digits(rng, 6)}",
                          mail=f"E-mail : info@{a.lower()}hospital.example", web=f"www.{a.lower()}hospital.example"),
                refby=doc_name(rng).upper(), tech=(rng.choice(F_NAMES) + " " + rng.choice(SURN), "Medical Laboratory Technician"), path=(doc_name(rng), "Consultant Pathologist"), addr=rng.choice(["GOKARNESHWOR", "KALANKI", "BANESHWOR", "BOUDHA", "PATAN"]))


def draw_clinical(d, D, rng):
    p, I, dt = D["patient"], D["inst"], D["dt"]
    for i, s in enumerate([I["box"], I["phone"], I["mail"], I["web"]]): d.T(500, 26 + i * 9, s, 7, "V", black, "r")
    d.fit(34, 84, I["name"], "VB", 17, 300, RED); d.T(340, 84, "PRIVATE LIMITED", 7.5, "VB", RED)
    d.grad(220, 88, 140, 6, ORANGE, RED, vertical=False)
    d.T(34, 104, "A Multispeciality Hospital", 7.5, "VBI", GREEN); d.T(34, 120, "Department of Pathology", 11, "VB", HexColor("#222222"))
    y0 = 146
    for i, (l, v, b) in enumerate([("Name", f"{p['name']}", True), ("Patient Type/Ward/Bed", "OPD / /", False), ("Age/Gender", f"{p['age']} Y / {p['sex']}", False), ("Referred By", D["refby"], False), ("Sample Registered Date", f"{bs_str(dt, '/', False)} - {dt.strftime('%Y/%m/%d %H:%M:%S')}", False)]):
        kv(d, 34, 150, y0 + i * 12.5, l, v, 8, b)
    d.barcode(p["pid"], 372, 126, 70, 16)
    for i, (l, v, b) in enumerate([("Hospital No.", p["pid"], True), ("Sample No", D["sample"], True), ("Address", D["addr"], False), ("Date & Time of Report", bs_str(dt + timedelta(hours=1)), False)]):
        d.T(300, y0 + 9 + i * 12.5, l, 8); d.T(398, y0 + 9 + i * 12.5, ":", 8); d.T(405, y0 + 9 + i * 12.5, v, 8, "VB" if b else "V")
    top = 224
    cols = dict(test=60, indent=76, value=172, unit=228, ref=272, flag=380, method=402)
    if D.get("source") == "csv": cols.update(value=222, unit=284, ref=328, flag=422, method=448)   # wider Test column: CSV labels are long
    for k, x in (("Test", 90), ("Result", cols["value"]), ("Unit", cols["unit"]), ("Reference Range", cols["ref"]), ("Flag", cols["flag"]), ("Method", cols["method"])): d.T(x, top + 10, k, 8, "VB")
    d.L(36, top + 14, 505, top + 14, .5)
    yb = draw_rows(d, D["rows"], top + 18, cols, 36, 505, 13, 8, True, "flag", title_size=10)
    d.R(36, top, 469, yb - top + 3, stroke=black, lw=.9)
    ys = yb + 40
    d.scribble(150, ys - 3, 60, 24, rng); d.scribble(370, ys - 8, 50, 28, rng)
    for cx, (nm, ttl) in ((190, D["tech"]), (396, D["path"])):
        d.T(cx, ys + 30, "-" * 38, 7, "V", black, "c", rec=False)
        d.T(cx, ys + 41, nm, 7, "VB", black, "c"); d.T(cx, ys + 50, ttl, 7, "VB", black, "c"); d.T(cx, ys + 59, f"Reg No: {digits(rng, 4)}", 7, "VB", black, "c")
    d.T(505, 800, "Page 1 of 1", 7.5, "VBI", black, "r")


# =============================================================================
# 4/5) DIAGNOSTIC-CENTRE : IMMUNOLOGY and SPECIAL TEST (shared header / footer)
# =============================================================================
IMMUNO = {
    "Anti-cyclic citrullinated peptide (anti CCP)": ((0.5, 17.0), 2, "U/mL", ["< 17.0: Negative", "\u2265 17.0: Positive"], "CLIA",
        ["Anti-CCP antibodies are produced by the immune system and are directed against citrullinated peptides found in joint tissue.",
         "A raised level supports the diagnosis of rheumatoid arthritis and is usually interpreted together with symptoms and other tests.",
         "A negative result does not exclude the disease; some patients become positive later in its course."]),
    "Rheumatoid Factor (RF)": ((2, 14), 1, "IU/mL", ["< 14.0: Negative", "\u2265 14.0: Positive"], "Nephelometry",
        ["Rheumatoid factor is an antibody directed against the body's own immunoglobulins.",
         "It is raised in many patients with rheumatoid arthritis but may also be present in other autoimmune and infectious conditions.",
         "Results should always be correlated clinically."]),
    "C-Reactive Protein (CRP)": ((0.5, 6), 1, "mg/L", ["< 6.0: Normal", "\u2265 6.0: Raised"], "Immunoturbidimetry",
        ["C-reactive protein is an acute-phase protein made by the liver in response to inflammation.",
         "Raised levels may indicate infection, tissue injury or chronic inflammatory disease.",
         "The test is non-specific; the cause must be identified by clinical assessment."]),
}


def gen_diag_common(rng, tmpl):
    p = gen_patient(rng); dt = rand_dt(rng); a, b = inst_names(rng)
    return dict(template=tmpl, patient=p, dt=dt, sample=digits(rng, 4), inst=dict(a=a, b=b, name1=a, name2="Diagnostic", tag="Precision in every test", phone=f"+977 01-4{digits(rng, 6)}/21/30",
                addr=f"{rng.choice(['Sinamangal', 'Baneshwor', 'Lazimpat', 'Kupondole'])}-{rng.randint(1, 9)}, Kathmandu, Nepal", web=f"www.{a.lower()}diagnostic.example", mail=f"info@{a.lower()}diagnostic.example"),
        sigs=[(doc_name(rng, "").strip() + "", "BSC MLT", f"Reg No.: A-{digits(rng, 4)} MLT"), (doc_name(rng, ""), "Lab Incharge", f"Reg No.: A-{digits(rng, 3)}"), (doc_name(rng), "Consultant Pathologist", f"MD, Reg No. {digits(rng, 5)}")])


def gen_immuno(rng):
    D = gen_diag_common(rng, "immuno")
    name = rng.choice(list(IMMUNO)); (lo, hi), nd, unit, ref, meth, para = IMMUNO[name]
    v = round(rng.uniform(lo, hi * (1.8 if rng.random() < .2 else 1)), nd)
    D.update(test=dict(name=name, value=f"{v:.{nd}f}", unit=unit, ref=ref, method=meth), para=para, req=f"{D['inst']['a']} Hospital & Research Center Pvt. Ltd.", refby="Self")
    return D


def gen_special(rng):
    D = gen_diag_common(rng, "special")
    tit = rng.choice(["1:40", "1:80", "1:160", "1:320", "1:640"])
    D.update(titer=tit, result="NEGATIVE" if int(tit.split(":")[1]) <= 160 else "POSITIVE", sample=f"{ad_to_bs(D['dt'].date())[0]}-N{digits(rng, 5)}", refby=f"{D['inst']['a'].upper()} DIAGNOSTIC CENTRE")
    return D


def diag_header(d, I, y_end=125):
    swoosh(d, 150, 26, 50)
    d.T(50, 60, I["name1"], 26, "VB", NAVY); d.T(50, 86, I["name2"], 26, "VB", NAVY)
    d.T(50, 99, I["tag"].upper(), 6, "V", GREEN); d.T(50, 117, "Accredited Pathology Laboratory", 11, "VB", NAVY)
    d.L(36, y_end, 540, y_end, 1.2, NAVY)
    d.C(500, 62, 26, stroke=GREY, lw=.8); d.C(500, 62, 20, stroke=GREY, lw=.5)
    d.T(500, 60, "QUALITY", 6.5, "VB", GREY, "c"); d.T(500, 68, "CERTIFIED", 6.5, "VB", GREY, "c"); d.T(500, 98, "Medical Laboratory", 5.5, "V", GREY, "c")
    d.R(522, 140, 17, 92, fill=GREEN); d.vtext(533, 186, "DIAGNOSTICS REPORT", 7, "VB", white, 90)


def diag_footer(d, I, qr_val, show_page=True):
    d.R(0, 790, W, 52, fill=BLUE_BAND); d.R(0, 786, W, 4, fill=GREEN); d.markcolor = HexColor("#C9D8EE")
    d.T(48, 814, I["phone"], 8, "V", white); d.T(222, 810, I["addr"], 8, "V", white); d.T(222, 822, I["web"], 8, "V", white); d.T(410, 814, I["mail"], 8, "V", white)
    if show_page: d.T(530, 832, "Page 1 of 1", 6.5, "V", white, "r")


def draw_immuno(d, D, rng):
    p, I, dt, T = D["patient"], D["inst"], D["dt"], D["test"]
    diag_header(d, I)
    for i, (l, v) in enumerate([("Sample ID:", D["sample"]), ("Patient's Name:", f"{p['title']} {p['first'].title()} {p['last'].title()}".strip()), ("Age / Gender:", f"{p['age']} yrs / {'Female' if p['sex'] == 'F' else 'Male'}"),
                                ("P.P/ Ctz. No:", ""), ("Referred By:", D["refby"]), ("Requestor:", D["req"]), ("Contact No.:", p["phone"]), ("Email ID:", f"report@{I['a'].lower()}hospital.example")]):
        d.T(72, 152 + i * 12.3, l, 8); d.T(140, 152 + i * 12.3, v, 8, "VB" if i == 1 else "V")
    d.T(240, 152, "Patient ID:", 8); d.T(295, 152, p["pid"] if D.get("source") == "csv" else "N" + digits(rng, 6), 8)
    d.barcode(D["sample"], 430, 146, 70, 22)
    for i, l in enumerate(["Date Of Collection:", "Date Of Registration:", "Date Of Reporting:"]):
        tt = dt + timedelta(hours=2 * i)
        d.T(318, 195 + i * 24, l, 8); d.T(428, 193 + i * 24, tt.strftime("%d %b %Y %H:%M:%S"), 8); d.T(428, 203 + i * 24, bs_str(tt, "/", False) + " BS", 8)
    d.grad(58, 265, 482, 15, HexColor("#555555"), HexColor("#9a9a9a")); d.T(299, 276.5, "Immunology/Serology", 10, "VB", white, "c")
    for k, x in (("Test", 76), ("Result", 245), ("Reference", 312), ("Unit", 410), ("Method", 448)): d.T(x, 298, k, 8, "VB")
    nm1, nm2 = T["name"], ""
    if stringWidth(nm1, "VB", 8) > 160:
        parts = nm1.split(); k = len(parts)
        while stringWidth(" ".join(parts[:k]), "VB", 8) > 160: k -= 1
        nm1, nm2 = " ".join(parts[:k]), " ".join(parts[k:])
    d.T(76, 314, nm1, 8, "VB")
    if nm2: d.T(76, 326, nm2, 8, "VB")
    d.T(245, 316, T["value"], 8.5); d.T(312, 314, T["ref"][0], 8.5); d.T(312, 326, T["ref"][1], 8.5); d.T(410, 314, T["unit"], 8); d.T(448, 314, T["method"], 8)
    y = 354
    for para in D["para"]:
        words, line = para.split(), ""
        for wd in words:
            if stringWidth(line + " " + wd, "V", 6.8) > 360: d.T(85, y, line.strip(), 6.8); y += 10.4; line = wd
            else: line += " " + wd
        d.T(85, y, line.strip(), 6.8); y += 12
    d.T(300, y + 14, "*** End of Report ***", 8, "V", black, "c")
    d.qr(f"https://reports.example/{D['sample']}", 62, 718, 56)
    for i, x in enumerate((125, 262, 400)):
        nm, ttl, reg = D["sigs"][i]
        d.scribble(x + 10, 700, 70, 22, rng); d.L(x, 733, x + 125, 733, .8)
        d.T(x + 6, 746, nm, 7.5); d.T(x + 6, 757, ttl, 7.5); d.T(x + 6, 768, reg, 7.5)
    d.T(70, 782, "Scan QR-Code to view report online", 5.5, "VI", GREY)
    diag_footer(d, I, "")


def draw_special(d, D, rng):
    p, I, dt = D["patient"], D["inst"], D["dt"]
    diag_header(d, I)
    d.R(40, 150, 478, 76, stroke=black, lw=.8)
    for i, (l, v) in enumerate([("Name", p["name"]), ("Address", "KATHMANDU - KATHMANDU"), ("Phone No.", "0"), ("Referred By", D["refby"]), ("Lab No", D["sample"]), ("Passport No", ""), ("Patient Type", "OPD")]):
        d.T(46, 160 + i * 9.6, l, 6.8); d.T(100, 160 + i * 9.6, ":", 6.8); d.T(107, 160 + i * 9.6, v, 6.8, "VB")
    d.barcode(p["pid"], 372, 154, 70, 18)
    for i, (l, v) in enumerate([("Patient No.", p["pid"]), ("Age/Gender", f"{p['age']} Y / {p['sex']}"), ("Collected Date", f"{dt.strftime('%Y/%m/%d')} AD | {bs_str(dt)}"), ("Reporting Date", f"{dt.strftime('%Y/%m/%d')} AD | {bs_str(dt + timedelta(hours=5))}")]):
        d.T(322, 188 + i * 10, l, 6.5); d.T(378, 188 + i * 10, ":", 6.5); d.T(383, 188 + i * 10, v, 6.5, "VB" if i < 2 else "V")
    d.T(272, 262, "SPECIAL TEST", 9.5, "VB", black, "c"); d.L(58, 266, 540, 266, .8)
    for k, x in (("Test", 62), ("Result", 205), ("Unit", 322), ("Reference Range", 372), ("Method", 460)): d.T(x, 280, k, 8, "VB")
    d.L(58, 284, 540, 284, .8)
    d.T(62, 296, "ANTINUCLEAR ANTIBODY TEST", 7.5, "VB"); d.T(70, 306, "(ANTI-CELL ANTIBODY)", 7.5, "VB")
    d.T(64, 322, "Method:Indirect Immunofluorescence", 7, "VB"); d.T(68, 332, "Assay on HEP-2 cell,Serum", 7, "VB")
    d.T(62, 350, "SCREENING TITER", 7); d.T(208, 349, D["titer"], 8)
    d.T(64, 372, "RESULT", 7); d.T(208, 371, D["result"], 8, "VB" if D["result"] == "POSITIVE" else "V")
    d.T(64, 393, "REFERENCE RANGE", 7); d.T(210, 393, "-", 7); d.T(372, 392, "\u2264 1:160", 8)
    d.L(58, 398, 540, 398, .8)
    d.R(66, 410, 468, 150, stroke=black, lw=.8); d.R(88, 405, 34, 11, fill=white); d.T(90, 413, "NOTE", 8, "VB")
    notes = ["Note:", "1. Immunofluorescence microscopy using human cellular extracts such as HEp-2 cells is a sensitive screening test for serum antibodies.",
             "2. Test conducted on Serum.", "3. Patterns are reported as per the international consensus on ANA patterns.", "",
             "Comments:", "Antinuclear antibodies are autoantibodies directed against constituents of the cell nucleus. They occur with high frequency in connective tissue "
             "disorders. As positive results are also seen in healthy individuals, they are not by themselves diagnostic and must be correlated with other laboratory and clinical findings."]
    y = 428
    for para in notes:
        if not para: y += 6; continue
        line = ""
        for wd in para.split():
            if stringWidth((line + " " + wd).strip(), "V", 7.2) > 440: d.T(72, y, line, 7.2); y += 11.5; line = wd
            else: line = (line + " " + wd).strip()
        d.T(72, y, line, 7.2, "VB" if line.endswith(":") else "V"); y += 11.5
    d.qr(f"https://reports.example/{D['sample']}", 90, 600, 54)
    d.scribble(405, 585, 70, 26, rng); d.L(385, 628, 500, 628, .6, black, (2, 2))
    for i, s in enumerate(["Authorized by", D["sigs"][2][0].replace("Dr.", "Prof. Dr."), "MBBS, MD", "Consultant Pathologist", f"Reg. No: {digits(rng, 4)}"]):
        d.T(442, 638 + i * 9.5, s, 6.5, "V", black, "c")
    d.T(300, 700, "---------- End of Report ----------", 6.5, "V", black, "c")
    d.T(160, 710, f"Printed Date/Time :{dt.strftime('%Y/%m/%d')} AD - {bs_str(dt + timedelta(hours=6))} BS (This report is electronically generated.)", 6.3, "V", black)
    diag_footer(d, I, "", False)


# =============================================================================
# 6) AUDIOGRAM
# =============================================================================
FREQ = [125, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 6000, 8000]
FL = ["125", "250", "500", "750", "1k", "1.5k", "2k", "3k", "4k", "6k", "8k"]
AC_F, BC_F = [250, 500, 1000, 2000, 4000, 8000], [500, 1000, 2000, 4000]


def gen_ear(rng, kind):
    base = dict(normal=(5, 20), mild=(20, 35), moderate=(40, 60), severe=(65, 90), profound=(95, 112))[kind]
    slope = rng.randint(0, 6) if kind != "normal" else rng.randint(0, 3)
    ac = {}
    for i, f in enumerate(AC_F):
        v = rng.randint(*base) + i * slope; v = int(round(v / 5) * 5)
        ac[f] = None if (v >= 120 or (kind == "profound" and i >= 3 and rng.random() < .8)) else min(v, 115)
    bc = {}
    for f in BC_F:
        a = ac.get(f); bc[f] = None if a is None and rng.random() < .5 else max(-5, int(round(((a if a is not None else 100) - rng.choice([0, 5, 10, 10, 20])) / 5) * 5))
    masked = kind in ("severe", "profound")
    ac_m = {f: (max(0, v - rng.choice([20, 30, 40])) if v is not None else None) for f, v in ac.items()} if masked else {}
    bc_m = {f: (None if v is None else max(0, v - 10)) for f, v in bc.items()} if masked else {}
    return dict(kind=kind, ac=ac, bc=bc, ac_m=ac_m, bc_m=bc_m, masked=masked)


def pta(ear, key):
    vals = [(ear[key].get(f) if ear[key].get(f) is not None else 120) for f in BC_F]
    return round(sum(vals) / len(vals), 1)


def hl_text(v):
    return "NORMAL HEARING" if v <= 15 else "MINIMAL HEARING LOSS" if v <= 25 else "MILD HEARING LOSS" if v <= 40 else "MODERATE HEARING LOSS" if v <= 55 else \
        "MODERATELY SEVERE HEARING LOSS" if v <= 70 else "SEVERE HEARING LOSS" if v <= 90 else "PROFOUND HEARING LOSS"


def gen_audiogram(rng):
    p = gen_patient(rng); dt = rand_dt(rng); a, b = inst_names(rng)
    kinds = ["normal", "mild", "moderate", "severe", "profound"]
    r_kind = rng.choice(kinds[:4]); l_kind = rng.choice(kinds) if rng.random() < .6 else r_kind
    R_, L_ = gen_ear(rng, r_kind), gen_ear(rng, l_kind)
    dob = date(dt.year - p["age"], rng.randint(1, 12), rng.randint(1, 28))
    return dict(template="audiogram", patient=p, dt=dt, R=R_, L=L_, dob=dob, hosp=f"{a} {b}", pta=dict(R_ac=pta(R_, "ac"), L_ac=pta(L_, "ac"), R_bc=pta(R_, "bc"), L_bc=pta(L_, "bc")),
                comment=rng.choice([["ENT REVIEW", "F/U"], ["HEARING AID EVALUATION"], ["REPEAT AUDIOMETRY AFTER 3 MONTHS"]]), phone=f"01-5{digits(rng, 6)}, 5{digits(rng, 6)}",
                addr=f"{rng.choice(['Adwait Marg', 'Ring Road', 'Maitighar'])}, {rng.choice(['Bagbazar', 'Putalisadak', 'Baneshwor'])}, Kathmandu-28", signer=doc_name(rng, "").strip())


def marker(d, kind, x, y, col, nr=False):
    s = 3.1
    if kind == "O": d.C(x, y, s, stroke=col, lw=.9)
    elif kind == "X": d.L(x - s, y - s, x + s, y + s, .9, col); d.L(x - s, y + s, x + s, y - s, .9, col)
    elif kind == "SQ": d.R(x - s, y - s, 2 * s, 2 * s, stroke=col, lw=.9)
    elif kind == "TRI": d.P([(x - s, y + s), (x + s, y + s), (x, y - s)], stroke=col, lw=.9)
    elif kind == "<": d.P([(x + 2.4, y - 3.2), (x - 1.8, y), (x + 2.4, y + 3.2)], stroke=col, lw=.9, close=False)
    elif kind == "]": d.P([(x - 2, y - 3.5), (x + 2, y - 3.5), (x + 2, y + 3.5), (x - 2, y + 3.5)], stroke=col, lw=.9, close=False)
    if nr: d.L(x + s, y + s, x + s + 4, y + s + 4, .9, col)


def legend_symbol(d, code, x, y, col):
    s_ = 2.6
    if code in ("O", "X", "TRI", "SQ", "<", "]"): marker(d, code, x, y, col)
    elif code == "OX": d.C(x, y, s_, stroke=col, lw=.8); d.L(x - 1.8, y - 1.8, x + 1.8, y + 1.8, .7, col); d.L(x - 1.8, y + 1.8, x + 1.8, y - 1.8, .7, col)
    elif code == ">": d.P([(x - 1.5, y - 3.2), (x + 2.6, y), (x - 1.5, y + 3.2)], stroke=col, lw=.9, close=False)
    elif code == "[": d.P([(x + 2, y - 3.5), (x - 2, y - 3.5), (x - 2, y + 3.5), (x + 2, y + 3.5)], stroke=col, lw=.9, close=False)
    elif code == "FFR": d.P([(x + s_, y - s_), (x - s_, y), (x + s_, y + s_)], fill=col)
    elif code == "FFL": d.P([(x - s_, y - s_), (x + s_, y), (x - s_, y + s_)], fill=col)
    elif code == "FFB": d.P([(x - s_, y - s_), (x, y), (x - s_, y + s_)], stroke=col, lw=.8); d.P([(x + s_, y - s_), (x, y), (x + s_, y + s_)], stroke=col, lw=.8)
    elif code: d.T(x - 2, y + 2.2, code, 6, "V", col)


def chart(d, x, y, w, h, ear, side, col):
    d.T(x + 5, y - 20, "Right" if side == "R" else "Left", 8.5, "V"); d.T(x + 28, y - 8, "dB HL", 6, "V")
    px = lambda i: x + w * i / (len(FREQ) - 1); py = lambda db: y + (db + 10) / 130 * h
    for db in range(-10, 121, 10):
        d.L(x, py(db), x + w, py(db), .45, HexColor("#888888")); d.T(x - 4, py(db) + 2, str(db), 5.8, "V", black, "r")
    for i in range(len(FREQ)):
        d.L(px(i), y, px(i), y + h, 1.1 if i == 4 else .4, black if i == 4 else HexColor("#888888"), None if i == 4 else (1, 1.5))
        d.T(px(i) - (4 if side == "R" else 3), y + h + 9 + (6 if i % 2 else 0), FL[i], 5.8, "V")
    d.L(x, py(0), x + w, py(0), .9); d.T(x + w + 2, y + h - 5, "Hz", 6, "V")
    ac_sym = ("TRI" if side == "R" else "SQ") if ear["masked"] else ("O" if side == "R" else "X")
    bc_sym = "<" if side == "R" else "]"
    src = ear["ac_m"] if ear["masked"] and False else ear["ac"]
    pts = [(px(FREQ.index(f)), py(v)) for f, v in src.items() if v is not None]
    for a_, b_ in zip(pts, pts[1:]): d.L(a_[0], a_[1], b_[0], b_[1], .9, col)
    for f, v in src.items():
        if v is None: marker(d, ac_sym, px(FREQ.index(f)), py(118), col, True)
        else: marker(d, ac_sym, px(FREQ.index(f)), py(v), col)
    for f, v in ear["bc"].items():
        if v is not None: marker(d, bc_sym, px(FREQ.index(f)) + (-4 if side == "R" else 4), py(v), col)
    # table below
    ty = y + h + 28
    for i, lab in enumerate(FL): d.T(px(i) - 3 + (0 if side == "R" else 0), ty, lab, 5.4, "V")
    rows = [(f"AC {side}", "Thr.", ear["ac"]), (f"AC {side}", "Mask.", ear["ac_m"]), (f"BC {side}", "Thr.", ear["bc"]), (f"BC {side}", "Mask.", ear["bc_m"])]
    for j, (a_, b_, dct) in enumerate(rows):
        yy = ty + 10 + j * 8.5; d.T(x - 33, yy, a_, 5.4); d.T(x - 14, yy, b_, 5.4)
        for f, v in dct.items(): d.T(px(FREQ.index(f)) - 3, yy, "N.R." if v is None else str(v), 5.4)


def draw_audiogram(d, D, rng):
    p, dt = D["patient"], D["dt"]
    swoosh(d, 56, 30, 44); fs = 16; first = D["hosp"].split()[0]
    w1 = stringWidth(first, "VB", fs); d.T(112, 52, first, fs, "VB", HexColor("#1B2A50"))
    d.T(112 + w1 + 4, 52, "ENT", fs, "VB", GREEN); d.T(112 + w1 + 8 + stringWidth("ENT", "VB", fs), 52, "Hospital Pvt. Ltd.", fs, "VB", HexColor("#1B2A50"))
    d.R(112, 60, 272, 13, fill=GREEN); d.T(248, 70, "EAR, NOSE, THROAT HOSPITAL PVT. LTD.", 8.5, "VB", white, "c")
    for i, s in enumerate([D["addr"], f"Tel.: {D['phone']}", f"E-mail : info@{D['hosp'].split()[0].lower()}ent.example"]): d.T(112, 83 + i * 8.5, s, 6.3, "VB" if i == 1 else "V")
    d.R(400, 28, 90, 66, fill=HexColor("#DDE6EE"), stroke=GREY, lw=.5)
    d.R(410, 36, 38, 24, fill=HexColor("#3A4A5A")); d.C(470, 52, 8, fill=HexColor("#E0B89A")); d.R(458, 60, 26, 24, fill=white, stroke=GREY, lw=.4)
    d.R(500, 28, 15, 76, fill=HexColor("#E8452C"), r=4); d.vtext(510, 66, "AUDIOGRAM REPORT", 6.5, "VB", white, 90)
    d.T(34, 122, f"PATIENT: {p['title'].replace('.', '').upper()} {p['name']} - {D['dob'].strftime('%d/%m/%Y')} ({p['age']} years) - {p['sex']}", 8, "VB")
    d.L(28, 127, 520, 127, 1.4, GREEN)
    d.T(285, 140, "PATIENT DATA", 7.5, "VB", black, "c")
    d.T(34, 160, f"1: Pure tone audiometry - {dt.month}/{dt.day}/{dt.year} {dt.strftime('%I:%M %p').lstrip('0')} - {D['hosp']} Hospital Pvt Ltd", 7.5, "VB")
    chart(d, 56, 196, 150, 182, D["R"], "R", HexColor("#D9453B")); chart(d, 340, 196, 150, 182, D["L"], "L", HexColor("#2B66B8"))
    # legend (symbols are drawn, not typed)
    RC, LC = HexColor("#D9453B"), HexColor("#2B66B8")
    d.T(236, 196, "R", 6, "V"); d.T(262, 196, "L", 6, "V"); d.T(286, 196, "BIL", 6, "V")
    leg = [("AC", "O", "X", "OX"), ("AC Mask.", "TRI", "SQ", "TRI"), ("UCL", "U", "U", ""), ("BC", "<", ">", ""), ("BC Mask.", "[", "]", ""), ("FF", "FFR", "FFL", "FFB"), ("FF Mask.", "S", "S", "S"), ("FF Aided", "A", "A", "A")]
    for i, (a_, r_, l_, b_) in enumerate(leg):
        yy = 208 + i * 9.5; d.T(214, yy, a_, 5.8)
        for xx, code, col in ((238, r_, RC), (264, l_, LC), (290, b_, black)): legend_symbol(d, code, xx, yy - 2, col)
    d.T(236, 296, "Pure tones average", 6); d.T(240, 308, "R", 6); d.T(268, 308, "L", 6)
    for i, (a_, r_, l_) in enumerate([("AC", D["pta"]["R_ac"], D["pta"]["L_ac"]), ("BC", D["pta"]["R_bc"], D["pta"]["L_bc"])]):
        d.T(216, 318 + i * 9, a_, 6); d.T(240, 318 + i * 9, str(r_), 6); d.T(268, 318 + i * 9, str(l_), 6)
    d.T(214, 344, "Freq. [Hz]: 500, 1k, 2k, 4k", 5.8)
    d.T(34, 468, f"2: Session data - {dt.month}/{dt.day}/{dt.year} {dt.strftime('%I:%M %p').lstrip('0')} - {D['hosp']} Hospital Pvt Ltd", 7.5, "VB")
    d.T(320, 480, "GENERAL INFO", 7, "V")
    d.T(100, 508, "DIAGNOSIS", 7); d.T(150, 508, "PTA", 7); d.T(150, 518, f"RIGHT EAR- {hl_text(D['pta']['R_ac'])}", 7); d.T(150, 527, f"LEFT EAR- {hl_text(D['pta']['L_ac'])}", 7)
    d.T(295, 552, "COMMENT", 7.5, "VB", black, "c"); d.T(100, 578, "COMMENT", 7); 
    for i, s in enumerate(D["comment"]): d.T(150, 578 + i * 10, s, 7)
    d.scribble(385, 612, 55, 38, rng, black, 1.1)
    for i, s in enumerate([D["signer"], "Consultant Audiologist and SLP", f"Reg. No. A-{digits(rng, 2)} Sp&Hg"]): d.T(425, 664 + i * 9, s, 7.5 if i == 0 else 7, "VB" if i == 0 else "V", HexColor("#2B66B8"), "c")
    d.P([(190, 714), (208, 696), (362, 696), (380, 714)], fill=GREEN); d.T(285, 709, "OUR SERVICES", 11, "VB", white, "c", rec=True)
    d.R(40, 714, 480, 72, fill=BLUE_BAND)
    cols = [["Ear, Nose, Throat & Neck Clinic", "Speech & Hearing Clinic", "Vertigo & Tinnitus Clinic", "Surgeries of Ear, Nose, Throat"],
            ["General Health Clinic", "Thyroid & Diabetes Clinic", "Ortho & Spine Clinic", "Headache & Neuro Clinic"], ["Physiotherapy", "USG", "X-rays", "Pathology Lab"]]
    for ci, xs in enumerate((58, 244, 430)):
        for i, s in enumerate(cols[ci]): d.T(xs, 730 + i * 13, "*  " + s, 7, "V", white)


# =============================================================================
# CSV MODE  (reads the same Mathernal_Risk.csv as lab_report_generator.py)
# =============================================================================
CSV_TYPES = ["municipal", "medicare", "clinical"]          # layouts that can show CSV test values
CSV_TITLE = dict(municipal="Bio-Chemistry Report", medicare="BIOCHEMISTRY REPORT", clinical="CLINICAL CHEMISTRY")
# plausible ranges -> only used to LOG suspicious CSV rows (the report is still made)
PLAUSIBLE = {"age": (10, 60), "temp": (90, 110), "hr": (30, 220), "sys": (60, 260), "dia": (30, 150), "bmi": (12, 50)}


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


def safe(s): return re.sub(r"[^A-Za-z0-9_-]+", "_", str(s)).strip("_") or "patient"


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


def csv_warnings(row):
    out = []
    for k, (lo, hi) in PLAUSIBLE.items():
        v = to_float(row.get(k))
        if v is not None and not (lo <= v <= hi): out.append(f"{k}={fnum(v, 2)} outside plausible range {lo}-{hi}")
    if to_float(row.get("age")) is None: out.append("age missing or not a number (random age used)")
    return out


def _ct(name, value, unit="", ref="", flag="", indent=True, bold=False):
    return dict(k="test", name=name, value=value, unit=unit, ref=ref, method="", indent=indent, flag=flag, lo=None, hi=None, bold=bold)


def _rng_flag(v, lo, hi): return "L" if v < lo else "H" if v > hi else ""


def csv_result_rows(r):
    """Rows of the table, values exactly as in the CSV (same content as lab_report_generator.py)."""
    rows = []
    h_txt, g_txt = r.get("hba1c", ""), r.get("glucose", "")
    h = to_float(h_txt); pct = h if (h is not None and h <= 20) else None      # % only if it looks like a %
    if h_txt:
        rows.append(dict(k="group", name="HBA1C (GLYCOSYLATED HEMOGLOBIN)"))
        rows.append(_ct("HBA1C", h_txt, "%" if pct is not None else ""))
        if pct is not None: rows.append(_ct("ESTIMATED AVERAGE GLUCOSE", f"{28.7 * pct - 46.7:.2f}", "mg/dL"))
    if g_txt: rows.append(_ct("FASTING BLOOD GLUCOSE", g_txt, "mg/dL", indent=False))
    temp, hr, sy, di, bmi = (to_float(r.get(k)) for k in ("temp", "hr", "sys", "dia", "bmi"))
    vit = []
    if temp is not None: vit.append(_ct("BODY TEMPERATURE", fnum(temp, 1), "\xb0F", "97.0 - 99.0", _rng_flag(temp, 97, 99)))
    if hr is not None: vit.append(_ct("HEART RATE", fnum(hr, 0), "bpm", "60 - 100", _rng_flag(hr, 60, 100)))
    if sy is not None and di is not None:
        vit.append(_ct("BLOOD PRESSURE", f"{fnum(sy, 0)} / {fnum(di, 0)}", "mmHg", "< 140 / 90", "H" if (sy >= 140 or di >= 90) else ""))
    if bmi is not None: vit.append(_ct("BODY MASS INDEX (BMI)", fnum(bmi, 1), "kg/m\xb2", "18.5 - 24.9", _rng_flag(bmi, 18.5, 24.9)))
    if vit: rows.append(dict(k="group", name="MATERNAL HEALTH PARAMETERS")); rows += vit
    return rows


def csv_report(rng, tid, row, opts):
    """Random layout details (hospital, signers, dates, sample no.) + patient / values from the CSV row."""
    D = TEMPLATES[tid][0](rng)
    p = D["patient"]
    sex = (opts.get("sex") or "F").upper()[:1]
    name = row.get("name", "").strip()
    age = to_float(row.get("age"))
    p.update(title=opts.get("title") or ("Mr." if sex == "M" else "Ms."), first=name.title(), last="", name=name.upper(),
             sex=sex, months=0, pid=row.get("reg") or p["pid"])
    if age is not None: p["age"] = int(round(age))
    if opts.get("referred_by"): D["refby"] = opts["referred_by"]
    D["source"] = "csv"; D["csv_row"] = dict(row)
    if tid in CSV_TYPES:
        D["rows"] = [dict(k="title", name=CSV_TITLE[tid])] + csv_result_rows(row)
    return D


# =============================================================================
# registry, manual entry, rendering
# =============================================================================
TEMPLATES = dict(municipal=(gen_municipal, draw_municipal), medicare=(gen_medicare, draw_medicare), clinical=(gen_clinical, draw_clinical),
                 immuno=(gen_immuno, draw_immuno), special=(gen_special, draw_special), audiogram=(gen_audiogram, draw_audiogram))


def build_pdf(D, rng):
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); d = Doc(c)
    DRAW = TEMPLATES[D["template"]][1]
    DRAW(d, D, rng); d.mark(); c.showPage(); c.save()
    return buf.getvalue(), d.words


def render_png(pdf, dpi):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(pdf)[0].render(scale=dpi / 72).to_pil().convert("RGB")


def augment(img, words, rng):
    """photo-style: rotated paper on carpet, shadow gradient, blur, noise. Word boxes are transformed too."""
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter
    Wd, Ht = img.size
    sc = rng.uniform(.62, .8); pw, ph = int(Wd * sc), int(Ht * sc); ang = rng.uniform(-4, 4)
    paper = ImageEnhance.Brightness(img.resize((pw, ph), Image.LANCZOS)).enhance(rng.uniform(.82, 1.0))
    rot = paper.convert("RGBA").rotate(ang, expand=True, resample=Image.BICUBIC); rw, rh = rot.size
    nprng = np.random.default_rng(rng.randint(0, 10 ** 9))
    ribs = np.sin(np.arange(Ht)[:, None] / rng.uniform(1.6, 2.6)) * 10
    carpet = np.clip(np.array([105, 18, 28])[None, None, :] + ribs[:, :, None] + nprng.normal(0, 14, (Ht, Wd, 3)), 0, 255).astype("uint8")
    bg = Image.fromarray(carpet)
    ox, oy = rng.randint(0, max(1, Wd - rw)), rng.randint(0, max(1, Ht - rh))
    bg.paste(rot, (ox, oy), rot)
    a = np.array(bg).astype("float32")
    gx = np.linspace(rng.uniform(.8, 1), rng.uniform(.8, 1.05), Wd)[None, :, None]; gy = np.linspace(rng.uniform(.85, 1.05), rng.uniform(.8, 1), Ht)[:, None, None]
    a = a * gx * gy + nprng.normal(0, rng.uniform(2, 6), a.shape)
    out = Image.fromarray(np.clip(a, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(rng.uniform(.3, .9)))
    th = math.radians(ang); cx, cy = pw / 2, ph / 2
    polys = []
    for w in words:
        x0, y0, x1, y1 = w["box"]; pts = []
        for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            dx, dy = x * sc - cx, y * sc - cy
            pts.append([round(rw / 2 + dx * math.cos(th) + dy * math.sin(th) + ox, 1), round(rh / 2 - dx * math.sin(th) + dy * math.cos(th) + oy, 1)])
        polys.append(pts)
    return out, polys


def manual_patch(D):
    def ask(msg, default=""):
        s = input(f"{msg}" + (f" [{default}]" if default != "" else "") + ": ").strip(); return s or default
    p = D["patient"]
    p["first"] = ask("First name", p["first"]).title(); p["last"] = ask("Surname", p["last"]).title(); p["name"] = f"{p['first']} {p['last']}".upper()
    p["age"] = int(ask("Age", p["age"])); p["sex"] = ask("Sex (M/F)", p["sex"]).upper()[:1]; p["pid"] = ask("Patient number", p["pid"])
    if "rows" in D:
        print("Press Enter to keep the random value; flags update automatically.")
        for r in D["rows"]:
            if r["k"] != "test": continue
            r["value"] = ask(f"  {r['name']} ({r['unit']}, ref {r['ref']})", r["value"])
            try: v = float(r["value"].replace(",", "")); r["flag"] = "L" if v < r["lo"] else "H" if v > r["hi"] else ""
            except ValueError: r["flag"] = ""
    elif "test" in D:
        D["test"]["value"] = ask(f"  {D['test']['name']} ({D['test']['unit']})", D["test"]["value"])
    elif "titer" in D:
        D["titer"] = ask("  Screening titer (e.g. 1:80)", D["titer"]); D["result"] = ask("  Result", D["result"]).upper()
    return D


def job(a):
    idx, tid, seed, out, dpi, aug, pdf_on, D, row, opts = a
    rng = random.Random(seed)
    if D is None: D = csv_report(rng, tid, row, opts) if row else TEMPLATES[tid][0](rng)
    pdf, words = build_pdf(D, rng)
    name = f"{safe(D['patient']['pid'])}_{tid}" if row else f"{tid}_{idx:05d}"
    if pdf_on: open(os.path.join(out, "pdf", name + ".pdf"), "wb").write(pdf)
    img = render_png(pdf, dpi); img.save(os.path.join(out, "png", name + ".png"))
    k = dpi / 72
    gt = dict(template=tid, image=name + ".png", size=list(img.size), patient={x: v for x, v in D["patient"].items()},
              fields={x: (v if isinstance(v, (str, int, float, list, dict)) else str(v)) for x, v in D.items() if x not in ("patient", "rows", "spec")},
              rows=[{x: v for x, v in r.items() if x != "spec"} for r in D.get("rows", [])],
              words=[dict(text=w["text"], line=w["line"], box=[round(v * k, 1) for v in w["box"]]) for w in words])
    if aug:
        ph, polys = augment(img, [dict(box=[v * k for v in w["box"]]) for w in words], rng)
        ph.save(os.path.join(out, "photo", name + "_photo.jpg"), quality=rng.randint(70, 92))
        gt["photo_image"] = name + "_photo.jpg"; gt["photo_word_polygons"] = polys
    json.dump(gt, open(os.path.join(out, "labels", name + ".json"), "w"), default=str, indent=1)
    return name, (csv_warnings(row) if row else [])


def main():
    ap = argparse.ArgumentParser(description="Synthetic lab report generator for OCR training", epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=0, help="number of reports (default: one of each layout)")
    ap.add_argument("--types", nargs="*", default=["all"], choices=["all"] + list(TEMPLATES))
    ap.add_argument("--out", default="synthetic_reports"); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=150); ap.add_argument("--augment", action="store_true")
    ap.add_argument("--no-pdf", action="store_true"); ap.add_argument("--manual", action="store_true")
    ap.add_argument("--workers", type=int, default=cpu_count())
    ap.add_argument("--csv", help="read patients + values from this CSV (e.g. Mathernal_Risk.csv), one report per row")
    ap.add_argument("--limit", type=int, help="CSV mode: only the first N rows")
    ap.add_argument("--ids", nargs="*", help="CSV mode: only these Patient IDs")
    ap.add_argument("--sex"); ap.add_argument("--title"); ap.add_argument("--referred-by")
    a = ap.parse_args()
    types = (CSV_TYPES if a.csv else list(TEMPLATES)) if "all" in a.types else a.types
    if a.csv and any(x not in CSV_TYPES for x in types):
        print("Note: immuno / special / audiogram take only the patient identity from the CSV (their tests are not in it).")
    for sub in ("pdf", "png", "labels") + (("photo",) if a.augment else ()): os.makedirs(os.path.join(a.out, sub), exist_ok=True)
    jobs = []
    if a.manual:
        while True:
            print("\nLayouts:", ", ".join(f"{i + 1}={n}" for i, n in enumerate(TEMPLATES)))
            n = list(TEMPLATES)[int(input("Choose layout number: ")) - 1]
            seed = random.randint(0, 10 ** 6); D = TEMPLATES[n][0](random.Random(seed)); D = manual_patch(D)
            jobs.append((len(jobs), n, seed, a.out, a.dpi, a.augment, not a.no_pdf, D, None, None))
            if input("Add another? (y/n) [n]: ").strip().lower() != "y": break
    if a.csv:
        rows = read_csv(a.csv)
        if a.ids: rows = [r for r in rows if r.get("reg") in set(a.ids)]
        if a.limit: rows = rows[:a.limit]
        opts = dict(sex=a.sex, title=a.title, referred_by=a.referred_by)
        base = len(jobs)
        jobs += [(base + i, types[i % len(types)], a.seed * 100000 + i, a.out, a.dpi, a.augment, not a.no_pdf, None, r, opts) for i, r in enumerate(rows)]
    elif not a.manual:
        n = a.count or len(types)
        jobs = [(i, types[i % len(types)], a.seed * 100000 + i, a.out, a.dpi, a.augment, not a.no_pdf, None, None, None) for i in range(n)]
    print(f"Generating {len(jobs)} report(s) -> {a.out}/")
    results = []
    if len(jobs) > 4 and a.workers > 1 and not a.manual:
        with Pool(a.workers) as pool:
            for i, res in enumerate(pool.imap(job, jobs, chunksize=4), 1):
                results.append(res)
                if i % 50 == 0 or i == len(jobs): print(f"  {i}/{len(jobs)}", flush=True)
    else:
        for j in jobs: res = job(j); results.append(res); print("  ", res[0])
    warn = [(nm, "; ".join(w)) for nm, w in results if w]
    if warn:
        wp = os.path.join(a.out, "data_warnings.csv")
        with open(wp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["Report", "Warning"]); w.writerows(warn)
        print(f"{len(warn)} row(s) have suspicious values (report still created) -> {wp}")
    print("Done.")


if __name__ == "__main__":
    main()