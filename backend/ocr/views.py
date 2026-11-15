import logging

from audit.services import log_event
from core.exceptions import ApiError
from core.responses import ok
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

from ocr.exceptions import CaptureQualityError, EngineUnavailable, OcrError, UploadValidationError
from ocr.models import OcrExtraction
from ocr.services import pipeline, upload
from ocr.services.parser import TARGET_FIELDS

logger = logging.getLogger(__name__)


class OcrFeedbackView(APIView):
    """POST /api/ocr/feedback/ — measures real-world OCR error rate.

    Body: {"entries": [{"field": "age", "changed": true}, ...]} — field NAMES
    and whether the operator changed them. Values are NEVER accepted, stored
    or logged.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ocr_extract"

    def post(self, request):
        entries = request.data.get("entries")
        if not isinstance(entries, list) or not entries:
            raise ApiError("`entries` must be a non-empty list of {field, changed}.", code="VALIDATION_ERROR", status_code=400)
        allowed = set(TARGET_FIELDS)
        changed, kept = [], []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            field = str(entry.get("field", ""))
            if field not in allowed:
                continue
            (changed if entry.get("changed") else kept).append(field)
        log_event(
            request, "OCR_FEEDBACK", target_type="ocr_extraction",
            detail={"changed_fields": sorted(set(changed)), "kept_fields": sorted(set(kept))},
        )
        return ok({"recorded": len(set(changed)) + len(set(kept))})


class OcrExtractView(APIView):
    """POST /api/ocr/extract/ — pre-fill helper only.

    Accepts a report-card image/PDF and returns extracted field suggestions
    for the operator to review. It NEVER creates an Assessment and NEVER
    runs a prediction.
    """

    # Scoped throttle: OCR is CPU-heavy; per-user cap independent of the
    # global (absent) throttle config.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ocr_extract"

    def post(self, request):
        file_type, content = self._validated_upload(request)

        try:
            payload = pipeline.extract(file_type, content)
        except CaptureQualityError as exc:
            raise ApiError(str(exc), code="CAPTURE_QUALITY", status_code=422)
        except EngineUnavailable as exc:
            raise ApiError(str(exc), code="OCR_ENGINE_UNAVAILABLE", status_code=503)
        except OcrError as exc:
            raise ApiError(str(exc), code="OCR_EXTRACT_FAILED", status_code=400)
        except ValueError as exc:
            raise ApiError(str(exc) or "The file could not be read.", code="VALIDATION_ERROR", status_code=400)

        summary = payload.pop("summary", {})
        try:
            OcrExtraction.objects.create(
                user=request.user if request.user.is_authenticated else None,
                file_type=file_type,
                engine=payload.get("engine_info", {}).get("engine", "unknown"),
                fields_extracted=summary.get("fields_extracted", 0),
                fields_flagged=summary.get("fields_flagged", 0),
                duration_ms=payload.get("engine_info", {}).get("duration_ms", 0),
            )
        except Exception:
            # The extraction result is the product; a metadata-recording
            # failure must not destroy it (logged so the cause is visible).
            logger.exception("OcrExtraction record could not be saved")
        # Audit: counts and file type only — never raw text or values.
        try:
            log_event(
                request, "OCR_EXTRACTED", target_type="ocr_extraction",
                detail={
                    "file_type": file_type,
                    "fields_extracted": summary.get("fields_extracted", 0),
                    "fields_flagged": summary.get("fields_flagged", 0),
                },
            )
        except Exception:
            logger.exception("OCR_EXTRACTED audit event could not be saved")
        return ok(payload)

    @staticmethod
    def _validated_upload(request):
        upload_file = request.FILES.get("file")
        try:
            return upload.validate_upload(upload_file)
        except UploadValidationError as exc:
            raise ApiError(str(exc), code="VALIDATION_ERROR", status_code=400)
