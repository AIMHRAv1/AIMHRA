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
from assessments.trends import compute_measurement_trends, compute_trend
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

    def test_every_existing_rule_has_structured_recommendation_metadata(self):
        ruleset = load_rules(force=True)
        for rule in ruleset["rules"]:
            vitals = {}
            symptoms = []
            if rule["type"] == "symptom":
                symptoms = [rule["match"]]
            else:
                threshold = float(rule["value"])
                vitals[rule["feature"]] = threshold - 1 if rule["op"] == "<" else threshold

            outcome = rules_evaluate(vitals, symptoms)
            matches = [
                recommendation
                for entries in outcome["recommendations"].values()
                for recommendation in entries
                if rule["id"] in recommendation["triggering_rule_ids"]
            ]
            self.assertEqual(len(matches), 1, rule["id"])
            recommendation = matches[0]
            self.assertTrue(recommendation["title"])
            self.assertTrue(recommendation["explanation"])
            self.assertTrue(recommendation["priority"])
            self.assertTrue(recommendation["suggested_next_action"])
            self.assertIsNone(recommendation["supporting_source"])
            self.assertIn("No rule-specific", recommendation["source_status"])

    def test_recommendations_deduplicate_same_priority_and_keep_rule_traceability(self):
        outcome = rules_evaluate(
            {"systolic_bp": 170, "diastolic_bp": 110},
            ["vaginal_bleeding", "convulsions"],
        )
        urgent = outcome["recommendations"]["urgent_medical_attention"]
        self.assertEqual(len(urgent), 1)
        self.assertEqual(
            set(urgent[0]["triggering_rule_ids"]),
            {"EMER-CONVULSIONS", "EMER-BLEEDING", "EMER-BP-HIGH", "EMER-BP-DIA"},
        )
        self.assertEqual(urgent[0]["triggering_rule_id"], "EMER-CONVULSIONS")
        self.assertEqual(outcome["recommendations"]["further_assessment"], [])
        self.assertEqual(len(outcome["triggered"]), 6)

    def test_no_trigger_returns_all_recommendation_groups_empty(self):
        outcome = rules_evaluate({"heart_rate": 80}, [])
        self.assertEqual(outcome["recommendations"], {
            "routine_monitoring": [],
            "further_assessment": [],
            "medical_consultation": [],
            "urgent_medical_attention": [],
        })

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

    def test_latest_assessment_without_prediction_is_not_replaced_by_an_older_risk(self):
        trend = compute_trend([
            {"risk_level": "high risk"},
            {"risk_level": None},
        ])
        self.assertIsNone(trend["current"])
        self.assertEqual(trend["status"], "no_data")
        self.assertEqual(trend["sequence"], ["high risk"])

    def test_measurement_comparison_uses_existing_rules_only(self):
        changes = compute_measurement_trends([
            {
                "systolic_bp": 135, "diastolic_bp": 88, "heart_rate": 80,
                "body_temperature": 98.6, "bmi": 24, "hba1c": 38, "fasting_glucose": 5.2,
            },
            {
                "systolic_bp": 145, "diastolic_bp": 88, "heart_rate": 80,
                "body_temperature": 98.6, "bmi": 24, "hba1c": 40, "fasting_glucose": 5.2,
            },
        ])
        by_feature = {item["feature"]: item for item in changes}
        self.assertEqual(by_feature["systolic_bp"]["difference"], 10)
        self.assertEqual(by_feature["systolic_bp"]["direction"], "increased")
        self.assertEqual(
            [rule["id"] for rule in by_feature["systolic_bp"]["newly_triggered_rules"]],
            ["HC-BP-SYS"],
        )
        self.assertEqual(by_feature["heart_rate"]["direction"], "unchanged")
        self.assertEqual(by_feature["hba1c"]["difference"], 2)
        self.assertEqual(by_feature["hba1c"]["current_triggered_rules"], [])

    def test_measurement_comparison_handles_baseline_and_missing_values(self):
        baseline = compute_measurement_trends([{"systolic_bp": 120}])
        self.assertEqual(baseline[0]["direction"], "baseline")
        self.assertIsNone(baseline[0]["difference"])
        incomplete = compute_measurement_trends([
            {"systolic_bp": None},
            {"systolic_bp": 170},
        ])
        systolic = incomplete[0]
        self.assertEqual(systolic["direction"], "unavailable")
        self.assertEqual(systolic["rule_status"], "previous_value_unavailable")
        self.assertEqual(systolic["newly_triggered_rules"], [])


