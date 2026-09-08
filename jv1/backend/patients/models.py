import uuid

from django.conf import settings
from django.db import models


def generate_patient_code():
    """Short opaque public identifier (e.g. P-7F3A9C21) so internal DB ids
    and names are not exposed through list endpoints."""
    return f"P-{uuid.uuid4().hex[:8].upper()}"


class PatientProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patient_profile",
        null=True, blank=True,
    )
    patient_code = models.CharField(max_length=16, unique=True, default=generate_patient_code)
    # Created by a healthcare worker or administrator on behalf of a patient.
    full_name = models.CharField(max_length=128, blank=True, default="")
    phone_number = models.CharField(max_length=32, blank=True, default="")
    emergency_contact_number = models.CharField(max_length=32, blank=True, default="")
    district = models.CharField(max_length=128, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    blood_group = models.CharField(max_length=8, blank=True, default="")
    gestational_week_at_registration = models.PositiveSmallIntegerField(null=True, blank=True)
    estimated_due_date = models.DateField(null=True, blank=True)
    gravidity = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Total pregnancies, including current.")
    parity = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Births after 20 weeks' gestation.")
    medical_history_notes = models.TextField(blank=True, default="")
    allergies = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["patient_code"])]

    def __str__(self):
        return self.patient_code


class PatientAssignment(models.Model):
    """Explicit authorization: a healthcare worker can only access patients
    assigned to them. Created by administrators."""

    healthcare_worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assigned_patients",
        limit_choices_to={"role": "HEALTHCARE_WORKER"},
    )
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="assigned_workers"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assignments_made", limit_choices_to={"role": "ADMIN"},
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("healthcare_worker", "patient")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.healthcare_worker_id} -> {self.patient_id}"
