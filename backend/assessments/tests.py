"""Assessment workflow tests: validation, permissions, isolation, rule engine,
trends. Patients are standalone records owned/assigned to healthcare workers."""
import json
from datetime import date, datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
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


class AuthMixin:
    """JWT auth helper shared by API test classes."""

    def auth(self, user, client=None):
        from rest_framework_simplejwt.tokens import RefreshToken

        token = RefreshToken.for_user(user).access_token
        (client or self.client).credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return token


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

    def test_eclampsia_education_question_is_not_detected_as_convulsions(self):
        found = detect_symptoms("What is eclampsia and pre-eclampsia?")
        self.assertNotIn("convulsions", found)


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


class DecisionSupportTests(AuthMixin, TestCase):
    """Phase 2: structured decision_support with traceable guideline
    references. KB content is ingested through the normal /api/rag/ path."""

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
                name=r["name"], version=f"dstest-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"], features=r["bundle"]["features"],
                training_config={"quick": True}, metrics=r["test_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )
        cls.admin = make_user("dsadmin", role="ADMIN")
        cls.worker = make_user("dsworker")
        cls.profile = make_patient("DS Patient")
        cls.profile.created_by = cls.worker
        cls.profile.save(update_fields=["created_by"])

    def setUp(self):
        self.client = APIClient()
        self.auth(self.worker)
        admin_client = APIClient()
        self.auth(self.admin, client=admin_client)
        r = admin_client.post(
            "/api/rag/documents/",
            {"title": "DS Guideline", "source_url": "https://example.test/guideline",
             "content_text": (
                 "Severe hypertension in pregnancy, systolic blood pressure of 160 mm Hg or "
                 "more, requires urgent assessment at a health facility. Severe headache with "
                 "raised blood pressure is a warning sign that should be assessed the same day. "
                 "BMI of 30 or above in pregnancy is associated with increased risk and requires "
                 "tailored antenatal monitoring."
             )},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201, r.content)

    def _assess(self, **overrides):
        payload = {
            **VALID_PAYLOAD, "patient": self.profile.id, "systolic_bp": 165,
            "diastolic_bp": 105, "symptoms": ["severe_headache"], **overrides,
        }
        r = self.client.post("/api/assessments/", payload, content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["data"] or r.json()

    def test_decision_support_structure_and_references(self):
        data = self._assess()
        ds = data["decision_support"]
        # Clear separation of the three sources of support.
        self.assertEqual(ds["ml"]["risk_level"], data["risk_level"])
        self.assertEqual(ds["rules"]["category"], data["rules"]["category"])
        self.assertIn("not machine learning", ds["rules"]["note"])
        self.assertTrue(all("not a medical cause" in f["note"] for f in ds["ml"]["top_factors"]))
        # Rule triggers are cited against the ingested guideline.
        self.assertGreater(len(ds["references"]), 0)
        rule_ids = {r["topic_id"] for r in ds["references"] if r["topic_type"] == "rule"}
        self.assertIn("EMER-BP-HIGH", rule_ids)
        ref = ds["references"][0]
        self.assertEqual(ref["document_title"], "DS Guideline")
        self.assertEqual(ref["source_url"], "https://example.test/guideline")
        self.assertTrue(ref["document_sha256"])
        self.assertIn("chunk_index", ref)

    def test_references_persisted_on_prediction(self):
        data = self._assess()
        pred = Prediction.objects.get(assessment_id=data["assessment"]["id"])
        self.assertGreater(len(pred.explanation.get("references", [])), 0)

    def test_decision_support_survives_empty_kb(self):
        from kb.models import KnowledgeDocument

        KnowledgeDocument.objects.all().delete()
        data = self._assess()
        self.assertEqual(data["decision_support"]["references"], [])
        self.assertTrue(data["decision_support"]["reference_warnings"])
        self.assertIn(data["risk_level"], ("low risk", "mid risk", "high risk"))


class AssessmentAPITests(AuthMixin, TestCase):
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

    def test_registration_gestational_week_advances_for_assessment_date(self):
        self.auth(self.worker)
        self.profile.gestational_week_at_registration = 18
        self.profile.created_at = timezone.make_aware(datetime(2026, 8, 5, 12))
        self.profile.save(update_fields=["gestational_week_at_registration", "created_at"])

        response = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id, "visit_date": "2026-08-19"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["assessment"]["gestational_week"], 20)

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
        for field, value in [
            ("age", 300),
            ("body_temperature", 110),
            ("heart_rate", 999),
            ("systolic_bp", 200),
            ("diastolic_bp", 130),
        ]:
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

    def test_diastolic_equal_to_systolic_rejected(self):
        self.auth(self.worker)
        payload = {**VALID_PAYLOAD, "patient": self.profile.id, "systolic_bp": 100, "diastolic_bp": 100}
        r = self.client.post("/api/assessments/", payload, content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_age_must_match_patient_date_of_birth(self):
        self.auth(self.worker)
        self.profile.date_of_birth = date(2000, 1, 1)
        self.profile.save(update_fields=["date_of_birth"])
        payload = {**VALID_PAYLOAD, "patient": self.profile.id, "age": 28}
        response = self.client.post(
            "/api/assessments/", payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("age", response.json()["error"]["details"])

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

    def test_worker_can_assess_any_patient(self):
        # Policy: every health worker sees all patients — no assignment step.
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.other_profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(Assessment.objects.filter(patient=self.other_profile).exists())

    def test_worker_can_access_assigned_patient(self):
        self.auth(self.worker)
        r = self.client.get(f"/api/assessments/risk-history/?patient={self.assigned_profile.id}")
        self.assertEqual(r.status_code, 200)

    def test_worker_can_read_any_patient_history(self):
        # Policy: every health worker sees all patients.
        self.auth(self.worker)
        r = self.client.get(f"/api/assessments/risk-history/?patient={self.other_profile.id}")
        self.assertEqual(r.status_code, 200)

    def test_admin_cannot_perform_assessments(self):
        # Policy: administrators do not record patient assessments.
        self.auth(self.admin)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.other_profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Assessment.objects.filter(patient=self.other_profile).exists())

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

    def test_trend_shows_treating_workers_even_for_admin(self):
        # The administrator history view must show which health worker treated
        # the patient (worker names are not patient PII).
        Assessment.objects.all().delete()
        self.worker.full_name = "Dr. Treating Worker"
        self.worker.save(update_fields=["full_name"])
        self.auth(self.worker)
        self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id},
            content_type="application/json",
        )
        self.auth(self.admin)
        r = self.client.get(f"/api/assessments/risk-trends/?patient={self.profile.id}")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"] or r.json()
        self.assertIn("Dr. Treating Worker", data["treating_workers"])
        self.assertEqual(data["series"][0]["recorded_by"], "Dr. Treating Worker")

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
        self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id},
            content_type="application/json",
        )
        r = self.client.get("/api/assessments/")
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"] or r.json()
        self.assertEqual(data["results"][0]["patient_code"], self.profile.patient_code)

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

