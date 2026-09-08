from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.views import APIView

from assessments.models import Assessment
from audit.services import log_event
from core.exceptions import ApiError
from core.responses import ok
from patients.selectors import can_access_patient
from reports.models import Report
from reports.services import generate_report


class ReportSerializer(serializers.ModelSerializer):
    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    assessment_id = serializers.IntegerField(read_only=True)
    filename = serializers.CharField(source="file.name", read_only=True)

    class Meta:
        model = Report
        fields = ["id", "patient", "patient_code", "assessment_id", "filename", "created_at"]


class ReportListCreateView(APIView):
    def get(self, request):
        user = request.user
        qs = Report.objects.select_related("patient", "assessment").order_by("-created_at")
        patient_id = request.query_params.get("patient")
        if user.role == "PATIENT":
            qs = qs.filter(patient__user=user)
        elif user.role == "HEALTHCARE_WORKER":
            from patients.selectors import patient_ids_for_healthcare_worker

            ids = patient_ids_for_healthcare_worker(user)
            qs = qs.filter(patient_id__in=ids)
            if patient_id:
                qs = qs.filter(patient_id=patient_id)
        else:
            qs = Report.objects.none()
        return ok({"reports": ReportSerializer(qs[:50], many=True).data})

    def post(self, request):
        assessment_id = request.data.get("assessment")
        if not assessment_id:
            raise ApiError("`assessment` id is required.", code="VALIDATION_ERROR", status_code=400)
        assessment = get_object_or_404(
            Assessment.objects.select_related("patient", "prediction"), pk=assessment_id
        )
        if not can_access_patient(request.user, assessment.patient):
            raise ApiError("You are not authorized to generate a report for this assessment.",
                           code="PERMISSION_DENIED", status_code=403)
        if not hasattr(assessment, "prediction"):
            raise ApiError("This assessment has no prediction to report.", code="VALIDATION_ERROR", status_code=400)
        report = generate_report(assessment, request.user)
        log_event(request, "REPORT_GENERATED", target_type="report", target_id=str(report.id),
                  detail={"assessment": assessment.id, "patient": assessment.patient_id})
        return ok({"report": ReportSerializer(report).data, "download_url": report.file.url}, status=201)


class ReportDownloadView(APIView):
    def get(self, request, pk):
        report = get_object_or_404(Report.objects.select_related("patient"), pk=pk)
        if not can_access_patient(request.user, report.patient):
            raise ApiError("You are not authorized to access this report.", code="PERMISSION_DENIED", status_code=403)
        from django.http import FileResponse

        response = FileResponse(report.file.open("rb"), as_attachment=True, filename=report.file.name.split("/")[-1])
        return response
