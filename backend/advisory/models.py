from django.conf import settings
from django.db import models

from assessments.models import Assessment
from patients.models import PatientProfile


class Advisory(models.Model):
    """Persisted care advice for one assessment, produced by the same
    pipeline as the chatbot (rules -> RAG -> offline generation)."""

    assessment = models.OneToOneField(Assessment, related_name="advisory", on_delete=models.CASCADE)
    patient = models.ForeignKey(PatientProfile, related_name="advisories", on_delete=models.CASCADE)
    content = models.TextField()
    risk_level = models.CharField(max_length=16)
    rules_category = models.CharField(max_length=16)
    sources = models.JSONField(default=list, blank=True)
    generation_mode = models.CharField(
        max_length=24,
        help_text="local_llm | rag_only_fallback | no_llm_configured",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="advisories", null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Advisory(assessment={self.assessment_id}, risk={self.risk_level})"
