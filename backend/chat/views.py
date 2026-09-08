from audit.services import log_event
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.views import APIView

from chat.models import ChatMessage, ChatSession
from chat.services import respond
from core.exceptions import ApiError
from core.responses import ok
from patients.models import PatientProfile
from patients.selectors import can_access_patient, patient_ids_for_healthcare_worker


class SessionSerializer(serializers.ModelSerializer):
    creator_username = serializers.CharField(source="created_by.username", read_only=True, default="")

    class Meta:
        model = ChatSession
        fields = ["id", "title", "patient", "creator_username", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "escalation", "sources", "generation_mode", "created_at"]


def _resolve_session(request, session_id):
    session = get_object_or_404(ChatSession.objects.select_related("patient"), pk=session_id)
    if not can_access_patient(request.user, session.patient):
        raise ApiError("You are not authorized to access this conversation.", code="PERMISSION_DENIED", status_code=403)
    return session


def _resolve_patient_for_session(request, patient_id):
    if not patient_id:
        raise ApiError("`patient` is required to create a conversation.", code="VALIDATION_ERROR", status_code=400)
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    if not can_access_patient(request.user, patient):
        raise ApiError("You are not authorized to access this patient.", code="PERMISSION_DENIED", status_code=403)
    return patient


class SessionListCreateView(APIView):
    def get(self, request):
        user = request.user
        qs = ChatSession.objects.select_related("patient").order_by("-updated_at")
        if user.role == "HEALTHCARE_WORKER":
            qs = qs.filter(patient_id__in=patient_ids_for_healthcare_worker(user))
        patient_id = request.query_params.get("patient")
        if patient_id:
            _resolve_patient_for_session(request, patient_id)
            qs = qs.filter(patient_id=patient_id)
        return ok({"sessions": SessionSerializer(qs[:50], many=True).data})

    def post(self, request):
        patient = _resolve_patient_for_session(request, request.data.get("patient"))
        serializer = SessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = ChatSession.objects.create(
            patient=patient, created_by=request.user,
            title=serializer.validated_data.get("title") or "New conversation",
        )
        log_event(
            request, "CHAT_ACCESS", target_type="chat_session", target_id=str(session.id),
            detail={"patient": patient.id, "action": "session_created"},
        )
        return ok({"session": SessionSerializer(session).data}, status=201)


class SessionDetailView(APIView):
    def get(self, request, session_id):
        session = _resolve_session(request, session_id)
        messages = ChatMessage.objects.filter(session=session).order_by("created_at", "id")
        return ok({"session": SessionSerializer(session).data, "messages": MessageSerializer(messages, many=True).data})

    def delete(self, request, session_id):
        session = _resolve_session(request, session_id)
        if session.created_by_id != request.user.id and request.user.role != "ADMIN":
            raise ApiError("Only the session owner can delete it.", code="PERMISSION_DENIED", status_code=403)
        session.delete()
        return ok({"deleted": True})


class SendMessageView(APIView):
    """Main chatbot endpoint: message -> safety pipeline -> answer."""

    def post(self, request, session_id):
        session = _resolve_session(request, session_id)
        text = (request.data.get("message") or "").strip()
        if not text:
            raise ApiError("`message` is required.", code="VALIDATION_ERROR", status_code=400)
        if len(text) > 4000:
            raise ApiError("Message is too long (max 4000 characters).", code="VALIDATION_ERROR", status_code=400)
        if not session.title or session.title == "New conversation":
            session.title = text[:60]
            session.save(update_fields=["title"])
        result = respond(session, text, request=request)
        return ok({"reply": result})
