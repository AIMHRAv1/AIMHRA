"""OCR engine layer. Tesseract via pytesseract; PDFs with a real text layer
are read directly with PyMuPDF (exact, no OCR). Everything imports lazily so
nothing heavy loads at server startup, and the Tesseract binary is probed
only on first use.

Line model consumed by the parser:
    {"text": str, "conf": float 0..1, "source": "tesseract" | "pymupdf_text"}
"""
import logging
import shutil
from pathlib import Path

from ocr.exceptions import EngineUnavailable

logger = logging.getLogger(__name__)

TESSERACT_INSTALL_HINT = (
    "The OCR engine (Tesseract) is not installed on the server. "
    "Install it and try again — Windows: run the UB-Mannheim installer "
    "https://github.com/UB-Mannheim/tesseract/wiki and set TESSERACT_CMD if it "
    "is not on PATH. Ubuntu/Debian: sudo apt install tesseract-ocr. "
    "Alternatively, upload a PDF whose pages contain selectable text."
)

# Lines shorter than this are treated as noise when deciding whether a PDF
# page already has a usable text layer.
PDF_TEXT_MIN_CHARS = 40
MAX_PDF_PAGES = 2


_COMMON_WINDOWS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _tesseract_cmd():
    from django.conf import settings

    cmd = getattr(settings, "TESSERACT_CMD", "") or ""
    if cmd and Path(cmd).exists():
        return cmd
    found = shutil.which("tesseract")
    if found:
        return found
    # Common winget/UB-Mannheim install locations (not always on PATH).
    for candidate in _COMMON_WINDOWS_PATHS:
        if Path(candidate).exists():
            return candidate
    if cmd:
        return cmd  # configured but missing — let the engine raise a clear error
    return None


def tesseract_available():
    return _tesseract_cmd() is not None


def _configure_pytesseract():
    import pytesseract

    cmd = _tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def _tessdata_best_dir():
    """Packaged tessdata_best (LSTM) directory when present — measurably
    better digit/decimal accuracy than the default tessdata."""
    from django.conf import settings

    if not getattr(settings, "OCR_TESSDATA_BEST", True):
        return None
    best = Path(__file__).resolve().parent.parent / "tessdata_best"  # backend/ocr/tessdata_best
    if (best / "eng.traineddata").exists():
        return str(best)
    return None


def _base_tess_args():
    """Upgraded Tesseract config (Step 3): LSTM OEM, explicit DPI, and the
    tessdata_best directory when packaged."""
    args = ["--oem 1", "-c user_defined_dpi=300"]
    best = _tessdata_best_dir()
    if best:
        args.append(f"--tessdata-dir {best}")
    return args


def _tesseract_languages():
    """Installed Tesseract languages; gracefully degrades to 'eng'."""
    try:
        pytesseract = _configure_pytesseract()
        raw = pytesseract.get_languages(config="")
        return [lang for lang in raw if lang and lang != "osd"]
    except Exception:
        return []


def ensure_engine_available():
    """Raise EngineUnavailable (with install guidance) when Tesseract is
    needed but missing. Called before any OCR work starts."""
    if not tesseract_available():
        raise EngineUnavailable(TESSERACT_INSTALL_HINT)


def ocr_image(content: bytes, preprocess_flags=None, return_words=False, variant=None):
    """Run Tesseract over image bytes.

    Returns (lines, engine_info) — or, with return_words=True,
    (lines, engine_info, words, processed_image) where words carries bounding
    boxes for field-level re-reading. `variant` selects a cascade
    preprocessing level (preprocess_variant) when given, overriding
    preprocess_flags.
    """
    ensure_engine_available()
    from ocr.services.preprocess import decode_image, preprocess_image, preprocess_variant

    img = decode_image(content)
    if variant is not None:
        processed = preprocess_variant(img, level=variant)
    else:
        processed = preprocess_image(img, **(preprocess_flags or {}))

    import pytesseract

    _configure_pytesseract()
    installed = _tesseract_languages()
    # Spec: "eng" plus "nep" if installed; fall back to English gracefully.
    langs = "eng+nep" if "nep" in installed else "eng"
    config = " ".join(["--psm 6"] + _base_tess_args())
    data = pytesseract.image_to_data(
        processed, lang=langs, config=config, output_type=pytesseract.Output.DICT
    )

    lines = _group_tesseract_lines(data)
    engine_info = {"engine": "tesseract", "languages": langs}
    if return_words:
        words = _flat_words(data)
        return lines, engine_info, words, processed
    return lines, engine_info


