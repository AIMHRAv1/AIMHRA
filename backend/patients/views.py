from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.views import APIView

from audit import services as audit_svc
from core.exceptions import ApiError
from core.permissions import IsAdmin, IsHealthcareWorkerOnly, IsPatientListAccess
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

    GET  /api/patients/   - scoped list (search: code/name/phone/email)
    POST /api/patients/   - create a standalone patient record. The creator is
                            automatically granted access (no admin step needed).
    """

    serializer_class = PatientProfileSerializer
    permission_classes = [IsPatientListAccess]

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
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = serializer.save(created_by=request.user)
        audit_svc.log_event(
            request, "PATIENT_CREATED", target_type="patient", target_id=str(patient.id),
            detail={"patient_code": patient.patient_code},
        )
        return ok(
            PatientProfileSerializer(
                patient, context=self.get_serializer_context()
            ).data,
            status=201,
        )


class PatientDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH one patient record with authorization enforcement."""

    serializer_class = PatientProfileSerializer
    permission_classes = [IsHealthcareWorkerOnly]

    def get_object(self):
        user = self.request.user
        profile = get_object_or_404(
            PatientProfile.objects.prefetch_related("assigned_workers"),
            pk=self.kwargs["pk"],
        )
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
        return context

    def update(self, request, *args, **kwargs):
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


class AdminPatientHistoryView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        from assessments.models import Assessment

        patient = get_object_or_404(PatientProfile, pk=pk)
        assessments = Assessment.objects.filter(patient=patient).select_related(
            "created_by", "prediction"
        ).order_by("-visit_date", "-id")
        return ok({
            "patient": {
                "id": patient.id,
                "patient_code": patient.patient_code,
                "assessment_count": assessments.count(),
            },
            "assessments": [
                {
                    "id": assessment.id,
                    "visit_date": assessment.visit_date.isoformat(),
                    "risk_level": getattr(assessment.prediction, "risk_level", None),
                    "assessed_by": (
                        assessment.created_by.full_name or assessment.created_by.username
                        if assessment.created_by else None
                    ),
                }
                for assessment in assessments
            ],
        })


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
