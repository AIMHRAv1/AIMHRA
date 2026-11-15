"""Patient-record management tests: standalone records owned by healthcare
workers, created via API, scoped by access control."""
from django.test import TestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from patients.models import PatientAssignment, PatientProfile


def make_user(username, role="HEALTHCARE_WORKER", password="Passw0rd!42"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password=password, role=role
    )


def token_for(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


VALID_PATIENT = {
    "full_name": "Example Patient",
    "email": "patient@example.com",
    "phone": "+977XXXXXXXXXX",
    "date_of_birth": "1998-05-12",
    "blood_group": "O+",
    "gestational_week_at_registration": 24,
    "estimated_due_date": "2026-12-20",
    "gravidity": 2,
    "parity": 1,
    "medical_history_notes": "",
    "allergies": "",
    "address": "Kathmandu",
    "emergency_contact_name": "Spouse",
    "emergency_contact_phone": "+9779000000000",
    "obstetric_history_notes": "Previous uneventful pregnancy.",
    "current_medications": "Folic acid 5mg",
    "additional_notes": "Prefers morning visits.",
}


class PatientApiTests(TestCase):
    def setUp(self):
        self.worker = make_user("worker1")
        self.other_worker = make_user("worker2")
        self.admin = make_user("admin1", role="ADMIN")
        self.worker_auth = token_for(self.worker)
        self.other_auth = token_for(self.other_worker)
        self.admin_auth = token_for(self.admin)

    def test_worker_can_create_patient(self):
        r = self.client.post(
            "/api/patients/",
            VALID_PATIENT,
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()["data"]
        self.assertTrue(data["patient_code"].startswith("P-"))
        self.assertEqual(data["full_name"], "Example Patient")
        self.assertEqual(data["created_by"], self.worker.id)
        self.assertEqual(data["current_medications"], "Folic acid 5mg")

        patient = PatientProfile.objects.get(pk=data["id"])
        self.assertEqual(patient.created_by_id, self.worker.id)
        self.assertTrue(patient.is_active)

    def test_patient_code_is_generated_server_side(self):
        r = self.client.post(
            "/api/patients/",
            {"full_name": "No Code"},
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["data"]["patient_code"].startswith("P-"))

    def test_patient_creation_is_audited(self):
        from audit.models import AuditLog

        self.client.post(
            "/api/patients/",
            VALID_PATIENT,
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="PATIENT_CREATED", user=self.worker, target_type="patient"
            ).exists()
        )

    def test_worker_cannot_create_patient_unauthenticated(self):
        r = self.client.post(
            "/api/patients/",
            VALID_PATIENT,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 401)

    def test_worker_can_update_own_patient(self):
        patient = PatientProfile.objects.create(full_name="Old", created_by=self.worker)
        r = self.client.patch(
            f"/api/patients/{patient.id}/",
            {"full_name": "Updated Name", "emergency_contact_name": "New EC"},
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertEqual(r.status_code, 200, r.content)
        patient.refresh_from_db()
        self.assertEqual(patient.full_name, "Updated Name")
        self.assertEqual(patient.emergency_contact_name, "New EC")

    def test_worker_can_access_any_patient(self):
        # Policy: every health worker sees all patients — no assignment step.
        patient = PatientProfile.objects.create(full_name="Owned By Other", created_by=self.other_worker)
        r = self.client.get(f"/api/patients/{patient.id}/", **self.worker_auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["full_name"], "Owned By Other")

    def test_worker_can_access_assigned_patient(self):
        patient = PatientProfile.objects.create(full_name="Assigned", created_by=self.other_worker)
        PatientAssignment.objects.create(healthcare_worker=self.worker, patient=patient)
        r = self.client.get(f"/api/patients/{patient.id}/", **self.worker_auth)
        self.assertEqual(r.status_code, 200)

    def test_admin_can_access_all_patients(self):
        PatientProfile.objects.create(full_name="A1", created_by=self.worker)
        PatientProfile.objects.create(full_name="A2", created_by=self.other_worker)
        r = self.client.get("/api/patients/", **self.admin_auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["count"], 2)

    def test_worker_automatically_sees_all_patients(self):
        # Policy: workers see every patient record, not just their own.
        PatientProfile.objects.create(full_name="Mine", created_by=self.worker)
        PatientProfile.objects.create(full_name="Not Mine", created_by=self.other_worker)
        r = self.client.get("/api/patients/", **self.worker_auth)
        names = {p["full_name"] for p in r.json()["data"]["results"]}
        self.assertEqual(names, {"Mine", "Not Mine"})

    def test_search_by_code_name_phone_email(self):
        PatientProfile.objects.create(full_name="Searchable Person", phone="+9771234567", email="s@e.com")
        for term in ["Searchable", "+9771234567", "s@e.com", "P-"]:
            r = self.client.get(f"/api/patients/?search={term}", **self.admin_auth)
            self.assertEqual(r.status_code, 200)
            results = r.json()["data"]["results"]
            self.assertEqual(len(results), 1, term)
            # matching still works on stored values, but the admin response
            # itself stays PII-redacted
            self.assertIsNone(results[0]["full_name"], term)
            self.assertTrue(results[0]["patient_code"].startswith("P-"), term)

    def test_blood_group_validated(self):
        r = self.client.post(
            "/api/patients/",
            {**VALID_PATIENT, "blood_group": "ZZ"},
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertEqual(r.status_code, 400)

    def test_blood_group_without_rh_factor_accepted(self):
        # "AB" (Rh unknown) is legitimate clinical input and must not 400.
        r = self.client.post(
            "/api/patients/",
            {**VALID_PATIENT, "blood_group": "AB"},
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["data"]["blood_group"], "AB")

    def test_invalid_blood_group_returns_readable_message(self):
        r = self.client.post(
            "/api/patients/",
            {**VALID_PATIENT, "blood_group": "ZZ"},
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("Blood group", r.json()["error"]["message"])

    def test_creating_user_cannot_pick_created_by(self):
        r = self.client.post(
            "/api/patients/",
            {**VALID_PATIENT, "created_by": self.admin.id},
            content_type="application/json",
            **self.worker_auth,
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["data"]["created_by"], self.worker.id)


class PatientStatTests(TestCase):
    def test_system_stats_have_no_patient_role(self):
        make_user("w", role="HEALTHCARE_WORKER")
        make_user("a", role="ADMIN")
        admin = User.objects.get(username="a")
        r = self.client.get("/api/admin/stats/", **token_for(admin))
        self.assertEqual(r.status_code, 200)
        by_role = r.json()["data"]["users"]["by_role"]
        self.assertNotIn("PATIENT", by_role)
        self.assertEqual(set(by_role), {"HEALTHCARE_WORKER", "ADMIN"})

class AdminPatientPrivacyTests(TestCase):
    """Administrators must NOT see patient information, but keep access to
    clinical analytics (history, trends, reports) via code + summary fields."""

    def setUp(self):
        self.worker = make_user("pworker1")
        self.admin = make_user("padmin1", role="ADMIN")
        self.worker_auth = token_for(self.worker)
        self.admin_auth = token_for(self.admin)
        self.patient = PatientProfile.objects.create(
            full_name="Private Person", email="p@e.com", phone="+9779000000001",
            date_of_birth="1998-05-12", blood_group="O+", address="Kathmandu",
            emergency_contact_name="Spouse", medical_history_notes="note",
            gestational_week_at_registration=24, created_by=self.worker,
        )

    def test_admin_detail_is_redacted_but_code_and_analytics_remain(self):
        r = self.client.get(f"/api/patients/{self.patient.id}/", **self.admin_auth)
        self.assertEqual(r.status_code, 200)
        data = r.json()  # detail endpoint returns the plain serializer payload
        for field in ("full_name", "email", "phone", "address", "date_of_birth",
                      "blood_group", "gestational_week_at_registration",
                      "emergency_contact_name", "medical_history_notes"):
            self.assertIsNone(data[field], field)
        self.assertEqual(data["patient_code"], self.patient.patient_code)
        self.assertIn("current_risk", data)
        self.assertIn("assessment_count", data)

    def test_admin_list_is_redacted(self):
        r = self.client.get("/api/patients/", **self.admin_auth)
        self.assertEqual(r.status_code, 200)
        results = r.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["full_name"])
        self.assertEqual(results[0]["patient_code"], self.patient.patient_code)

    def test_worker_still_sees_full_patient_information(self):
        r = self.client.get(f"/api/patients/{self.patient.id}/", **self.worker_auth)
        self.assertEqual(r.status_code, 200)
        data = r.json()  # detail endpoint returns the plain serializer payload
        self.assertEqual(data["full_name"], "Private Person")
        self.assertEqual(data["phone"], "+9779000000001")

    def test_admin_cannot_update_patient(self):
        r = self.client.patch(
            f"/api/patients/{self.patient.id}/",
            {"full_name": "Changed Name"},
            content_type="application/json",
            **self.admin_auth,
        )
        self.assertEqual(r.status_code, 403)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.full_name, "Private Person")

    def test_admin_cannot_create_patient(self):
        r = self.client.post(
            "/api/patients/",
            {**VALID_PATIENT},
            content_type="application/json",
            **self.admin_auth,
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(PatientProfile.objects.count(), 1)


class AdminAssignmentRetiredTests(TestCase):
    """Administrators can no longer assign patients to health workers —
    every worker sees all patients, so the assignment step is retired."""

    def setUp(self):
        self.admin = make_user("asgadmin", role="ADMIN")
        self.worker = make_user("asgworker")
        self.admin_auth = token_for(self.admin)

    def test_admin_cannot_create_assignment(self):
        patient = PatientProfile.objects.create(full_name="P", created_by=self.worker)
        r = self.client.post(
            "/api/patients/assignments/",
            {"healthcare_worker": self.worker.id, "patient": patient.id},
            content_type="application/json",
            **self.admin_auth,
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(PatientAssignment.objects.count(), 0)
