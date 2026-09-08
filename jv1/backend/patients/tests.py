from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from patients.models import PatientAssignment, PatientProfile


class PatientRecordAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.worker = User.objects.create_user(username="worker", password="Passw0rd!42", role="HEALTHCARE_WORKER")
        self.admin = User.objects.create_user(username="admin", password="Passw0rd!42", role="ADMIN")

    def test_worker_creates_accountless_patient_and_assignment(self):
        self.client.force_authenticate(self.worker)
        response = self.client.post("/api/patients/create/", {"full_name": "Asha", "district": "Kaski"}, format="json")
        self.assertEqual(response.status_code, 201)
        patient = PatientProfile.objects.get(full_name="Asha")
        self.assertIsNone(patient.user)
        self.assertTrue(PatientAssignment.objects.filter(healthcare_worker=self.worker, patient=patient).exists())

    def test_admin_cannot_view_patient_detail(self):
        patient = PatientProfile.objects.create(full_name="Private record")
        self.client.force_authenticate(self.admin)
        response = self.client.get(f"/api/patients/{patient.id}/")
        self.assertEqual(response.status_code, 403)

    def test_admin_patient_list_is_empty(self):
        PatientProfile.objects.create(full_name="Private record")
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/patients/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["results"], [])
