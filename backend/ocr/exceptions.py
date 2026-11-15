"""OCR-layer exceptions mapped to API responses by ocr.views."""


class OcrError(Exception):
    """Base class: message is user-safe."""


class UploadValidationError(OcrError):
    """Uploaded file rejected (type/size)."""


class CaptureQualityError(OcrError):
    """The photo failed the capture-quality gate (too small / too blurry).
    Operator action: retake the photo."""


class EngineUnavailable(OcrError):
    """The OCR engine binary is not installed. Carries install guidance."""
