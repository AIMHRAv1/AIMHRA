from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.views import APIView

from chat.models import ChatMessage, ChatSession
from chat.services import respond
from core.exceptions import ApiError
from core.responses import ok
from patients.models import PatientProfile
from patients.selectors import can_access_patient


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ["id", "title", "patient", "created_at", "updated_at"]
        read_only_fields = ["id", "patient", "created_at", "updated_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "escalation", "sources", "generation_mode", "created_at"]


def _resolve_session(request, session_id):
    session = get_object_or_404(ChatSession.objects.select_related("patient"), pk=session_id)
    if not can_access_patient(request.user, session.patient):
        raise ApiError("You are not authorized to access this conversation.", code="PERMISSION_DENIED", status_code=403)
    return session


class SessionListCreateView(APIView):
    def get(self, request):
        user = request.user
        qs = ChatSession.objects.select_related("patient").order_by("-updated_at")
        if user.role == "PATIENT":
            profile = PatientProfile.objects.filter(user=user).first()
            qs = qs.filter(patient=profile) if profile else ChatSession.objects.none()
        elif user.role == "HEALTHCARE_WORKER":
            from patients.selectors import patient_ids_for_healthcare_worker

            qs = qs.filter(patient_id__in=patient_ids_for_healthcare_worker(user))
        else:
            qs = ChatSession.objects.none()
        return ok({"sessions": SessionSerializer(qs[:50], many=True).data})

    def post(self, request):
        raise ApiError("Patient chat is disabled.", code="PERMISSION_DENIED", status_code=403)


class SessionDetailView(APIView):
    def get(self, request, session_id):
        session = _resolve_session(request, session_id)
        messages = ChatMessage.objects.filter(session=session).order_by("created_at", "id")
        return ok({"session": SessionSerializer(session).data, "messages": MessageSerializer(messages, many=True).data})

    def delete(self, request, session_id):
        session = _resolve_session(request, session_id)
        if request.user.role != "PATIENT" and session.created_by_id != request.user.id:
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