class AssessmentAPITests(TestCase):
    """Full workflow tests against the real (quick-trained) production model."""

    @classmethod
    def setUpTestData(cls):
        from django.conf import settings

        from mlcore.models import ModelVersion
        from mlcore.training import train_all

        outcome = train_all(settings.BASE_DIR / "data" / "Mathernal_Risk.csv",
                            settings.ML_ARTIFACTS_DIR, quick=True)
        best = next(r for r in outcome["results"] if r["name"] == outcome["selected_model"])
        for r in outcome["results"]:
            ModelVersion.objects.create(
                name=r["name"], version=f"apitest-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"], features=r["bundle"]["features"],
                training_config={"quick": True}, metrics=r["test_metrics"] or {},
                validation_metrics=r["validation_metrics"],
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
        self.assertEqual(data["prediction_status"], "available")
        self.assertTrue(Assessment.objects.filter(patient=self.profile).exists())
        self.assertTrue(Prediction.objects.filter(assessment__patient=self.profile).exists())

    def test_emergency_assessment_creates_alert(self):
        self.auth(self.worker)
        payload = {**VALID_PAYLOAD, "patient": self.profile.id, "systolic_bp": 172, "symptoms": ["severe_headache"]}
        r = self.client.post("/api/assessments/", payload, content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()["data"]
        self.assertEqual(data["rules"]["category"], "EMERGENCY")
        self.assertEqual(data["prediction_status"], "available")
        self.assertTrue(Prediction.objects.filter(assessment_id=data["assessment"]["id"]).exists())
        self.assertEqual(Alert.objects.filter(patient=self.profile, category="EMERGENCY").count(), 1)

    def test_new_patient_first_assessment_evaluates_current_symptoms(self):
        from unittest.mock import patch

        self.auth(self.worker)
        patient_response = self.client.post(
            "/api/patients/",
            {"full_name": "First assessment patient"},
            content_type="application/json",
        )
        self.assertEqual(patient_response.status_code, 201, patient_response.content)
        patient_id = patient_response.json()["data"]["id"]

        with patch(
            "assessments.services.rules_evaluate", wraps=rules_evaluate
        ) as evaluate:
            response = self.client.post(
                "/api/assessments/",
                {
                    **VALID_PAYLOAD,
                    "patient": patient_id,
                    "gestational_week": 24,
                    "symptoms": ["severe_headache"],
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        assessment = Assessment.objects.get(pk=data["assessment"]["id"])
        self.assertEqual(data["rules"]["category"], "HIGH_CONCERN")
        self.assertIn("HC-HEADACHE", [rule["id"] for rule in data["rules"]["triggered"]])
        self.assertEqual(assessment.symptoms, ["severe_headache"])
        self.assertEqual(assessment.recommendations, data["recommendations"])
        consultation = data["recommendations"]["medical_consultation"][0]
        self.assertIn("HC-HEADACHE", consultation["triggering_rule_ids"])
        self.assertIsNone(consultation["supporting_source"])
        history = self.client.get(
            f"/api/assessments/risk-trends/?patient={patient_id}"
        ).json()["data"]
        self.assertEqual(history["series"][0]["recommendations"], assessment.recommendations)
        rule_inputs, symptoms = evaluate.call_args.args
        self.assertEqual(rule_inputs["age"], 28)
        self.assertEqual(rule_inputs["gestational_week"], 24)
        self.assertEqual(symptoms, ["severe_headache"])

    def test_existing_patient_new_symptom_is_evaluated_on_that_visit(self):
        self.auth(self.worker)
        first = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id, "symptoms": ["none"]},
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 201, first.content)
        response = self.client.post(
            "/api/assessments/",
            {
                **VALID_PAYLOAD,
                "patient": self.profile.id,
                "visit_date": "2026-08-20",
                "symptoms": ["blurred_vision"],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        current = Assessment.objects.get(pk=data["assessment"]["id"])
        self.assertEqual(current.symptoms, ["blurred_vision"])
        self.assertIn("HC-VISION", [rule["id"] for rule in data["rules"]["triggered"]])
        self.assertEqual(Assessment.objects.filter(patient=self.profile).count(), 2)

    def test_existing_patient_no_new_symptoms_does_not_repeat_old_trigger(self):
        self.auth(self.worker)
        previous = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id, "symptoms": ["vaginal_bleeding"]},
            content_type="application/json",
        )
        self.assertEqual(previous.status_code, 201, previous.content)
        current = self.client.post(
            "/api/assessments/",
            {
                **VALID_PAYLOAD,
                "patient": self.profile.id,
                "visit_date": "2026-08-20",
                "symptoms": ["none"],
            },
            content_type="application/json",
        )

        self.assertEqual(current.status_code, 201, current.content)
        current_data = current.json()["data"]
        current_assessment = Assessment.objects.get(pk=current_data["assessment"]["id"])
        previous_assessment = Assessment.objects.get(
            pk=previous.json()["data"]["assessment"]["id"]
        )
        self.assertEqual(current_data["rules"]["triggered"], [])
        self.assertEqual(current_assessment.symptoms, [])
        self.assertEqual(previous_assessment.symptoms, ["vaginal_bleeding"])
        self.assertEqual(Alert.objects.filter(assessment=previous_assessment).count(), 1)
        self.assertFalse(Alert.objects.filter(assessment=current_assessment).exists())

    def test_multiple_symptoms_trigger_all_applicable_symptom_rules(self):
        self.auth(self.worker)
        response = self.client.post(
            "/api/assessments/",
            {
                **VALID_PAYLOAD,
                "patient": self.profile.id,
                "symptoms": ["convulsions", "vaginal_bleeding", "persistent_vomiting"],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        assessment = Assessment.objects.get(pk=response.json()["data"]["assessment"]["id"])
        alert = Alert.objects.get(assessment=assessment)
        self.assertEqual(
            set(alert.rule_id.split(",")),
            {"EMER-CONVULSIONS", "EMER-BLEEDING", "ATT-VOMITING"},
        )
        self.assertEqual(
            set(assessment.symptoms),
            {"convulsions", "vaginal_bleeding", "persistent_vomiting"},
        )

    def test_prediction_failure_does_not_prevent_rule_alert_persistence(self):
        from unittest.mock import patch

        from mlcore.exceptions import ModelUnavailableError

        self.auth(self.worker)
        with patch(
            "assessments.services.model_predict",
            side_effect=ModelUnavailableError("No production model is registered."),
        ):
            response = self.client.post(
                "/api/assessments/",
                {
                    **VALID_PAYLOAD,
                    "patient": self.profile.id,
                    "systolic_bp": 145,
                    "symptoms": ["severe_headache"],
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        assessment = Assessment.objects.get(pk=data["assessment"]["id"])
        self.assertEqual(data["prediction_status"], "unavailable")
        self.assertIn("no ML risk classification", data["prediction_message"])
        self.assertIsNone(data["risk_level"])
        self.assertIsNone(data["model"])
        self.assertFalse(Prediction.objects.filter(assessment=assessment).exists())
        alert = Alert.objects.get(assessment=assessment)
        self.assertEqual(alert.category, "HIGH_CONCERN")
        self.assertIn("HC-BP-SYS", alert.rule_id)
        self.assertIn("HC-HEADACHE", alert.rule_id)

    def test_all_triggered_rules_are_persisted_for_assessment(self):
        self.auth(self.worker)
        response = self.client.post(
            "/api/assessments/",
            {
                **VALID_PAYLOAD,
                "patient": self.profile.id,
                "systolic_bp": 172,
                "diastolic_bp": 110,
                "body_temperature": 104,
                "heart_rate": 140,
                "bmi": 30,
                "symptoms": [
                    "severe_headache", "vaginal_bleeding", "persistent_vomiting",
                    "dizziness_fainting", "fever", "swelling_face_hands",
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        assessment = Assessment.objects.get(pk=response.json()["data"]["assessment"]["id"])
        alert = Alert.objects.get(assessment=assessment)
        persisted_ids = alert.rule_id.split(",")
        self.assertEqual(
            set(persisted_ids),
            {
                "EMER-BLEEDING", "EMER-BP-HIGH", "EMER-BP-DIA", "EMER-TEMP", "EMER-HR-HIGH",
                "HC-HEADACHE", "HC-SWELLING", "HC-BP-SYS", "HC-BP-DIA", "HC-HR-HIGH",
                "HC-FEVER", "ATT-VOMITING", "ATT-DIZZINESS", "ATT-FEVER-SYMPTOM",
                "ATT-BMI-HIGH",
            },
        )
        self.assertGreater(len(persisted_ids), 5)
        self.assertEqual(len(alert.rule_description.split("; ")), len(persisted_ids))
        self.assertGreater(len(alert.rule_description), 255)
        self.assertEqual(alert.category, "EMERGENCY")

    def test_assessment_without_triggered_rules_does_not_create_alert(self):
        self.auth(self.worker)
        response = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["rules"]["triggered"], [])
        self.assertFalse(Alert.objects.filter(patient=self.profile).exists())

    def test_alert_can_be_acknowledged_and_resolved(self):
        self.auth(self.worker)
        response = self.client.post(
            "/api/assessments/",
            {
                **VALID_PAYLOAD,
                "patient": self.profile.id,
                "systolic_bp": 172,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        alert = Alert.objects.get(patient=self.profile)

        acknowledged = self.client.post(
            f"/api/assessments/alerts/{alert.id}/ack/",
            {"status": "ACKNOWLEDGED"},
            content_type="application/json",
        )
        self.assertEqual(acknowledged.status_code, 200, acknowledged.content)
        self.assertEqual(acknowledged.json()["data"]["alert"]["status"], "ACKNOWLEDGED")

        resolved = self.client.post(
            f"/api/assessments/alerts/{alert.id}/ack/",
            {"status": "RESOLVED"},
            content_type="application/json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.content)
        self.assertEqual(resolved.json()["data"]["alert"]["status"], "RESOLVED")

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

    def test_worker_can_assess_shared_patient(self):
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.other_profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Assessment.objects.filter(patient=self.other_profile).exists())
        self.assertEqual(r.json()["data"]["assessment"]["assessed_by"], self.worker.username)

    def test_worker_can_access_assigned_patient(self):
        self.auth(self.worker)
        r = self.client.get(f"/api/assessments/risk-history/?patient={self.assigned_profile.id}")
        self.assertEqual(r.status_code, 200)

    def test_worker_can_read_shared_patient(self):
        self.auth(self.worker)
        r = self.client.get(f"/api/assessments/risk-history/?patient={self.other_profile.id}")
        self.assertEqual(r.status_code, 200)

    def test_admin_cannot_assess_patient(self):
        self.auth(self.admin)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.other_profile.id},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

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

    def test_history_returns_measurements_in_chronological_patient_scope(self):
        self.auth(self.worker)
        common = {
            key: value for key, value in VALID_PAYLOAD.items()
            if key not in ("visit_date", "systolic_bp")
        }
        Assessment.objects.create(
            patient=self.profile, visit_date="2026-08-01", systolic_bp=120, **common
        )
        Assessment.objects.create(patient=self.profile, visit_date="2026-07-01", **common, systolic_bp=135)
        Assessment.objects.create(
            patient=self.other_profile, visit_date="2026-06-01", systolic_bp=110, **common
        )

        response = self.client.get(f"/api/assessments/risk-trends/?patient={self.profile.id}")
        data = response.json()["data"] or response.json()
        self.assertEqual(
            [item["visit_date"] for item in data["series"]],
            ["2026-07-01", "2026-08-01"],
        )
        self.assertEqual(data["series"][0]["systolic_bp"], 135)
        self.assertEqual(data["measurement_trends"][0]["difference"], -15)
        self.assertIsNone(data["series"][0]["risk_level"])

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

    def test_no_model_still_saves_assessment_without_fabricated_prediction(self):
        from mlcore.models import ModelVersion

        ModelVersion.objects.all().delete()
        self.auth(self.worker)
        r = self.client.post(
            "/api/assessments/",
            {**VALID_PAYLOAD, "patient": self.profile.id, "systolic_bp": 172},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()["data"]
        self.assertEqual(data["prediction_status"], "unavailable")
        self.assertIsNone(data["risk_level"])
        self.assertTrue(Assessment.objects.filter(patient=self.profile).exists())
        self.assertEqual(Alert.objects.get(patient=self.profile).category, "EMERGENCY")
        self.assertFalse(Prediction.objects.filter(assessment__patient=self.profile).exists())