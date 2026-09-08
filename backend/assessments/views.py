from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.views import APIView

from assessments.models import Alert, Assessment, Prediction
from assessments.serializers import AlertAckSerializer, AlertSerializer, AssessmentSerializer
from assessments.services import DISCLAIMER, create_assessment, prediction_series
from assessments.trends import compute_trend
from core.exceptions import ApiError
from core.responses import ok
from core.permissions import IsHealthcareWorker
from patients.models import PatientProfile
from patients.selectors import can_access_patient


def _resolve_patient(request):
    """Resolve the explicitly selected patient and verify access.

    Every worker/admin patient-scoped request must name a patient
    (?patient=<id> in the query string or `patient` in the body) so the
    frontend can never accidentally assess/read the wrong record.
    """
    user = request.user
    patient_id = request.query_params.get("patient") or request.data.get("patient")
    if not patient_id:
        raise ApiError("`patient` query parameter is required.", code="VALIDATION_ERROR", status_code=400)
    profile = get_object_or_404(PatientProfile, pk=patient_id)
    if not can_access_patient(user, profile):
        raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
    return profile


class AssessmentListCreateView(generics.ListCreateAPIView):
    serializer_class = AssessmentSerializer

    def get_queryset(self):
        qs = Assessment.objects.select_related("prediction", "patient").prefetch_related("alerts")
        user = self.request.user
        if user.role != "ADMIN":
            from patients.selectors import patient_ids_for_healthcare_worker

            ids = patient_ids_for_healthcare_worker(user)
            qs = qs.filter(patient_id__in=ids)
        patient = self.request.query_params.get("patient")
        if patient:
            profile = get_object_or_404(PatientProfile, pk=patient)
            if not can_access_patient(user, profile):
                raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
            qs = qs.filter(patient=profile)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        return ok({"results": serializer.data, "count": qs.count()} if page is None else {"results": serializer.data})

    def create(self, request, *args, **kwargs):
        patient = _resolve_patient(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # The service runs the full pipeline: predict -> SHAP -> rules -> persist.
        result = create_assessment(patient, serializer.validated_data, request=request)
        return ok(result, status=201)


class AssessmentDetailView(generics.RetrieveAPIView):
    serializer_class = AssessmentSerializer

    def get_object(self):
        assessment = get_object_or_404(
            Assessment.objects.select_related("prediction", "patient"), pk=self.kwargs["pk"]
        )
        if not can_access_patient(self.request.user, assessment.patient):
            raise ApiError("You are not authorized to access this assessment.", code="PERMISSION_DENIED", status_code=403)
        return assessment


class RiskHistoryView(APIView):
    """Chronological prediction series for the resolved patient."""

    def get(self, request):
        patient = _resolve_patient(request)
        return ok({"history": prediction_series(patient), "disclaimer": DISCLAIMER})


class RiskTrendView(APIView):
    """Trend analytics over the prediction series."""

    def get(self, request):
        patient = _resolve_patient(request)
        history = prediction_series(patient)
        probabilities = [
            {"visit_date": h["visit_date"], "high_risk_probability": h.get("probability") if h["risk_level"] == "high risk" else None,
             "risk_level": h["risk_level"], "gestational_week": h.get("gestational_week")}
            for h in history
        ]
        return ok(
            {
                "trend": compute_trend(history),
                "series": history,
                "disclaimer": "Trends describe stored assessments only. The system does not predict future risk.",
            }
        )


class AlertListView(generics.ListAPIView):
    serializer_class = AlertSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Alert.objects.select_related("patient", "assessment").all()
        if user.role == "HEALTHCARE_WORKER":
            from patients.selectors import patient_ids_for_healthcare_worker

            ids = patient_ids_for_healthcare_worker(user)
            qs = qs.filter(patient_id__in=ids)
        patient = self.request.query_params.get("patient")
        if patient:
            profile = get_object_or_404(PatientProfile, pk=patient)
            if not can_access_patient(user, profile):
                raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
            qs = qs.filter(patient=profile)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return qs


class AlertAckView(APIView):
    """Healthcare workers acknowledge/resolve alerts."""

    permission_classes = [IsHealthcareWorker]

    def post(self, request, pk):
        alert = get_object_or_404(Alert, pk=pk)
        if not can_access_patient(request.user, alert.patient):
            raise ApiError("You are not authorized to manage this alert.", code="PERMISSION_DENIED", status_code=403)
        serializer = AlertAckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert.status = serializer.validated_data["status"]
        alert.acknowledged_by = request.user
        alert.save(update_fields=["status", "acknowledged_by"])
        return ok({"alert": AlertSerializer(alert).data})
