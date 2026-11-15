"""Training-crop generation from the report/reports corpus.

Every PDF in report/reports/pdf carries an exact vector text layer. Word
boxes from PyMuPDF mapped onto the rendered PNG (150 dpi, scale = png_width /
pdf_width) give pixel-exact (crop, label) pairs for ALL report templates —
the "lab" letterhead template, municipal, medicare and clinical.

Output: <out>/crops/<split>/<n>.png + <out>/labels.tsv ("split/name label").
The train/eval split follows the corpus convention: patient reg-ID % 5 == 0
goes to eval, everything else to train, so the recognizer never trains on
the held-out evaluation patients.
"""
import re
import unicodedata
from pathlib import Path

# easyocr gen2 english charset — labels must stay inside it
G2_CHARSET = '0123456789!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~ ÇABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

# label normalization for glyphs the g2 charset lacks
_CHAR_MAP = {"²": "2", "°": "", "×": "x", "¼": "1/4", "½": "1/2", "–": "-", "−": "-"}

_MIN_WORD_LEN = 1
_MAX_WORD_LEN = 24  # long legal/URL lines teach nothing useful here
_CROP_PAD = 2  # px of padding around each word box


def normalize_label(text):
    """Map missing glyphs, drop words that still fall outside the charset.
    Returns normalized label or None (skip)."""
    t = text or ""
    for src, dst in _CHAR_MAP.items():
        t = t.replace(src, dst)
    # collapse whitespace: labels are single words from the PDF layer
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t) < _MIN_WORD_LEN or len(t) > _MAX_WORD_LEN:
        return None
    if any(ch not in G2_CHARSET for ch in t):
        return None
    # keep words with at least one letter/digit (pure punctuation is noise)
    if not any(ch.isalnum() for ch in t):
        return None
    return t


def words_from_pdf(pdf_path):
    """(x0, y0, x1, y1, text) tuples in PDF points, plus page size."""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    page = doc[0]
    words = [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]
    pw, ph = page.rect.width, page.rect.height
    doc.close()
    return words, pw, ph


def crop_words(png_path, pdf_path, page_image=None):
    """Yield (PIL.Image gray crop, label) for every usable word on the page.

    page_image: preprocessed PIL page (what the OCR engine actually feeds the
    recognizer — binarized + upscaled). When given, word boxes are mapped onto
    IT so training crops match the inference distribution; otherwise crops
    come from the raw PNG render.
    """
    from PIL import Image

    words, pw, _ph = words_from_pdf(pdf_path)
    img = page_image if page_image is not None else Image.open(str(png_path))
    scale = img.width / pw
    if abs(img.height / scale - _ph) > 3:  # png/pdf mismatch guard
        return
    for (x0, y0, x1, y1, text) in words:
        label = normalize_label(text)
        if label is None:
            continue
        box = (
            max(0, int(x0 * scale) - _CROP_PAD),
            max(0, int(y0 * scale) - _CROP_PAD),
            min(img.width, int(x1 * scale) + _CROP_PAD),
            min(img.height, int(y1 * scale) + _CROP_PAD),
        )
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            continue
        crop = img.crop(box).convert("L")
        yield crop, label


def _preprocessed_page(png_path):
    """The exact page image the EasyOCR engine feeds to readtext:
    decode -> grayscale -> denoise -> deskew -> threshold -> resize."""
    import cv2
    from PIL import Image

    from ocr.services.preprocess import decode_image, preprocess_image

    processed = preprocess_image(decode_image(png_path.read_bytes()))
    if processed.ndim == 3:
        processed = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
    return Image.fromarray(processed, "L")


def build_corpus(png_dir, pdf_dir, out_dir, max_per_page=48, match_engine=True):
    """Build the crop dataset. Returns (train_count, eval_count).

    match_engine=True renders crops from the preprocessed pages so the
    recognizer trains on what it sees at inference time (the earlier
    grayscale-render crops made the fine-tuned model fail on real pages).
    """
    out = Path(out_dir)
    (out / "crops" / "train").mkdir(parents=True, exist_ok=True)
    (out / "crops" / "eval").mkdir(parents=True, exist_ok=True)
    labels = out / "labels.tsv"

    pngs = sorted(Path(png_dir).glob("*.png"))
    rows = []
    n_train = n_eval = 0
    idx = 0
    for png in pngs:
        stem = png.stem
        if "degraded" in stem:
            continue
        reg = stem.split("_", 1)[0]
        if not reg.isdigit():
            continue
        split = "eval" if int(reg) % 5 == 0 else "train"
        pdf = Path(pdf_dir) / (stem + ".pdf")
        if not pdf.exists():
            continue
        page = _preprocessed_page(png) if match_engine else None
        pairs = list(crop_words(png, pdf, page_image=page))
        if not pairs:
            continue
        # cap per page, prioritizing digit-bearing tokens (the values) and
        # label words, then the rest
        digit_first = sorted(pairs, key=lambda p: (0 if any(c.isdigit() for c in p[1]) else 1, p[1]))
        chosen = digit_first[:max_per_page]
        for crop, label in chosen:
            idx += 1
            rel = f"crops/{split}/{idx:06d}.png"
            crop.save(out / rel)
            rows.append(f"{split}\t{reg}\t{rel}\t{label}")
            if split == "train":
                n_train += 1
            else:
                n_eval += 1

    labels.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return n_train, n_eval
