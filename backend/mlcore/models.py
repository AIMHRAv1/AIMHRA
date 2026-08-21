from django.db import models


class ModelVersion(models.Model):
    """Registry of trained models. One row per trained model; at most one
    row per model name carries status=PRODUCTION at a time."""

    STATUS_CANDIDATE = "CANDIDATE"
    STATUS_PRODUCTION = "PRODUCTION"
    STATUS_RETIRED = "RETIRED"
    STATUS_CHOICES = (
        (STATUS_CANDIDATE, "Candidate"),
        (STATUS_PRODUCTION, "Production"),
        (STATUS_RETIRED, "Retired"),
    )

    name = models.CharField(max_length=64, help_text="e.g. RandomForest, XGBoost")
    version = models.CharField(max_length=16)
    trained_at = models.DateTimeField(auto_now_add=True)
    dataset_version = models.CharField(max_length=64, help_text="md5 of the training CSV")
    features = models.JSONField(default=list)
    training_config = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict, help_text="Test-split metrics")
    validation_metrics = models.JSONField(default=dict, blank=True)
    artifact_path = models.CharField(max_length=512, blank=True, default="")
    selection_criterion = models.CharField(max_length=64, default="high_risk_recall_then_f1")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_CANDIDATE)

    class Meta:
        ordering = ["-trained_at"]
        unique_together = ("name", "version")
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.name} {self.version} [{self.status}]"