class MeasurementTrendTests(AuthMixin, TestCase):
    """Phase 3: measurement history, previous-vs-latest comparisons and the
    review-gated trend-rule engine. Trend rules are deterministic arithmetic
    checks, NOT machine learning."""

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
                name=r["name"], version=f"trtest-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"], features=r["bundle"]["features"],
                training_config={"quick": True}, metrics=r["test_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )
        cls.worker = make_user("trworker")
        cls.profile = make_patient("Trend Patient")
        cls.profile.created_by = cls.worker
        cls.profile.save(update_fields=["created_by"])

    def setUp(self):
        self.client = APIClient()
        self.auth(self.worker)

    def _assess(self, visit_date, systolic, diastolic, heart_rate=86):
        payload = {
            **VALID_PAYLOAD, "patient": self.profile.id, "visit_date": visit_date,
            "systolic_bp": systolic, "diastolic_bp": diastolic, "heart_rate": heart_rate,
        }
        r = self.client.post("/api/assessments/", payload, content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["data"] or r.json()

    def test_compare_measurements_arithmetic(self):
        from assessments.trends import compare_measurements, measurement_series

        self._assess("2026-08-01", 120, 80)
        self._assess("2026-08-15", 135, 78)
        series = measurement_series(self.profile)
        self.assertEqual(len(series["visits"]), 2)
        comparisons = compare_measurements(series)
        by_feature = {c["feature"]: c for c in comparisons}
        sbp = by_feature["systolic_bp"]
        self.assertEqual(sbp["previous_value"], 120.0)
        self.assertEqual(sbp["latest_value"], 135.0)
        self.assertEqual(sbp["delta"], 15.0)
        self.assertEqual(sbp["percent_change"], 12.5)
        self.assertEqual(sbp["direction"], "increased")
        dbp = by_feature["diastolic_bp"]
        self.assertEqual(dbp["delta"], -2.0)
        self.assertEqual(dbp["direction"], "decreased")

    def test_trend_engine_disabled_when_unreviewed(self):
        from assessments.rules import trend_engine

        self.assertFalse(trend_engine.trend_rules_active())
        comparisons = [{"feature": "systolic_bp", "delta": 40, "percent_change": 33.3, "direction": "increased"}]
        out = trend_engine.evaluate_trends(comparisons)
        self.assertFalse(out["active"])
        self.assertEqual(out["category"], "NORMAL")
        self.assertEqual(out["triggered"], [])

    def test_trend_engine_fires_only_when_reviewed(self):
        # Simulate a clinically reviewed ruleset: the same arithmetic then
        # fires deterministically. (Test-only fixture; the shipped file
        # stays PENDING_CLINICAL_REVIEW with empty thresholds.)
        import tempfile
        from assessments.rules import trend_engine
        from pathlib import Path

        reviewed = {
            "version": "trend-test", "review_status": "CLINICALLY_REVIEWED",
            "categories": {}, "messages": {"ATTENTION": "noted"},
            "rules": [{
                "id": "TREND-TEST-SBP", "category": "ATTENTION", "feature": "systolic_bp",
                "direction": "increased", "delta": 20, "op": ">=",
                "description": "Test-only systolic rise",
            }],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(reviewed, fh)
            path = Path(fh.name)
        original = trend_engine.TREND_RULES_FILE
        path2 = None
        trend_engine.TREND_RULES_FILE = path
        try:
            out = trend_engine.evaluate_trends(
                [{"feature": "systolic_bp", "delta": 25, "percent_change": 18.0, "direction": "increased"}],
                force_reload=True,
            )
            self.assertTrue(out["active"])
            self.assertEqual(out["category"], "ATTENTION")
            self.assertEqual(out["triggered"][0]["id"], "TREND-TEST-SBP")
            # Below-threshold and wrong-direction cases never fire.
            out2 = trend_engine.evaluate_trends(
                [{"feature": "systolic_bp", "delta": 10, "percent_change": 5.0, "direction": "increased"}],
                force_reload=True,
            )
            self.assertEqual(out2["triggered"], [])
            out3 = trend_engine.evaluate_trends(
                [{"feature": "systolic_bp", "delta": 30, "percent_change": 25.0, "direction": "decreased"}],
                force_reload=True,
            )
            self.assertEqual(out3["triggered"], [])
            # Unfilled threshold can never fire.
            unfilled = dict(reviewed, rules=[dict(reviewed["rules"][0], delta=None)])
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(unfilled, fh)
                path2 = Path(fh.name)
            trend_engine.TREND_RULES_FILE = path2
            out4 = trend_engine.evaluate_trends(
                [{"feature": "systolic_bp", "delta": 99, "percent_change": 50.0, "direction": "increased"}],
                force_reload=True,
            )
            self.assertEqual(out4["triggered"], [])
        finally:
            trend_engine.TREND_RULES_FILE = original
            path.unlink(missing_ok=True)
            if path2:
                path2.unlink(missing_ok=True)
            trend_engine.load_trend_rules(force=True)

    def test_assessment_response_includes_measurements_and_no_trend_alerts(self):
        from assessments.models import Alert

        self._assess("2026-08-01", 120, 80)
        data = self._assess("2026-08-15", 150, 95)
        mt = data["measurement_trend"]
        self.assertIn("not machine learning", mt["note"])
        self.assertFalse(mt["rules"]["active"])  # shipped ruleset is unreviewed
        self.assertEqual(mt["rules"]["category"], "NORMAL")
        cmp = {c["feature"]: c for c in mt["comparisons"]}["systolic_bp"]
        self.assertEqual(cmp["delta"], 30.0)
        # No trend alert may exist while the ruleset is unreviewed.
        self.assertFalse(Alert.objects.filter(rules_version__startswith="trend-").exists())

    def test_trend_view_returns_measurements(self):
        self._assess("2026-08-01", 120, 80)
        self._assess("2026-08-15", 135, 78)
        r = self.client.get(f"/api/assessments/risk-trends/?patient={self.profile.id}")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"] or r.json()
        self.assertIn("measurements", data)
        self.assertEqual(len(data["measurements"]["visits"]), 2)
        self.assertEqual(len(data["measurements"]["comparisons"]), 8)
        self.assertIn("measurement_rules", data)
