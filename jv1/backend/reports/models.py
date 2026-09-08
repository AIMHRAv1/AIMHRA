from django.db import models


class Report(models.Model):
    """A generated PDF report for one assessment. Not a medical document."""

    patient = models.ForeignKey(
        "patients.PatientProfile", on_delete=models.CASCADE, related_name="reports"
    )
    assessment = models.ForeignKey(
        "assessments.Assessment", on_delete=models.CASCADE, related_name="reports"
    )
    generated_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL, related_name="reports_generated"
    )
    file = models.FileField(upload_to="reports/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
