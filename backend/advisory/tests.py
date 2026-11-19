"""Advisory pipeline tests: chatbot-pipeline advice per assessment, warn-then-
advise on emergency assessments, safe offline fallback and access control."""
from unittest.mock import patch

from accounts.models import User
from assessments.models import Assessment
from django.test import TestCase, override_settings
from patients.models import PatientProfile
from rest_framework_simplejwt.tokens import RefreshToken

KB_TEXT = (
    "During pregnancy, a balanced diet with iron and folate supports healthy blood "
    "levels. Elevated blood pressure in pregnancy should be monitored closely, with "
    "reduced salt intake, rest, and regular antenatal check-ups. Contact a healthcare "
    "professional if blood pressure readings stay high or headaches and blurred vision "
    "appear."
)

EMERGENCY_KB_TEXT = (
    "Heavy vaginal bleeding in pregnancy is an emergency. While arranging emergency "
    "care, the patient should lie on her side, stay calm, avoid drinking or eating, "
    "and have someone stay with her. Note the amount of bleeding and any clots to "
    "report to the medical team. Do not take any medication unless instructed by a "
    "clinician. Transport to the nearest hospital as quickly and smoothly as possible."
)

VITALS = {
    "age": 27, "body_temperature": 98.4, "heart_rate": 88, "systolic_bp": 118,
    "diastolic_bp": 76, "bmi": 23.1, "hba1c": 36, "fasting_glucose": 5.2,
}

EMERGENCY_VITALS = {
    "age": 34, "body_temperature": 98.9, "heart_rate": 118, "systolic_bp": 172,
    "diastolic_bp": 112, "bmi": 26.0, "hba1c": 45, "fasting_glucose": 7.8,
}


