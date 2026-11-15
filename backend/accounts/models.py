from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    """Manages the single-role user model.

    Superusers are created from the command line only, so ``createsuperuser``
    (and ``create_superuser`` in general) makes an ADMIN; everyone else starts
    as a HEALTHCARE_WORKER created by an admin.
    """

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", self.model.ROLE_ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Application user with a single role.

    HEALTHCARE_WORKER: manages patient records, assessments, alerts and reports.
    ADMIN: manages users, models, knowledge base, audit logs and all patient data.
    """

    objects = UserManager()

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

    def save(self, *args, **kwargs):
        # Staff flag is derived from role; admins never come from self-registration.
        self.is_staff = self.role == self.ROLE_ADMIN
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return self.role == self.ROLE_ADMIN
