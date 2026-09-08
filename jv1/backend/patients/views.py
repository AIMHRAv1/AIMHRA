from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import services as audit_svc
from core.exceptions import ApiError
from core.permissions import IsAdmin, IsHealthcareWorker
from core.responses import ok
from patients.models import PatientAssignment, PatientProfile
from patients.selectors import can_access_patient, patient_ids_for_healthcare_worker
from patients.serializers import PatientAssignmentSerializer, PatientProfileSerializer


class PatientCreateView(generics.CreateAPIView):
    """Create a patient record without creating a patient login account."""

    serializer_class = PatientProfileSerializer
    permission_classes = [IsHealthcareWorker | IsAdmin]

    def perform_create(self, serializer):
        patient = serializer.save()
        if self.request.user.role == "HEALTHCARE_WORKER":
            PatientAssignment.objects.get_or_create(
                healthcare_worker=self.request.user, patient=patient
            )


class MyProfileView(generics.RetrieveUpdateAPIView):
    """Legacy patient self-service endpoint is intentionally unavailable."""

    serializer_class = PatientProfileSerializer
    permission_classes = [IsHealthcareWorker]

    def get_object(self):
        raise ApiError("Use the worker account profile endpoint.", code="PERMISSION_DENIED", status_code=403)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        audit_svc.log_event(
            request, "PROFILE_UPDATED", target_type="patient_profile", target_id=str(self.get_object().id)
        )
        return response


class PatientListView(generics.ListAPIView):
    """Patient list scoped by role:
    - HEALTHCARE_WORKER: assigned patients only
    """

    serializer_class = PatientProfileSerializer

    def get_queryset(self):
        user = self.request.user
        qs = PatientProfile.objects.select_related("user").all()
        if user.role != "HEALTHCARE_WORKER":
            return PatientProfile.objects.none()
        ids = patient_ids_for_healthcare_worker(user)
        qs = qs.filter(id__in=ids)
        # search/filter
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                models_q(search)
            )
        return qs


def models_q(search):
    from django.db.models import Q

    return Q(patient_code__icontains=search) | Q(full_name__icontains=search) | Q(phone_number__icontains=search)


class PatientDetailView(generics.RetrieveAPIView):
    serializer_class = PatientProfileSerializer

    def get_object(self):
        profile = get_object_or_404(PatientProfile, pk=self.kwargs["pk"])
        if not can_access_patient(self.request.user, profile):
            raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
        return profile


class PatientAssignmentListView(generics.ListCreateAPIView):
    """Admin manages worker->patient authorization."""

    serializer_class = PatientAssignmentSerializer
    permission_classes = [IsAdmin]
    queryset = PatientAssignment.objects.select_related("patient", "healthcare_worker", "assigned_by").all()

    def perform_create(self, serializer):
        assignment = serializer.save(assigned_by=self.request.user)
        audit_svc.log_event(
            self.request,
            "PATIENT_ASSIGNED",
            target_type="patient_assignment",
            target_id=str(assignment.id),
            detail={"patient": assignment.patient_id, "worker": assignment.healthcare_worker_id},
        )


class PatientAssignmentDetailView(generics.DestroyAPIView):
    serializer_class = PatientAssignmentSerializer
    permission_classes = [IsAdmin]
    queryset = PatientAssignment.objects.all()


class SystemStatsView(APIView):
    """Admin dashboard statistics."""

    permission_classes = [IsAdmin]

    def get(self, request):
        from accounts.models import User
        from assessments.models import Alert, Assessment, Prediction
        from chat.models import ChatSession
        from kb.models import KnowledgeDocument
        from mlcore.models import ModelVersion
        from reports.models import Report

        total_users = User.objects.count()
        by_role = {
            r: User.objects.filter(role=r).count() for r in ("PATIENT", "HEALTHCARE_WORKER", "ADMIN")
        }
        risk_counts = {
            lvl: Prediction.objects.filter(risk_level=lvl).count()
            for lvl in ("low risk", "mid risk", "high risk")
        }
        return ok(
            {
                "users": {"total": total_users, "by_role": by_role},
                "patients": PatientProfile.objects.count(),
                "assessments": Assessment.objects.count(),
                "predictions": Prediction.objects.count(),
                "risk_distribution": risk_counts,
                "alerts": {
                    "open": Alert.objects.filter(status="OPEN").count(),
                    "total": Alert.objects.count(),
                },
                "chat_sessions": ChatSession.objects.count(),
                "knowledge_documents": KnowledgeDocument.objects.count(),
                "reports": Report.objects.count(),
                "models": {
                    "total": ModelVersion.objects.count(),
                    "production": ModelVersion.objects.filter(status="PRODUCTION").values(
                        "name", "version", "trained_at"
                    ).first(),
                },
            }
        )