def _flat_words(data):
    """Flat word list with bounding boxes (for crop re-reading)."""
    words = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not text or conf < 0:
            continue
        words.append({
            "text": text, "conf": conf / 100.0,
            "left": int(data["left"][i]), "top": int(data["top"][i]),
            "width": int(data["width"][i]), "height": int(data["height"][i]),
            "line": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
        })
    return words


def ocr_value_crop(processed_img, box):
    """Re-read a small value region with a digit whitelist (psm 7, OEM 1,
    explicit DPI). The crop is padded with WHITE and scaled so the digit
    height is >= 40 px — small crops are where decimals get lost. Returns
    the raw crop text (may be empty)."""
    import cv2
    import pytesseract

    _configure_pytesseract()
    x, y, w, h = box
    pad = max(6, h // 3)
    h_img, w_img = processed_img.shape[:2]
    crop = processed_img[max(0, y - pad):min(h_img, y + h + pad), max(0, x - pad):min(w_img, x + w + pad)]
    if crop.size == 0:
        return ""
    if crop.ndim == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # White padding frame so glyphs never touch the crop border.
    crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    # Scale so digit height >= 40 px.
    scale = max(1.0, 40.0 / max(1.0, float(h)))
    if scale > 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    config = " ".join([
        "--psm 7 -c tessedit_char_whitelist=0123456789.,-",
    ] + _base_tess_args())
    text = pytesseract.image_to_string(crop, config=config)
    return text.strip()


def _group_tesseract_words(words):
    """Group a flat pytesseract word dict into text lines with mean confidence."""
    import pytesseract

    rows = {}
    n = len(words.get("text", []))
    for i in range(n):
        text = (words["text"][i] or "").strip()
        try:
            conf = float(words["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not text or conf < 0:
            continue
        key = (words["block_num"][i], words["par_num"][i], words["line_num"][i])
        rows.setdefault(key, []).append((words["left"][i], text, conf / 100.0))
    lines = []
    for key in sorted(rows):
        items = sorted(rows[key], key=lambda t: t[0])
        conf = sum(c for _, _, c in items) / len(items)
        lines.append({"text": " ".join(t for _, t, _ in items), "conf": round(min(conf, 1.0), 3)})
    return lines


def _group_tesseract_lines(data):
    """Group the flat pytesseract dict into text lines with mean confidence
    and per-line word boxes (used for field-level crop re-reading)."""
    rows = {}
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not text or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        rows.setdefault(key, []).append({
            "text": text, "conf": conf / 100.0,
            "left": int(data["left"][i]), "top": int(data["top"][i]),
            "width": int(data["width"][i]), "height": int(data["height"][i]),
        })
    lines = []
    for key in sorted(rows):
        items = sorted(rows[key], key=lambda wd: wd["left"])
        conf = sum(w["conf"] for w in items) / len(items)
        lines.append({
            "text": " ".join(w["text"] for w in items),
            "conf": round(min(conf, 1.0), 3),
            "words": items,
        })
    return lines


def extract_pdf(content: bytes):
    """Extract text from a PDF.

    If the pages carry a real text layer, return those lines directly
    (exact — no OCR). Otherwise render the first pages to images and OCR
    them. Returns (lines, engine_info).
    """
    import fitz  # PyMuPDF — lazy import

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        text_lines = []
        for page in doc[:MAX_PDF_PAGES]:
            for raw in page.get_text().splitlines():
                text = raw.strip()
                if text:
                    text_lines.append({"text": text, "conf": 1.0, "source": "pymupdf_text"})
        if sum(len(l["text"]) for l in text_lines) >= PDF_TEXT_MIN_CHARS:
            return text_lines, {"engine": "pymupdf_text", "pages": min(len(doc), MAX_PDF_PAGES)}

        # Scanned PDF: render pages to images and OCR.
        ensure_engine_available()
        lines = []
        for page in doc[:MAX_PDF_PAGES]:
            pix = page.get_pixmap(dpi=300)  # Step 2: 300 DPI for scanned PDFs
            page_lines, _ = ocr_image(pix.tobytes("png"))
            lines.extend(page_lines)
        return lines, {"engine": "tesseract", "pages": min(len(doc), MAX_PDF_PAGES), "via": "rendered_pdf"}
    finally:
        doc.close()
