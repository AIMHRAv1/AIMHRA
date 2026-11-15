from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.views import APIView

from audit import services as audit_svc
from core.exceptions import ApiError
from core.permissions import IsAdmin
from core.responses import ok
from patients.models import PatientAssignment, PatientProfile
from patients.selectors import (
    can_access_patient,
    patient_summaries,
    scoped_patient_queryset,
)
from patients.serializers import PatientAssignmentSerializer, PatientProfileSerializer


class PatientListView(generics.ListCreateAPIView):
    """Healthcare-worker/administrator patient management.

    GET  /api/patients/   - scoped list (search: code/name/phone/email);
                            administrator responses are PII-redacted
    POST /api/patients/   - create a standalone patient record. The creator is
                            automatically granted access (no admin step needed).
                            Administrators are denied: they do not handle
                            patient information.
    """

    serializer_class = PatientProfileSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["redact_pii"] = self.request.user.role == "ADMIN"
        return context

    def get_queryset(self):
        qs = scoped_patient_queryset(self.request.user)
        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(patient_code__icontains=search)
                | Q(full_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
            )
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        summaries = patient_summaries(qs.values_list("id", flat=True))
        serializer = self.get_serializer(
            page if page is not None else qs,
            many=True,
            context={**self.get_serializer_context(), "patient_summaries": summaries},
        )
        return ok({"results": serializer.data, "count": qs.count()})

    def create(self, request, *args, **kwargs):
        if request.user.role == "ADMIN":
            raise ApiError(
                "Administrators do not create patient records — patient "
                "information is handled by healthcare workers.",
                code="ADMIN_PATIENT_WRITE_DENIED",
                status_code=403,
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = serializer.save(created_by=request.user)
        audit_svc.log_event(
            request, "PATIENT_CREATED", target_type="patient", target_id=str(patient.id),
            detail={"patient_code": patient.patient_code},
        )
        return ok(PatientProfileSerializer(patient).data, status=201)


class PatientDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH one patient record with authorization enforcement.

    Administrator responses are PII-redacted (code + clinical analytics only)
    and administrators cannot modify patient records."""

    serializer_class = PatientProfileSerializer

    def get_object(self):
        user = self.request.user
        profile = get_object_or_404(PatientProfile, pk=self.kwargs["pk"])
        if not can_access_patient(self.request.user, profile):
            raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
        # Attach the summary so detail responses carry current-risk context too.
        summaries = patient_summaries([profile.id])
        self.patient_summary = summaries.get(profile.id, {})
        return profile

    def get_serializer_context(self):
        context = super().get_serializer_context()
        summary = getattr(self, "patient_summary", {})
        context["patient_summaries"] = {self.kwargs["pk"]: summary} if summary else {}
        context["redact_pii"] = self.request.user.role == "ADMIN"
        return context

    def update(self, request, *args, **kwargs):
        if request.user.role == "ADMIN":
            raise ApiError(
                "Administrators do not modify patient records — patient "
                "information is handled by healthcare workers.",
                code="ADMIN_PATIENT_WRITE_DENIED",
                status_code=403,
            )
        partial = kwargs.pop("partial", False)
        profile = self.get_object()
        serializer = self.get_serializer(profile, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        audit_svc.log_event(
            request, "PATIENT_UPDATED", target_type="patient", target_id=str(updated.id),
            detail={"patient_code": updated.patient_code},
        )
        return ok(self.get_serializer(updated).data)


class PatientAssignmentListView(generics.ListCreateAPIView):
    """Legacy worker->patient assignment list.

    Creation is retired: every healthcare worker now sees all patients, so
    there is nothing left to assign. The GET list stays for audit/history of
    legacy assignments."""

    serializer_class = PatientAssignmentSerializer
    permission_classes = [IsAdmin]
    queryset = PatientAssignment.objects.select_related("patient", "healthcare_worker", "assigned_by").all()

    def perform_create(self, serializer):
        raise ApiError(
            "Patient assignments are retired — every healthcare worker can see "
            "all patients, so no assignment step is needed.",
            code="ASSIGNMENTS_RETIRED",
            status_code=403,
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
            r: User.objects.filter(role=r).count() for r in ("HEALTHCARE_WORKER", "ADMIN")
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
