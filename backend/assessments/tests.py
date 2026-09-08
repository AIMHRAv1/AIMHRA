"""Assessment workflow tests: validation, permissions, isolation, rule engine,
trends. Patients are standalone records owned/assigned to healthcare workers."""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Alert, Assessment, Prediction
from assessments.rules import evaluate as rules_evaluate
from assessments.rules.engine import load_rules
from assessments.rules.keywords import detect_symptoms
from assessments.trends import compute_trend
from patients.models import PatientAssignment, PatientProfile


VALID_PAYLOAD = {
    "visit_date": "2026-08-19", "gestational_week": 20,
    "age": 28, "body_temperature": 98.4, "heart_rate": 86,
    "systolic_bp": 120, "diastolic_bp": 78, "bmi": 23.0,
    "hba1c": 38.0, "fasting_glucose": 5.5,
    "symptoms": ["none"], "notes": "",
}


def make_user(username, role="HEALTHCARE_WORKER", password="Passw0rd!42"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password=password, role=role
    )


def make_patient(full_name="A Patient"):
    return PatientProfile.objects.create(full_name=full_name)


class RuleEngineTests(TestCase):
    def test_ruleset_loads_and_is_versioned(self):
        rules = load_rules(force=True)
        self.assertEqual(rules["version"], "v1")
        self.assertTrue(any(r["id"] == "EMER-BP-HIGH" for r in rules["rules"]))

    def test_severe_hypertension_is_emergency(self):
        out = rules_evaluate({"systolic_bp": 170, "diastolic_bp": 100}, [])
        self.assertEqual(out["category"], "EMERGENCY")
        self.assertTrue(out["escalate"])
        self.assertTrue(any(t["id"] == "EMER-BP-HIGH" for t in out["triggered"]))

    def test_symptom_emergency_bleeding(self):
        out = rules_evaluate({}, ["vaginal_bleeding"])
        self.assertEqual(out["category"], "EMERGENCY")

    def test_moderate_findings_are_high_concern(self):
        out = rules_evaluate({"systolic_bp": 145, "diastolic_bp": 92}, ["severe_headache"])
        self.assertEqual(out["category"], "HIGH_CONCERN")

    def test_normal_inputs_stay_normal(self):
        out = rules_evaluate(
            {"systolic_bp": 115, "diastolic_bp": 74, "heart_rate": 80, "body_temperature": 98.2, "bmi": 22}, []
        )
        self.assertEqual(out["category"], "NORMAL")
        self.assertFalse(out["escalate"])

    def test_unknown_symptoms_ignored(self):
        out = rules_evaluate({}, ["not_a_symptom"])
        self.assertEqual(out["category"], "NORMAL")

    def test_keyword_detection(self):
        found = detect_symptoms("I have a severe headache and I feel dizzy")
        self.assertIn("severe_headache", found)
        self.assertIn("dizziness_fainting", found)


class TrendTests(TestCase):
    def test_improving_direction(self):
        trend = compute_trend([
            {"risk_level": "mid risk"}, {"risk_level": "low risk"},
        ])
        self.assertEqual(trend["status"], "improving")
        self.assertEqual(trend["direction"], "decreasing")

    def test_increasing_sequence(self):
        trend = compute_trend([
            {"risk_level": "low risk"}, {"risk_level": "mid risk"}, {"risk_level": "high risk"},
        ])
        self.assertEqual(trend["status"], "increasing")
        self.assertEqual(trend["sequence"], ["low risk", "mid risk", "high risk"])

    def test_single_visit_is_baseline(self):
        trend = compute_trend([{"risk_level": "mid risk"}])
        self.assertEqual(trend["status"], "baseline")


