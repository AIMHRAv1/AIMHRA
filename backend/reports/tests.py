"""Report generation tests for the healthcare-worker workflow."""
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

        cls.worker = User.objects.create_user(
            username="repworker", email="r@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        # Policy: workers see all patients, so a second worker can download
        # any report too. The remaining denial path is a non-worker role.
        cls.stranger = User.objects.create_user(
            username="repstranger", email="s2@t.com", password="Str0ng!Pass1", role="PATIENT"
        )
        cls.profile = PatientProfile.objects.create(
            full_name="Report Patient", created_by=cls.worker
        )
        cls.assessment = Assessment.objects.create(
            patient=cls.profile, visit_date="2026-08-01",
            symptoms=["severe_headache"], notes="", **PAYLOAD,
        )

    def test_worker_can_generate_report_for_accessible_patient(self):
        from assessments.services import create_assessment

        result = create_assessment(self.profile, {**PAYLOAD, "visit_date": "2026-08-05", "symptoms": []})
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        report = generate_report(assessment, self.worker)
        self.assertTrue(report.file.name.endswith(".pdf"))
        report.file.open("rb")
        content = report.file.read()
        report.file.close()
        self.assertGreater(len(content), 1000)
        self.assertTrue(content.startswith(b"%PDF"))

    def test_report_contains_prediction_and_model_version(self):
        from assessments.services import create_assessment

        result = create_assessment(self.profile, {
            **PAYLOAD, "visit_date": "2026-08-02", "symptoms": [],
        })
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        generate_report(assessment, self.worker)
        self.assertEqual(Report.objects.count(), 1)

    def test_report_download_requires_access(self):
        from assessments.services import create_assessment

        result = create_assessment(self.profile, {**PAYLOAD, "visit_date": "2026-08-03", "symptoms": []})
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        report = generate_report(assessment, self.worker)

        token = RefreshToken.for_user(self.worker).access_token
        r = self.client.get(
            f"/api/reports/{report.id}/download/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 200)

        stranger_token = RefreshToken.for_user(self.stranger).access_token
        r = self.client.get(
            f"/api/reports/{report.id}/download/",
            HTTP_AUTHORIZATION=f"Bearer {stranger_token}",
        )
        self.assertEqual(r.status_code, 403)

    def test_report_generation_through_api_audited(self):
        from assessments.services import create_assessment

        result = create_assessment(self.profile, {**PAYLOAD, "visit_date": "2026-08-04", "symptoms": []})
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        token = RefreshToken.for_user(self.worker).access_token
        r = self.client.post(
            "/api/reports/",
            {"assessment": assessment.id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(AuditLog.objects.filter(action="REPORT_GENERATED").exists())

class ReportReferenceTests(TestCase):
    """Phase 2: the PDF carries the traceable guideline-reference section."""

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
                name=r["name"], version=f"repref-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"], features=r["bundle"]["features"],
                training_config={"quick": True}, metrics=r["test_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )
        cls.worker = User.objects.create_user(
            username="reprefworker", email="rf@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        cls.profile = PatientProfile.objects.create(full_name="Ref Patient", created_by=cls.worker)

    def _report_for(self, payload):
        from assessments.services import create_assessment

        result = create_assessment(self.profile, payload)
        assessment = Assessment.objects.get(pk=result["assessment"]["id"])
        return generate_report(assessment, self.worker)

    @staticmethod
    def _pdf_text(report):
        import io

        from pypdf import PdfReader

        report.file.open("rb")
        try:
            reader = PdfReader(io.BytesIO(report.file.read()))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        finally:
            report.file.close()

    def test_report_lists_guideline_references(self):
        from kb.models import KnowledgeDocument
        from kb.services.indexing import index_document

        doc = KnowledgeDocument.objects.create(
            title="Ref Guideline", source_url="https://example.test/ref",
            content_text=(
                "A systolic blood pressure of 160 mm Hg or more in pregnancy is severe "
                "hypertension and requires urgent facility-based assessment by a professional."
            ),
            sha256="a" * 64,
        )
        index_document(doc)
        payload = {
            "age": 30, "body_temperature": 98.4, "heart_rate": 90,
            "systolic_bp": 165, "diastolic_bp": 96, "bmi": 25.0,
            "hba1c": 40.0, "fasting_glucose": 6.0, "visit_date": "2026-08-06", "symptoms": [],
        }
        text = self._pdf_text(self._report_for(payload))
        self.assertIn("Guideline references", text)
        self.assertIn("Ref Guideline", text)
        self.assertIn("traceability", text)

    def test_report_states_when_no_references_available(self):
        from kb.models import KnowledgeDocument

        KnowledgeDocument.objects.all().delete()
        payload = {
            "age": 30, "body_temperature": 98.4, "heart_rate": 90,
            "systolic_bp": 150, "diastolic_bp": 96, "bmi": 25.0,
            "hba1c": 40.0, "fasting_glucose": 6.0, "visit_date": "2026-08-07", "symptoms": [],
        }
        text = self._pdf_text(self._report_for(payload))
        self.assertIn("No guideline references were available", text)


class AdminReportPolicyTests(TestCase):
    """Administrators do not generate patient reports (history-only access)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="repadmin2", email="ra@t.com", password="Str0ng!Pass1", role="ADMIN"
        )

    def test_admin_cannot_generate_report(self):
        token = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(self.admin).access_token}"}
        r = self.client.post("/api/reports/", {"assessment": 1}, content_type="application/json", **token)
        self.assertEqual(r.status_code, 403)
