from django.conf import settings
from django.db import models


class ChatSession(models.Model):
    title = models.CharField(max_length=128, blank=True, default="New conversation")
    patient = models.ForeignKey(
        "patients.PatientProfile", on_delete=models.CASCADE, related_name="chat_sessions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="chat_sessions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class ChatMessage(models.Model):
    ROLE_USER = "USER"
    ROLE_ASSISTANT = "ASSISTANT"
    ROLE_CHOICES = ((ROLE_USER, "User"), (ROLE_ASSISTANT, "Assistant"))

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    # Pipeline metadata: rule outcome, RAG sources, generation mode.
    escalation = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=list, blank=True)
    generation_mode = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="llm | rag_only_fallback | escalation | no_llm_configured",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