class AssessmentAPITests(TestCase):
    """Full workflow tests against the real (quick-trained) production model."""

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
                name=r["name"], version=f"apitest-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"], features=r["bundle"]["features"],
                training_config={"quick": True}, metrics=r["test_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )

        cls.worker = make_user("worker1")
        cls.other_worker = make_user("worker2")
        cls.admin = make_user("admin1", role="ADMIN")
        cls.profile = make_patient("Owned Patient")
        cls.assigned_profile = make_patient("Assigned Patient")
        cls.other_profile = make_patient("Other Worker Patient")

        # worker1 created the first patient and is assigned the second.
        cls.profile.created_by = cls.worker
        cls.profile.save(update_fields=["created_by"])
        PatientAssignment.objects.create(healthcare_worker=cls.worker, patient=cls.assigned_profile)
        # other_worker created the third patient.
        cls.other_profile.created_by = cls.other_worker
        cls.other_profile.save(update_fields=["created_by"])

    def setUp(self):
        self.client = APIClient()

    def auth(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken

        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return token

    def test_worker_can_assess_patient_they_created(self):
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()["data"] or r.json()
        self.assertIn(data["risk_level"], ("low risk", "mid risk", "high risk"))
        self.assertTrue(Assessment.objects.filter(patient=self.profile).exists())
        self.assertTrue(Prediction.objects.filter(assessment__patient=self.profile).exists())

    def test_emergency_assessment_creates_alert(self):
        self.auth(self.worker)
        payload = {**VALID_PAYLOAD, "patient": self.profile.id, "systolic_bp": 172, "symptoms": ["severe_headache"]}
        r = self.client.post("/api/assessments/", payload, content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()["data"]
        self.assertEqual(data["rules"]["category"], "EMERGENCY")
        self.assertEqual(Alert.objects.filter(patient=self.profile, category="EMERGENCY").count(), 1)

    def test_shap_explanation_persisted(self):
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id},
            content_type="application/json",
        )
        pred = Prediction.objects.get(assessment_id=r.json()["data"]["assessment"]["id"])
        self.assertIn("features", pred.explanation)

    def test_out_of_range_values_rejected(self):
        self.auth(self.worker)
        for field, value in [("age", 300), ("heart_rate", 999), ("systolic_bp", -5)]:
            r = self.client.post(
                "/api/assessments/",
                {**VALID_PAYLOAD, "patient": self.profile.id, field: value},
                content_type="application/json",
            )
            self.assertEqual(r.status_code, 400, f"{field}={value} should fail")
            self.assertFalse(r.json().get("success", True))

    def test_diastolic_above_systolic_rejected(self):
        self.auth(self.worker)
        payload = {**VALID_PAYLOAD, "patient": self.profile.id, "systolic_bp": 100, "diastolic_bp": 120}
        r = self.client.post("/api/assessments/", payload, content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_unknown_symptom_rejected(self):
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id, "symptoms": ["alien_disease"]},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_future_visit_date_rejected(self):
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id, "visit_date": "2099-01-01"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_worker_cannot_assess_another_workers_patient(self):
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.other_profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Assessment.objects.filter(patient=self.other_profile).exists())

    def test_worker_can_access_assigned_patient(self):
        self.auth(self.worker)
        r = self.client.get(f"/api/assessments/risk-history/?patient={self.assigned_profile.id}")
        self.assertEqual(r.status_code, 200)

    def test_worker_cannot_read_unauthorized_patient(self):
        self.auth(self.worker)
        r = self.client.get(f"/api/assessments/risk-history/?patient={self.other_profile.id}")
        self.assertEqual(r.status_code, 403)

    def test_admin_can_assess_any_patient(self):
        self.auth(self.admin)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.other_profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201)

    def test_history_and_trend_endpoints(self):
        self.auth(self.worker)
        self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id},
            content_type="application/json",
        )
        r = self.client.get(f"/api/assessments/risk-history/?patient={self.profile.id}")
        data = r.json()["data"] or r.json()
        self.assertEqual(len(data["history"]), 1)
        r = self.client.get(f"/api/assessments/risk-trends/?patient={self.profile.id}")
        data = r.json()["data"] or r.json()
        self.assertEqual(data["trend"]["status"], "baseline")
        self.assertIn("does not predict future risk", data["disclaimer"])

    def test_trend_is_descriptive_not_predictive(self):
        self.auth(self.worker)
        for visit, bp in [("2026-07-01", 118), ("2026-08-01", 125)]:
            self.client.post(
                "/api/assessments/",
                {**VALID_PAYLOAD, "patient": self.profile.id, "visit_date": visit, "systolic_bp": bp},
                content_type="application/json",
            )
        r = self.client.get(f"/api/assessments/risk-trends/?patient={self.profile.id}")
        data = r.json()["data"] or r.json()
        self.assertEqual(data["trend"]["visits"], 2)
        self.assertIn(data["trend"]["status"], ("improving", "stable", "increasing"))
        self.assertIn("does not predict future risk", data["disclaimer"])

    def test_assessment_list_requires_patient_or_scopes_access(self):
        self.auth(self.worker)
        r = self.client.get("/api/assessments/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()["data"])

    def test_no_model_means_503_not_fabricated(self):
        from mlcore.models import ModelVersion

        ModelVersion.objects.all().delete()
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "MODEL_UNAVAILABLE")
        self.assertFalse(Assessment.objects.filter(patient=self.profile).exists())