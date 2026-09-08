from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields["role"] = self.model.ROLE_ADMIN
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Application user with a single role.

    HEALTHCARE_WORKER: manages patient records, assessments, alerts and reports.
    ADMIN: manages users, models, knowledge base, audit logs and all patient data.
    """

    ROLE_HEALTHCARE_WORKER = "HEALTHCARE_WORKER"
    ROLE_ADMIN = "ADMIN"
    ROLE_CHOICES = (
        (ROLE_HEALTHCARE_WORKER, "Healthcare worker"),
        (ROLE_ADMIN, "Administrator"),
    )

    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_HEALTHCARE_WORKER)
    phone = models.CharField(max_length=32, blank=True, default="")
    # Required on registration so admins can review who signed up.
    full_name = models.CharField(max_length=128, blank=True, default="")

    objects = UserManager()

    def save(self, *args, **kwargs):
        # Django superusers must also be application administrators.
        if self.is_superuser:
            self.role = self.ROLE_ADMIN
        self.is_staff = self.role == self.ROLE_ADMIN
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return self.role == self.ROLE_ADMIN
