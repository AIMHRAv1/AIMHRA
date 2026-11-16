"""Authentication and permission tests for the staff-only role model.

Patients are clinical records, never application users. Valid application
roles are HEALTHCARE_WORKER and ADMIN only.
"""
from accounts.models import User
from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken


def make_user(username, role="HEALTHCARE_WORKER", password="Str0ng!Pass1", **extra):
    return User.objects.create_user(
        username=username, email=f"{username}@test.com", password=password, role=role, **extra
    )


class RoleModelTests(TestCase):
    def test_only_two_application_roles_exist(self):
        self.assertFalse(hasattr(User, "ROLE_PATIENT"))
        self.assertEqual(
            {choice[0] for choice in User.ROLE_CHOICES},
            {"HEALTHCARE_WORKER", "ADMIN"},
        )

    def test_default_role_is_healthcare_worker(self):
        user = make_user("fresh")
        self.assertEqual(user.role, "HEALTHCARE_WORKER")


class AuthFlowTests(TestCase):
    def login(self, username, password):
        return self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            content_type="application/json",
        )

    def test_register_endpoint_is_gone(self):
        r = self.client.post(
            "/api/auth/register/",
            {"username": "u1", "email": "u1@t.com", "password": "Str0ng!Pass1", "confirm_password": "Str0ng!Pass1"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)

    def test_healthcare_worker_can_log_in(self):
        make_user("worker1", role="HEALTHCARE_WORKER")
        r = self.login("worker1", "Str0ng!Pass1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("access", body)
        self.assertIn("refresh", body)
        self.assertEqual(body["user"]["role"], "HEALTHCARE_WORKER")

    def test_admin_can_log_in(self):
        make_user("admin1", role="ADMIN")
        r = self.login("admin1", "Str0ng!Pass1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["role"], "ADMIN")

    def test_legacy_patient_role_cannot_log_in(self):
        # Legacy accounts (created before the role refactor) may still exist in
        # the database; role != HEALTHCARE_WORKER/ADMIN must be rejected.
        legacy = make_user("legacypat", role="PATIENT")
        legacy.is_active = True
        legacy.save(update_fields=["is_active"])
        r = self.login("legacypat", "Str0ng!Pass1")
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()["success"])

    def test_inactive_user_cannot_log_in(self):
        make_user("inactive1", is_active=False)
        r = self.login("inactive1", "Str0ng!Pass1")
        self.assertEqual(r.status_code, 401)

    def test_failed_login_returns_structured_error_and_audits(self):
        from audit.models import AuditLog

        make_user("worker2", role="HEALTHCARE_WORKER")
        r = self.login("worker2", "wrongpass")
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()["success"])
        self.assertTrue(AuditLog.objects.filter(action="LOGIN_FAILED").exists())

    def test_worker_token_refresh_works(self):
        user = make_user("worker3", role="HEALTHCARE_WORKER")
        refresh = RefreshToken.for_user(user)
        r = self.client.post(
            "/api/auth/refresh/",
            {"refresh": str(refresh)},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json())

    def test_legacy_patient_refresh_rejected(self):
        legacy = make_user("legacypat2", role="PATIENT")
        legacy.is_active = True
        legacy.save(update_fields=["is_active"])
        refresh = RefreshToken.for_user(legacy)
        r = self.client.post(
            "/api/auth/refresh/",
            {"refresh": str(refresh)},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 401)

    def test_legacy_patient_access_token_rejected(self):
        legacy = make_user("legacypat3", role="PATIENT")
        legacy.is_active = False
        legacy.save(update_fields=["is_active"])
        token = RefreshToken.for_user(legacy).access_token
        r = self.client.get("/api/auth/profile/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 401)

    def test_profile_requires_authentication(self):
        r = self.client.get("/api/auth/profile/")
        self.assertEqual(r.status_code, 401)

    def test_change_password(self):
        user = make_user("worker4", role="HEALTHCARE_WORKER")
        token = RefreshToken.for_user(user).access_token
        r = self.client.post(
            "/api/auth/change-password/",
            {"current_password": "Str0ng!Pass1", "new_password": "N3w!Pass99"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 200)
        r = self.login("worker4", "N3w!Pass99")
        self.assertEqual(r.status_code, 200)

    def test_admin_endpoints_forbidden_for_workers(self):
        user = make_user("worker5", role="HEALTHCARE_WORKER")
        token = RefreshToken.for_user(user).access_token
        r = self.client.get("/api/audit/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 403)
        r = self.client.get("/api/auth/users/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 403)

    def test_admin_user_management(self):
        make_user("rootadmin", role="ADMIN")
        token = RefreshToken.for_user(User.objects.get(username="rootadmin")).access_token
        r = self.client.get("/api/auth/users/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)
        roles = {u["role"] for u in r.json()["data"]["results"]}
        self.assertNotIn("PATIENT", roles)

    def test_only_superuser_can_create_or_deactivate_administrators(self):
        admin = make_user("ordinaryadmin", role="ADMIN")
        root = User.objects.create_superuser(
            username="rootuser", email="root@test.com", password="Str0ng!Pass1"
        )
        admin_token = RefreshToken.for_user(admin).access_token
        root_token = RefreshToken.for_user(root).access_token
        admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {admin_token}"}
        root_auth = {"HTTP_AUTHORIZATION": f"Bearer {root_token}"}

        rejected = self.client.post(
            "/api/auth/users/",
            {
                "username": "blockedadmin",
                "email": "blocked@test.com",
                "password": "Str0ng!Pass1",
                "role": "ADMIN",
            },
            content_type="application/json",
            **admin_auth,
        )
        self.assertEqual(rejected.status_code, 400, rejected.content)
        self.assertFalse(User.objects.filter(username="blockedadmin").exists())

        created = self.client.post(
            "/api/auth/users/",
            {
                "username": "newadmin",
                "email": "newadmin@test.com",
                "password": "Str0ng!Pass1",
                "role": "ADMIN",
            },
            content_type="application/json",
            **root_auth,
        )
        self.assertEqual(created.status_code, 201, created.content)

        rejected = self.client.patch(
            f"/api/auth/users/{admin.id}/",
            {"is_active": False},
            content_type="application/json",
            **admin_auth,
        )
        self.assertEqual(rejected.status_code, 400, rejected.content)
        self.assertTrue(User.objects.get(pk=admin.id).is_active)

        deactivated = self.client.patch(
            f"/api/auth/users/{admin.id}/",
            {"is_active": False},
            content_type="application/json",
            **root_auth,
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.content)

        protected = self.client.patch(
            f"/api/auth/users/{root.id}/",
            {"is_active": False},
            content_type="application/json",
            **root_auth,
        )
        self.assertEqual(protected.status_code, 400, protected.content)

    def test_admin_can_create_healthcare_worker(self):
        admin = make_user("workercreatoradmin", role="ADMIN")
        token = RefreshToken.for_user(admin).access_token
        response = self.client.post(
            "/api/auth/users/",
            {
                "username": "createdworker",
                "email": "createdworker@test.com",
                "password": "Str0ng!Pass1",
                "role": "HEALTHCARE_WORKER",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["role"], "HEALTHCARE_WORKER")

    def test_healthcare_worker_activity_groups_assessments_by_patient(self):
        from assessments.models import Assessment, Prediction
        from patients.models import PatientProfile

        worker = make_user("activityworker")
        admin = make_user("activityadmin", role="ADMIN")
        first_patient = PatientProfile.objects.create(patient_code="P-ACTIVITY1")
        second_patient = PatientProfile.objects.create(patient_code="P-ACTIVITY2")
        for patient, visit_date, risk in (
            (first_patient, "2026-09-01", "high risk"),
            (first_patient, "2026-09-10", "mid risk"),
            (second_patient, "2026-09-05", "low risk"),
        ):
            assessment = Assessment.objects.create(
                patient=patient,
                created_by=worker,
                visit_date=visit_date,
                age=28,
                body_temperature=98.4,
                heart_rate=86,
                systolic_bp=120,
                diastolic_bp=78,
                bmi=23,
                hba1c=38,
                fasting_glucose=5.5,
            )
            Prediction.objects.create(
                assessment=assessment,
                risk_level=risk,
                probability=0.9,
                probabilities={},
                explanation={},
                model_name="test-model",
                model_version="1",
            )

        token = RefreshToken.for_user(admin).access_token
        response = self.client.get(
            f"/api/auth/users/{worker.id}/activity/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertEqual(data["user"]["patients_handled"], 2)
        rows = {patient["patient_code"]: patient for patient in data["patients"]}
        self.assertEqual(rows["P-ACTIVITY1"]["assessment_count"], 2)
        self.assertEqual(rows["P-ACTIVITY1"]["last_assessed_date"], "2026-09-10")
        self.assertEqual(rows["P-ACTIVITY1"]["latest_risk"], "mid risk")
        listing = self.client.get(
            "/api/auth/users/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(listing.status_code, 200, listing.content)
        worker_row = next(
            row for row in listing.json()["data"]["results"] if row["id"] == worker.id
        )
        self.assertEqual(worker_row["patients_handled"], 2)

    def test_logout_blacklists_refresh(self):
        user = make_user("worker6", role="HEALTHCARE_WORKER")
        refresh = RefreshToken.for_user(user)
        token = refresh.access_token
        r = self.client.post(
            "/api/auth/logout/",
            {"refresh": str(refresh)},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            "/api/auth/refresh/",
            {"refresh": str(refresh)},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 401)