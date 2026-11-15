"""Capture-quality gate (Step 3): runs BEFORE any OCR.

Rejects photos that are too small or too blurry with a clear "retake the
photo" message — misreads on such inputs were the main source of
dangerous (plausible-looking) errors in the Step 2 diagnosis.

Checks (configurable via settings):
- minimum original width (OCR_MIN_WIDTH, default 1200 px)
- blur: variance of the Laplacian below OCR_MIN_BLUR_VAR (default 40)
- escape hatch for tests/evaluation: OCR_ALLOW_LOW_QUALITY=1 disables the gate

Only the decoded image is inspected; nothing about its content is logged.
"""
import logging

from django.conf import settings

from ocr.exceptions import CaptureQualityError

logger = logging.getLogger(__name__)

RETAKE_MESSAGE = (
    "This photo is not good enough to scan reliably. Please retake it: "
    "fill the frame with the report card, hold the camera steady and parallel "
    "to the page, and use even light (avoid shadows and glare). "
    "Alternatively, upload the PDF report."
)


def check_capture_quality(content: bytes, file_type: str):
    """Raise OcrError (retake message) when the capture is too small or too
    blurry. Never raises for undecodable data (the extraction step reports
    that); never inspects or logs file content."""
    if getattr(settings, "OCR_ALLOW_LOW_QUALITY", False):
        return
    if file_type == "pdf":
        return  # PDFs are rendered at 300 DPI by the engine itself

    try:
        import cv2
        import numpy as np

        array = np.frombuffer(content, dtype=np.uint8)
        img = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return  # undecodable — let the extraction step report it
    except Exception:
        return

    h, w = img.shape[:2]
    min_width = int(getattr(settings, "OCR_MIN_WIDTH", 1200))
    if w < min_width:
        raise CaptureQualityError(
            f"The photo is too small ({w} px wide; at least {min_width} px needed). "
            + RETAKE_MESSAGE
        )

    min_blur_var = float(getattr(settings, "OCR_MIN_BLUR_VAR", 40))
    blur_var = float(cv2.Laplacian(img, cv2.CV_64F).var())
    if blur_var < min_blur_var:
        raise CaptureQualityError(
            f"The photo is too blurry (sharpness {blur_var:.0f}, minimum {min_blur_var:.0f}). "
            + RETAKE_MESSAGE
        )
    logger.info("Capture gate passed: %dx%d, blur var %.0f", w, h, blur_var)
