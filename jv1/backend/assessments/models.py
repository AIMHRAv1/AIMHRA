from django.conf import settings
from django.db import models

from mlcore.constants import FEATURES


class Assessment(models.Model):
    """One maternal health assessment (a visit). Stores the raw validated
    inputs; the derived prediction lives on the related Prediction row."""

    patient = models.ForeignKey(
        "patients.PatientProfile", on_delete=models.CASCADE, related_name="assessments"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="assessments_entered"
    )
    visit_date = models.DateField()
    gestational_week = models.PositiveSmallIntegerField(null=True, blank=True)
    # The 8 model features (names match mlcore.constants.FEATURES).
    age = models.FloatField()
    body_temperature = models.FloatField()
    heart_rate = models.FloatField()
    systolic_bp = models.FloatField()
    diastolic_bp = models.FloatField()
    bmi = models.FloatField()
    hba1c = models.FloatField()
    fasting_glucose = models.FloatField()
    # Fixed vocabulary of self-reported symptoms (rule-engine input).
    symptoms = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["visit_date", "id"]
        indexes = [models.Index(fields=["patient", "visit_date"])]

    def feature_values(self):
        return {f: getattr(self, f) for f in FEATURES}


class Prediction(models.Model):
    """Model output for one assessment, pinned to the exact model version."""

    assessment = models.OneToOneField(
        Assessment, on_delete=models.CASCADE, related_name="prediction"
    )
    risk_level = models.CharField(max_length=16, choices=[(l, l) for l in ("low risk", "mid risk", "high risk")])
    probability = models.FloatField(help_text="Confidence for the predicted class (0-1).")
    probabilities = models.JSONField(default=dict, help_text="Per-class probabilities.")
    explanation = models.JSONField(default=dict, help_text="SHAP feature contributions.")
    model_name = models.CharField(max_length=64)
    model_version = models.CharField(max_length=16)
    model_ref = models.ForeignKey(
        "mlcore.ModelVersion", null=True, on_delete=models.SET_NULL, related_name="predictions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Alert(models.Model):
    """Deterministic rule-engine outcome for an assessment."""

    CATEGORY_NORMAL = "NORMAL"
    CATEGORY_ATTENTION = "ATTENTION"
    CATEGORY_HIGH_CONCERN = "HIGH_CONCERN"
    CATEGORY_EMERGENCY = "EMERGENCY"
    CATEGORY_CHOICES = (
        (CATEGORY_NORMAL, "Normal"),
        (CATEGORY_ATTENTION, "Attention"),
        (CATEGORY_HIGH_CONCERN, "High concern"),
        (CATEGORY_EMERGENCY, "Emergency"),
    )
    STATUS_CHOICES = (("OPEN", "Open"), ("ACKNOWLEDGED", "Acknowledged"), ("RESOLVED", "Resolved"))

    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="alerts"
    )
    patient = models.ForeignKey(
        "patients.PatientProfile", on_delete=models.CASCADE, related_name="alerts"
    )
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    rule_id = models.CharField(max_length=64, blank=True, default="")
    rule_description = models.CharField(max_length=255, blank=True, default="")
    message = models.TextField()
    rules_version = models.CharField(max_length=16, default="v1")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="OPEN")
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="alerts_acknowledged",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "status"]), models.Index(fields=["category"])]
