"""Image preprocessing for OCR quality.

Each step is individually switchable so its effect can be measured in the
Phase 3 evaluation (preprocess.py::preprocess_image accepts flags).

Pipeline order (when enabled): grayscale -> denoise -> deskew -> resize
(upscale small / cap at MAX_SIDE) -> threshold.

The resize step runs BEFORE thresholding: thresholding an upscaled image
keeps stroke edges smooth, which matters for blurred and low-resolution
photos (thresholding before upscale destroys them — measured in Phase 2
testing). Threshold method adapts: Otsu for clean high-contrast prints,
adaptive for unevenly lit photos.
"""
import cv2
import numpy as np

MAX_SIDE = 1500
MIN_SIDE = 1000  # images smaller than this are upscaled for OCR


def preprocess_image(image_bgr, grayscale=True, denoise=True, deskew=True, threshold=True, resize=True):
    """Run the pipeline over a BGR/gray ndarray. Every step can be turned off
    independently (evaluation). Returns the processed ndarray.

    Order: grayscale -> denoise -> deskew -> adaptive threshold -> resize.
    (Threshold-before-resize preserved small glyphs like decimal points in
    Phase 2 testing; Otsu/median variants eroded them and were rejected.)
    """
    img = image_bgr
    if img is None or img.size == 0:
        raise ValueError("Empty image")
    if grayscale and img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if denoise:
        # Default window sizes matter: smaller (5/15) measurably degraded
        # recognition of small glyphs (decimal points) in Phase 2 testing.
        img = cv2.fastNlMeansDenoising(img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), h=10)
    if deskew and img.ndim == 2:
        img = _deskew(img)
    if threshold and img.ndim == 2:
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
        )
    if resize:
        img = _normalize_size(img)
    return img


MAX_SIDE = 3000         # hard memory cap for OCR input
OCR_TARGET_SIDE = 2200  # small photos are upscaled to at least this side (2-3x for phones)
MAX_UPSCALE = 3.0


def preprocess_image(image_bgr, grayscale=True, denoise=True, deskew=True, threshold=True, resize=True):
    """Legacy flag-based pipeline (kept for ablations/compat).

    Order: grayscale -> denoise -> deskew -> adaptive threshold -> resize.
    New code should prefer preprocess_variant() (cascade levels below).
    """
    img = image_bgr
    if img is None or img.size == 0:
        raise ValueError("Empty image")
    if grayscale and img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if denoise:
        img = cv2.fastNlMeansDenoising(img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), h=10)
    if deskew and img.ndim == 2:
        img = _deskew(img)
    if threshold and img.ndim == 2:
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
        )
    if resize:
        img = _normalize_size(img)
    return img


def preprocess_variant(image_bgr, level=0):
    """Cascade preprocessing variants (Step 2 approved design):

    level 0 (fast):  grayscale + cubic upscale to OCR_TARGET_SIDE.
    level 1:         + CLAHE (local contrast) + background normalization
                     (divide by a large blurred copy) — removes shadows and
                     uneven lighting WITHOUT destroying decimal points the
                     way hard thresholding does.
    level 2:         + mild denoise + deskew.
    level 3:         + hard adaptive threshold (optional variant only).
    """
    from django.conf import settings

    img = image_bgr
    if img is None or img.size == 0:
        raise ValueError("Empty image")
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if getattr(settings, "OCR_ENABLE_UPSCALE", True):
        img = _normalize_size(img)  # upscale/downscale FIRST: enhancement at OCR resolution
    if level >= 1:
        img = _background_normalize(img)
        img = _clahe(img)
    if level >= 2:
        img = cv2.fastNlMeansDenoising(img, h=7)
        img = _deskew(img)
    if level >= 3:
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15
        )
    return img


def _clahe(gray, clip_limit=2.5):
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _background_normalize(gray, block=51):
    """Divide by a large blurred copy: flattens shadows/uneven lighting while
    preserving stroke contrast (unlike thresholding, keeps gray levels)."""
    background = cv2.GaussianBlur(gray, (block, block), 0)
    background = cv2.medianBlur(background, block)
    norm = cv2.divide(gray, background, scale=255)
    return norm


def _normalize_size(img):
    """Upscale small photos to OCR_TARGET_SIDE (cubic, capped 3x) — small
    text needs ~30 px height for Tesseract; decimals/digits fall below it
    otherwise. Downscale ONLY above MAX_SIDE (never below the OCR target)."""
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        scale = MAX_SIDE / max(h, w)
    elif max(h, w) < OCR_TARGET_SIDE:
        scale = min(OCR_TARGET_SIDE / max(h, w), MAX_UPSCALE)
    else:
        scale = 1.0
    if scale != 1.0:
        interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=interpolation)
    return img


def _deskew(gray):
    """Estimate skew from near-horizontal text edges and rotate to correct.
    Small angles only (±15°); larger rotations are left to the user."""
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=120, minLineLength=80, maxLineGap=8)
    if lines is None:
        return gray
    angles = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if x2 == x1:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) <= 15:  # near-horizontal text lines only
            angles.append(angle)
    if not angles:
        return gray
    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.3:
        return gray
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def decode_image(content: bytes):
    """Decode bytes to an ndarray; raises ValueError for undecodable data."""
    array = np.frombuffer(content, dtype=np.uint8)
    img = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Image could not be decoded.")
    return img