@override_settings(LLM_BASE_URL="")  # force the offline fallback path in tests
class AdvisoryPipelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.conf import settings

        from mlcore.models import ModelVersion
        from mlcore.training import train_all

        outcome = train_all(settings.BASE_DIR / "data" / "Mathernal_Risk.csv",
                            settings.ML_ARTIFACTS_DIR, quick=True)
        best = max(outcome["results"], key=lambda r: r["test_metrics"]["f1_macro"])
        for r in outcome["results"]:
            ModelVersion.objects.create(
                name=r["name"], version=f"advtest-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"], features=r["bundle"]["features"],
                training_config={"quick": True}, metrics=r["test_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )
        cls.worker = User.objects.create_user(
            username="advworker", email="a@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        cls.other_worker = User.objects.create_user(
            username="advworker2", email="a2@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        cls.admin = User.objects.create_user(
            username="advadmin", email="aa@t.com", password="Adm1n!Pass9", role="ADMIN"
        )
        cls.profile = PatientProfile.objects.create(full_name="Adv Patient", created_by=cls.worker)
        cls.other_profile = PatientProfile.objects.create(full_name="Other Patient", created_by=cls.other_worker)

    def setUp(self):
        token = RefreshToken.for_user(self.worker).access_token
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        admin_token = RefreshToken.for_user(self.admin).access_token
        self.admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {admin_token}"}

    def _upload_kb(self, title, text):
        r = self.client.post(
            "/api/rag/documents/",
            {"title": title, "content_text": text},
            content_type="application/json",
            **self.admin_auth,
        )
        self.assertEqual(r.status_code, 201, r.content)

    def _create_assessment(self, patient, vitals, symptoms=None):
        r = self.client.post(
            "/api/assessments/",
            {"patient": patient.id, "visit_date": "2026-11-12", **vitals, "symptoms": symptoms or []},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json().get("data") or r.json()
        return data, Assessment.objects.get(pk=data["assessment"]["id"])

    def _generate(self, assessment_id, auth=None):
        return self.client.post(
            "/api/advisory/", {"assessment": assessment_id},
            content_type="application/json", **(auth or self.auth),
        )

    def test_worker_gets_detailed_advice_for_low_risk(self):
        self._upload_kb("Pregnancy Care Guidance", KB_TEXT)
        data, assessment = self._create_assessment(self.profile, VITALS)
        r = self._generate(assessment.id)
        self.assertEqual(r.status_code, 201, r.content)
        advisory = (r.json().get("data") or r.json())["advisory"]
        self.assertEqual(advisory["assessment"], assessment.id)
        self.assertEqual(advisory["risk_level"], data["risk_level"])
        self.assertIn("disclaimer", advisory)
        self.assertTrue(advisory["content"].strip())
        self.assertIn(advisory["generation_mode"], ("rag_only_fallback", "no_llm_configured"))
        self.assertTrue(any(s["document_title"] == "Pregnancy Care Guidance" for s in advisory["sources"]))
        # Regeneration replaces, never duplicates.
        r2 = self._generate(assessment.id)
        self.assertEqual(r2.status_code, 201)
        from advisory.models import Advisory

        self.assertEqual(Advisory.objects.filter(assessment_id=assessment.id).count(), 1)

    def test_get_stored_advisory_and_empty_case(self):
        _data, assessment = self._create_assessment(self.profile, VITALS)
        r = self.client.get(f"/api/advisory/detail/?assessment={assessment.id}", **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone((r.json().get("data") or r.json())["advisory"])
        self._generate(assessment.id)
        r2 = self.client.get(f"/api/advisory/detail/?assessment={assessment.id}", **self.auth)
        self.assertIsNotNone((r2.json().get("data") or r2.json())["advisory"])

    def test_emergency_assessment_warns_then_advises(self):
        self._upload_kb("Bleeding Emergency Guidance", EMERGENCY_KB_TEXT)
        _data, assessment = self._create_assessment(
            self.profile, EMERGENCY_VITALS, symptoms=["vaginal_bleeding"]
        )
        r = self._generate(assessment.id)
        self.assertEqual(r.status_code, 201, r.content)
        advisory = (r.json().get("data") or r.json())["advisory"]
        content = advisory["content"].lower()
        self.assertEqual(advisory["generation_mode"], "escalation")
        self.assertEqual(advisory["rules_category"], "EMERGENCY")
        # The warning comes first and is never softened...
        self.assertIn("do not wait", content)
        self.assertIn("nearest hospital", content)
        self.assertLess(content.find("do not wait"), content.find("the care steps below"))
        # ...but the advice on what to do is still present.
        self.assertTrue(len(content) > 300)

    def test_high_model_risk_is_not_labeled_normal_without_symptoms(self):
        _data, assessment = self._create_assessment(self.profile, VITALS)
        prediction = assessment.prediction
        prediction.risk_level = "high risk"
        prediction.probability = 0.87
        prediction.save(update_fields=["risk_level", "probability"])

        with (
            patch("advisory.services.rag.retrieve_context", return_value={"chunks": []}),
            patch("advisory.services.generate_answer", return_value=("Care guidance.", "local_llm")) as generate,
        ):
            response = self._generate(assessment.id)

        self.assertEqual(response.status_code, 201, response.content)
        advisory = response.json()["data"]["advisory"]
        self.assertEqual(advisory["risk_level"], "high risk")
        self.assertEqual(advisory["rules_category"], "NORMAL")
        self.assertEqual(advisory["advisory_category"], "HIGH_CONCERN")
        self.assertIn("classified this assessment as **high risk**", advisory["content"])
        self.assertIn("model classified this assessment as high risk", generate.call_args.args[0])

    def test_high_concern_rule_is_distinct_from_low_model_risk_and_not_emergency(self):
        _data, assessment = self._create_assessment(
            self.profile,
            {**VITALS, "systolic_bp": 145, "diastolic_bp": 92},
        )
        prediction = assessment.prediction
        prediction.risk_level = "low risk"
        prediction.probability = 0.87
        prediction.save(update_fields=["risk_level", "probability"])

        with (
            patch("advisory.services.rag.retrieve_context", return_value={"chunks": []}),
            patch("advisory.services.generate_answer", return_value=("Care guidance.", "local_llm")),
        ):
            response = self._generate(assessment.id)

        self.assertEqual(response.status_code, 201, response.content)
        advisory = response.json()["data"]["advisory"]
        self.assertEqual(advisory["risk_level"], "low risk")
        self.assertEqual(advisory["rules_category"], "HIGH_CONCERN")
        self.assertEqual(advisory["advisory_category"], "HIGH_CONCERN")
        self.assertEqual(advisory["rule_findings"][0]["id"], "HC-BP-SYS")
        self.assertIn("Separate rule check: High Concern", advisory["content"])
        self.assertNotIn("do not wait", advisory["content"].lower())
        self.assertNotEqual(advisory["generation_mode"], "escalation")

    def test_advisory_generator_receives_assessment_notes_symptoms_and_measurements(self):
        _data, assessment = self._create_assessment(
            self.profile, VITALS, symptoms=["persistent_vomiting"]
        )
        assessment.notes = "Reports difficulty keeping fluids down."
        assessment.save(update_fields=["notes"])
        assessment.patient.gestational_week_at_registration = 18
        assessment.patient.blood_group = "O+"
        assessment.patient.medical_history_notes = "History of gestational diabetes."
        assessment.patient.allergies = "Penicillin."
        assessment.patient.current_medications = "Folic acid."
        assessment.patient.additional_notes = "Needs interpreter support."
        assessment.patient.save(update_fields=[
            "gestational_week_at_registration", "blood_group", "medical_history_notes",
            "allergies", "current_medications", "additional_notes",
        ])

        with (
            patch("advisory.services.rag.retrieve_context", return_value={"chunks": []}),
            patch("advisory.services.generate_answer", return_value=("Care guidance.", "local_llm")) as generate,
        ):
            response = self._generate(assessment.id)

        self.assertEqual(response.status_code, 201, response.content)
        context = generate.call_args.kwargs["patient_context"]
        self.assertIn("Reports difficulty keeping fluids down.", context)
        self.assertIn("symptoms recorded: persistent vomiting", context)
        self.assertIn("systolic blood pressure 118.0 mm Hg", context)
        self.assertIn("blood group (entered clinical data", context)
        self.assertIn("History of gestational diabetes.", context)
        self.assertIn("Penicillin.", context)
        self.assertIn("Needs interpreter support.", context)
        retrieval_query = generate.call_args.args[0]
        self.assertIn("medical history: History of gestational diabetes", retrieval_query)
        self.assertIn("gestational week 18", retrieval_query)

    def test_non_worker_cannot_generate_or_read(self):
        # Policy: workers see all patients; only non-worker roles are denied.
        _data, assessment = self._create_assessment(self.profile, VITALS)
        stranger = User.objects.create_user(
            username="advpatient", email="ap@t.com", password="Str0ng!Pass1", role="PATIENT"
        )
        stranger_auth = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(stranger).access_token}"}
        r = self._generate(assessment.id, auth=stranger_auth)
        self.assertEqual(r.status_code, 403)
        r2 = self.client.get(f"/api/advisory/detail/?assessment={assessment.id}", **stranger_auth)
        self.assertEqual(r2.status_code, 403)

    def test_assessment_required(self):
        r = self.client.post("/api/advisory/", {}, content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 400)
