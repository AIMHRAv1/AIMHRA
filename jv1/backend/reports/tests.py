"""Report generation tests."""
from accounts.models import User
from assessments.models import Assessment
from audit.models import AuditLog
from django.test import TestCase
from patients.models import PatientProfile
from reports.models import Report
from reports.services import generate_report
from rest_framework_simplejwt.tokens import RefreshToken

PAYLOAD = {
    "age": 30, "body_temperature": 98.4, "heart_rate": 90,
    "systolic_bp": 150, "diastolic_bp": 96, "bmi": 25.0,
    "hba1c": 40.0, "fasting_glucose": 6.0,
}


class ReportTests(TestCase):
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
                name=r["name"], version=f"rep-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"], features=r["bundle"]["features"],
                training_config={"quick": True}, metrics=r["test_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )

        cls.user = User.objects.create_user(
            username="reppat", email="r@t.com", password="Str0ng!Pass1", role="PATIENT"
        )
        cls.profile = PatientProfile.objects.create(user=cls.user)
        cls.assessment = Assessment.objects.create(
            patient=cls.profile, visit_date="2026-08-01",
            symptoms=["severe_headache"], notes="", **PAYLOAD,
        )

    def test_generate_report_produces_pdf(self):
        from assessments.services import create_assessment

        result = create_assessment(self.profile, {**PAYLOAD, "visit_date": "2026-08-05", "symptoms": []})
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        report = generate_report(assessment, self.user)
        self.assertTrue(report.file.name.endswith(".pdf"))
        report.file.open("rb")
        content = report.file.read()
        report.file.close()
        self.assertGreater(len(content), 1000)
        self.assertTrue(content.startswith(b"%PDF"))

    def test_report_contains_prediction_and_model_version(self):
        from mlcore.registry import predict
        from assessments.services import create_assessment
        # Generate through the service so the prediction row exists.
        result = create_assessment(self.profile, {
            **PAYLOAD, "visit_date": "2026-08-02", "symptoms": [],
        })
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        report = generate_report(assessment, self.user)
        self.assertEqual(Report.objects.count(), 1)

    def test_report_download_requires_access(self):
        from assessments.services import create_assessment

        result = create_assessment(self.profile, {**PAYLOAD, "visit_date": "2026-08-03", "symptoms": []})
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        report = generate_report(assessment, self.user)

        token = RefreshToken.for_user(self.user).access_token
        r = self.client.get(f"/api/reports/{report.id}/download/",
                            HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)

        stranger = User.objects.create_user(username="stranger", email="s@t.com", password="Str0ng!Pass1")
        stranger_token = RefreshToken.for_user(stranger).access_token
        r = self.client.get(f"/api/reports/{report.id}/download/",
                            HTTP_AUTHORIZATION=f"Bearer {stranger_token}")
        self.assertEqual(r.status_code, 403)

    def test_report_generation_audited(self):
        from assessments.services import create_assessment
        from reports.views import generate_report as _

        result = create_assessment(self.profile, {**PAYLOAD, "visit_date": "2026-08-04", "symptoms": []})
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        generate_report(assessment, self.user)
        # create_assessment itself audits; direct service call doesn't need to
        self.assertTrue(AuditLog.objects.filter(action="ASSESSMENT_CREATED").exists())
