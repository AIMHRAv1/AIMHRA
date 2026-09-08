"""Authentication and permission tests."""
from accounts.models import User
from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken


class AuthFlowTests(TestCase):
    def register(self, username="user1"):
        return self.client.post("/api/auth/register/", {
            "username": username, "email": f"{username}@test.com", "full_name": "Test",
            "password": "Str0ng!Pass1", "confirm_password": "Str0ng!Pass1",
        }, content_type="application/json")

    def login(self, username, password):
        return self.client.post("/api/auth/login/", {"username": username, "password": password},
                                content_type="application/json")

    def test_register_creates_patient_role(self):
        r = self.register()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.get(username="user1").role, "PATIENT")

    def test_register_rejects_mismatched_passwords(self):
        r = self.client.post("/api/auth/register/", {
            "username": "u2", "email": "u2@t.com", "password": "Str0ng!Pass1",
            "confirm_password": "different", "full_name": "x",
        }, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["success"])

    def test_register_rejects_weak_password(self):
        r = self.client.post("/api/auth/register/", {
            "username": "u3", "email": "u3@t.com", "password": "123", "confirm_password": "123",
            "full_name": "x",
        }, content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_login_issues_jwt_and_user_payload(self):
        self.register()
        r = self.login("user1", "Str0ng!Pass1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json())
        self.assertIn("refresh", r.json())

    def test_failed_login_returns_structured_error_and_audits(self):
        from audit.models import AuditLog

        self.register()
        r = self.login("user1", "wrongpass")
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()["success"])
        self.assertTrue(AuditLog.objects.filter(action="LOGIN_FAILED").exists())

    def test_token_refresh(self):
        self.register()
        refresh = RefreshToken.for_user(User.objects.get(username="user1"))
        r = self.client.post("/api/auth/refresh/", {"refresh": str(refresh)},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json())

    def test_profile_requires_authentication(self):
        r = self.client.get("/api/patients/me/")
        self.assertEqual(r.status_code, 401)

    def test_change_password(self):
        self.register()
        token = RefreshToken.for_user(User.objects.get(username="user1")).access_token
        r = self.client.post("/api/auth/change-password/", {
            "current_password": "Str0ng!Pass1", "new_password": "N3w!Pass99",
        }, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.login("user1", "N3w!Pass99") .status_code, 200)

    def test_admin_endpoints_forbidden_for_patients(self):
        self.register()
        token = RefreshToken.for_user(User.objects.get(username="user1")).access_token
        r = self.client.get("/api/audit/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 403)
        r = self.client.get("/api/auth/users/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 403)

    def test_admin_user_management(self):
        User.objects.create_user(username="rootadmin", email="r@t.com", password="Adm1n!Pass9", role="ADMIN")
        token = RefreshToken.for_user(User.objects.get(username="rootadmin")).access_token
        r = self.client.get("/api/auth/users/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)

    def test_logout_blacklists_refresh(self):
        self.register()
        user = User.objects.get(username="user1")
        refresh = RefreshToken.for_user(user)
        token = refresh.access_token
        r = self.client.post("/api/auth/logout/", {"refresh": str(refresh)},
                             content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/api/auth/refresh/", {"refresh": str(refresh)}, content_type="application/json")
        self.assertEqual(r.status_code, 401)
