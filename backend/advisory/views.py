from audit.services import log_event
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView

from assessments.models import Assessment
from core.exceptions import ApiError
from core.responses import ok
from patients.selectors import can_access_patient

from .services import _serialize, generate_advisory


class AdvisoryGenerateView(APIView):
    """POST /api/advisory/ {assessment: id} — generate or regenerate the care
    advisory for one assessment using the chatbot pipeline."""

    def post(self, request):
        if request.user.role == "ADMIN":
            raise ApiError(
                "Administrators do not generate care advisories — it is a "
                "healthcare-worker feature.",
                code="ADMIN_ADVISORY_DENIED",
                status_code=403,
            )
        assessment_id = request.data.get("assessment")
        if not assessment_id:
            raise ApiError("`assessment` is required.", code="VALIDATION_ERROR", status_code=400)
        assessment = get_object_or_404(
            Assessment.objects.select_related("patient", "prediction"), pk=assessment_id
        )
        if not can_access_patient(request.user, assessment.patient):
            raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
        result = generate_advisory(assessment, created_by=request.user, request=request)
        return ok({"advisory": result}, status=201)


class AdvisoryDetailView(APIView):
    """GET /api/advisory/?assessment=<id> — fetch the stored advisory for one
    assessment (empty when it has never been generated)."""

    def get(self, request):
        assessment_id = request.query_params.get("assessment")
        if not assessment_id:
            raise ApiError("`assessment` is required.", code="VALIDATION_ERROR", status_code=400)
        assessment = get_object_or_404(Assessment.objects.select_related("patient"), pk=assessment_id)
        if not can_access_patient(request.user, assessment.patient):
            raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
        advisory = getattr(assessment, "advisory", None)
        log_event(request, "ADVISORY_ACCESS", target_type="advisory",
                  target_id=str(advisory.id) if advisory else None,
                  detail={"assessment": assessment.id, "found": bool(advisory)})
        return ok({"advisory": _serialize(advisory) if advisory else None})
