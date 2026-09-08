from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user with a single role.

    PATIENT: retained for legacy data; new patient records do not require accounts.
    HEALTHCARE_WORKER: sees patients explicitly assigned to them.
    ADMIN: manages users, models, knowledge base, audit logs.
    """

    ROLE_PATIENT = "PATIENT"
    ROLE_HEALTHCARE_WORKER = "HEALTHCARE_WORKER"
    ROLE_ADMIN = "ADMIN"
    ROLE_CHOICES = (
        (ROLE_PATIENT, "Patient"),
        (ROLE_HEALTHCARE_WORKER, "Healthcare worker"),
        (ROLE_ADMIN, "Administrator"),
    )

    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_PATIENT)
    phone = models.CharField(max_length=32, blank=True, default="")
    # Required on registration so admins can review who signed up.
    full_name = models.CharField(max_length=128, blank=True, default="")

    def save(self, *args, **kwargs):
        # Staff flag is derived from role; admins never come from self-registration.
        self.is_staff = self.role == self.ROLE_ADMIN
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return self.role == self.ROLE_ADMIN
