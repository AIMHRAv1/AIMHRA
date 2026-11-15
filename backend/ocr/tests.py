"""OCR feature tests.

The OCR engine layer is mocked for endpoint tests — Tesseract is NOT required
to run this suite. The PDF direct-text path is exercised for real (PyMuPDF,
no Tesseract needed).
"""
import io

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from assessments.models import Assessment
from audit.models import AuditLog
from django.core.files.uploadedfile import SimpleUploadedFile

from ocr.models import OcrExtraction
from ocr.services.parser import parse_lines
from ocr.services.validate import validate_fields

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def make_lines(pairs):
    return [{"text": t, "conf": c, "source": "tesseract"} for t, c in pairs]


class ParserTests(TestCase):
    def test_standard_labels_and_combined_bp(self):
        fields, warnings = parse_lines(make_lines([
            ("Patient Age: 28", 0.95),
            ("Blood Pressure: 120/80 mmHg", 0.93),
            ("Pulse: 88 bpm", 0.9),
            ("Body Temp: 98.6 F", 0.92),
            ("BMI: 23.4 kg/m2", 0.9),
            ("HbA1c: 36", 0.88),
            ("FBS: 5.6 mmol/L", 0.91),
            ("GA: 24 weeks", 0.85),
        ]))
        self.assertEqual(fields["age"]["value"], 28)
        self.assertEqual(fields["systolic_bp"]["value"], 120)
        self.assertEqual(fields["diastolic_bp"]["value"], 80)
        self.assertEqual(fields["heart_rate"]["value"], 88)
        self.assertAlmostEqual(fields["body_temperature"]["value"], 98.6, places=1)
        self.assertEqual(fields["bmi"]["value"], 23.4)
        self.assertEqual(fields["hba1c"]["value"], 36)
        self.assertEqual(fields["fasting_glucose"]["value"], 5.6)
        self.assertEqual(fields["gestational_week"]["value"], 24)
        self.assertNotIn("mg/dL", " ".join(warnings))

    def test_synonym_variants_and_celsius(self):
        fields, warnings = parse_lines(make_lines([
            ("Systolic: 122", 0.9),
            ("Diastolic: 81", 0.9),
            ("Heart rate: 90", 0.9),
            ("Temperature: 37.2 C", 0.9),
        ]))
        self.assertEqual(fields["systolic_bp"]["value"], 122)
        self.assertEqual(fields["diastolic_bp"]["value"], 81)
        self.assertEqual(fields["heart_rate"]["value"], 90)
        self.assertAlmostEqual(fields["body_temperature"]["value"], 99.0, delta=0.1)
        self.assertFalse(any("no unit" in w for w in warnings))

    def test_devanagari_digits_and_ocr_confusions(self):
        fields, _ = parse_lines(make_lines([
            ("Age: २८", 0.9),
            ("BMI: 2O.4", 0.8),
            ("Pulse: 8S", 0.8),
        ]))
        self.assertEqual(fields["age"]["value"], 28)
        self.assertEqual(fields["bmi"]["value"], 20.4)
        self.assertEqual(fields["heart_rate"]["value"], 85)

    def test_decimal_comma(self):
        fields, _ = parse_lines(make_lines([("HbA1c: 36,5", 0.9)]))
        self.assertEqual(fields["hba1c"]["value"], 36.5)

    def test_unitless_low_temperature_kept_raw_with_suggestion(self):
        # Step 2 policy: never guess units — raw value kept, amber warning,
        # Fahrenheit conversion offered as a suggestion.
        fields, warnings = parse_lines(make_lines([("Temperature: 37", 0.9)]))
        self.assertEqual(fields["body_temperature"]["value"], 37)
        self.assertTrue(any("no unit" in w for w in warnings))
        self.assertEqual(fields["body_temperature"]["suggestion"]["value"], 98.6)

    def test_glucose_mgdl_is_warned_not_converted(self):
        fields, warnings = parse_lines(make_lines([("FBS: 110 mg/dL", 0.9)]))
        self.assertEqual(fields["fasting_glucose"]["value"], 110)  # NOT converted
        self.assertTrue(any("mg/dL" in w for w in warnings))

    def test_visit_date_formats(self):
        fields, _ = parse_lines(make_lines([("Date: 2026-08-12", 0.95)]))
        self.assertEqual(fields["visit_date"]["value"], "2026-08-12")
        fields, warnings = parse_lines(make_lines([("Date: 12/08/2026", 0.95)]))
        self.assertEqual(fields["visit_date"]["value"], "2026-08-12")  # DD/MM assumed
        self.assertTrue(any("DD/MM" in w for w in warnings))
        fields, _ = parse_lines(make_lines([("Date: 12 Aug 2026", 0.95)]))
        self.assertEqual(fields["visit_date"]["value"], "2026-08-12")


class ValidateTests(TestCase):
    def test_out_of_range_and_bp_cross_flagged_not_corrected(self):
        fields, _ = parse_lines(make_lines([
            ("Blood Pressure: 165/170 mmHg", 0.9),
            ("Heart rate: 300", 0.9),
        ]))
        fields, summary = validate_fields(fields)
        self.assertFalse(fields["heart_rate"]["valid"])
        self.assertFalse(fields["diastolic_bp"]["valid"])
        self.assertIn("exceeds systolic", fields["diastolic_bp"]["warning"])
        self.assertEqual(summary["fields_flagged"], 3)
        # Never silently corrected:
        self.assertEqual(fields["heart_rate"]["value"], 300)
        self.assertEqual(fields["systolic_bp"]["value"], 165)

    def test_plausible_values_pass(self):
        fields, _ = parse_lines(make_lines([
            ("Blood Pressure: 120/80", 0.9), ("Pulse: 88", 0.9), ("Age: 28", 0.9),
        ]))
        fields, summary = validate_fields(fields)
        self.assertTrue(all(e["valid"] for e in fields.values()))
        self.assertEqual(summary["fields_flagged"], 0)


@override_settings(LLM_BASE_URL="")  # endpoint tests assert regex behavior only
class OcrEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="ocruser", email="o@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )

    def setUp(self):
        self.client = APIClient()
        from rest_framework_simplejwt.tokens import RefreshToken

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def _post(self, name="card.png", content=PNG_BYTES, content_type="image/png"):
        upload_file = SimpleUploadedFile(name, content, content_type=content_type)
        return self.client.post("/api/ocr/extract/", {"file": upload_file}, format="multipart")

    def test_auth_required(self):
        client = APIClient()
        upload_file = SimpleUploadedFile("c.png", PNG_BYTES, content_type="image/png")
        r = client.post("/api/ocr/extract/", {"file": upload_file}, format="multipart")
        self.assertEqual(r.status_code, 401)

    def test_bad_file_type_rejected(self):
        r = self._post(content=b"not really an image, just text", content_type="image/png")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unsupported", r.json()["error"]["message"])

    def test_oversized_file_rejected(self):
        r = self._post(content=PNG_BYTES + b"0" * (5 * 1024 * 1024))
        self.assertEqual(r.status_code, 400)
        self.assertIn("too large", r.json()["error"]["message"])

    def test_missing_tesseract_returns_503(self):
        with override_settings(TESSERACT_CMD=""):
            from unittest.mock import patch

            with patch("ocr.services.ocr_engine.tesseract_available", return_value=False):
                r = self._post()
        self.assertEqual(r.status_code, 503)
        self.assertIn("Tesseract", r.json()["error"]["message"])

    def test_happy_path_image_extracts_and_never_creates_assessment(self):
        lines = [
            {"text": "Age: 28", "conf": 0.95},
            {"text": "Blood Pressure: 120/80", "conf": 0.93},
            {"text": "Pulse: 88", "conf": 0.9},
            {"text": "Body Temp: 98.6 F", "conf": 0.9},
            {"text": "BMI: 23.4", "conf": 0.9},
            {"text": "HbA1c: 36", "conf": 0.88},
            {"text": "FBS: 5.6", "conf": 0.9},
        ]
        from unittest.mock import patch

        with patch(
            "ocr.services.ocr_engine.ocr_image",
            return_value=(lines, {"engine": "tesseract", "languages": "eng"}),
        ):
            r = self._post()
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"] or r.json()
        self.assertEqual(data["fields"]["age"]["value"], 28)
        self.assertEqual(data["fields"]["systolic_bp"]["value"], 120)
        self.assertIn("visit_date", data["missing"])
        self.assertIn("gestational_week", data["missing"])
        self.assertTrue(data["fields"]["age"]["valid"])
        self.assertEqual(data["engine_info"]["engine"], "tesseract")
        # OCR NEVER creates an assessment or prediction:
        self.assertEqual(Assessment.objects.count(), 0)
        self.assertTrue(OcrExtraction.objects.filter(user=self.user, engine="tesseract").exists())
        self.assertTrue(AuditLog.objects.filter(action="OCR_EXTRACTED").exists())
        detail = AuditLog.objects.filter(action="OCR_EXTRACTED").latest("id").detail
        self.assertIn("fields_extracted", detail)
        self.assertNotIn("raw_text", detail)  # values never enter the audit trail

    def test_metadata_failure_does_not_break_extraction(self):
        # Regression: a missing ocr_ocr_extraction table (or any metadata
        # failure) returned a 500 and destroyed a successful extraction.
        lines = [{"text": "Age: 28", "conf": 0.95}, {"text": "Pulse: 88", "conf": 0.9}]
        from unittest.mock import patch

        with patch(
            "ocr.services.ocr_engine.ocr_image",
            return_value=(lines, {"engine": "tesseract", "languages": "eng"}),
        ), patch(
            "ocr.models.OcrExtraction.objects.create", side_effect=RuntimeError("no such table")
        ):
            r = self._post()
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"] or r.json()
        self.assertEqual(data["fields"]["age"]["value"], 28)

    def test_pdf_with_text_layer_needs_no_tesseract(self):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        y = 780
        for line in [
            "Age: 28", "Blood Pressure: 130/85", "Pulse: 92 bpm", "Body Temp: 98.6 F",
            "BMI: 24.1", "HbA1c: 38", "FBS: 5.4", "Date: 2026-08-12",
        ]:
            pdf.drawString(60, y, line)
            y -= 20
        pdf.save()
        r = self._post(name="card.pdf", content=buffer.getvalue(), content_type="application/pdf")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"] or r.json()
        self.assertEqual(data["engine_info"]["engine"], "pymupdf_text")
        self.assertEqual(data["fields"]["age"]["value"], 28)
        self.assertEqual(data["fields"]["diastolic_bp"]["value"], 85)
        self.assertEqual(data["fields"]["visit_date"]["value"], "2026-08-12")
        self.assertEqual(Assessment.objects.count(), 0)


class ManualEntryUnchangedTests(TestCase):
    """data_source defaults keep manual entry exactly as before."""

    def test_model_default_is_manual(self):
        from accounts.models import User
        from patients.models import PatientProfile

        worker = User.objects.create_user(
            username="manworker", email="m@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        profile = PatientProfile.objects.create(full_name="Manual Patient", created_by=worker)
        assessment = Assessment.objects.create(
            patient=profile, visit_date="2026-08-01", age=28, body_temperature=98.4,
            heart_rate=86, systolic_bp=120, diastolic_bp=78, bmi=23.0, hba1c=38.0,
            fasting_glucose=5.5,
        )
        self.assertEqual(assessment.data_source, "manual")


class ParserRefRangeTests(TestCase):
    """Reference ranges on the same row must never be read as the value, and
    graphics bleed before a number must not become a digit (fixes for the
    report/reports corpus failures)."""

    def test_bp_value_wins_over_lt_reference(self):
        # value column before the "< 140 / 90" reference bound
        fields, _w = parse_lines(make_lines([
            ("BLOOD PRESSURE 161 / 100 mmHg < 140 / 90", 0.94),
        ]))
        self.assertEqual(fields["systolic_bp"]["value"], 161)
        self.assertEqual(fields["diastolic_bp"]["value"], 100)

    def test_bp_reference_only_line_is_skipped(self):
        # EasyOCR often drops the "<" glyph: the reference pair must still
        # lose to the real value found later on the same line
        fields, _w = parse_lines(make_lines([
            ("BLOOD PRESSURE 144 / 92 mmHg 140 / 90", 0.94),
        ]))
        self.assertEqual(fields["systolic_bp"]["value"], 144)
        self.assertEqual(fields["diastolic_bp"]["value"], 92)

    def test_dash_range_after_value_is_not_the_value(self):
        fields, _w = parse_lines(make_lines([
            ("BODY MASS INDEX (BMI) 24.3 18.5 - 24.9", 0.9),
        ]))
        self.assertEqual(fields["bmi"]["value"], 24.3)

    def test_reference_range_line_before_value_line(self):
        # label line, then reference range, then value: plain token wins
        fields, _w = parse_lines(make_lines([
            ("HEART RATE", 0.95),
            ("60 - 100", 0.9),
            ("76 bpm", 0.9),
        ]))
        self.assertEqual(fields["heart_rate"]["value"], 76)

    def test_barcode_bleed_letter_is_not_a_digit(self):
        # "S20" from barcode noise used to parse as 520 (S->5)
        fields, _w = parse_lines(make_lines([
            ("Age / Sex S20 YRS / F", 0.7),
        ]))
        self.assertEqual(fields["age"]["value"], 20)

    def test_leading_one_as_l_still_parses(self):
        # genuine leading confusable (1 misread as l) stays eligible
        fields, _w = parse_lines(make_lines([
            ("Heart rate l20 bpm", 0.8),
        ]))
        self.assertEqual(fields["heart_rate"]["value"], 120)


class RereadValueTests(TestCase):
    """Crop re-read parsing: first number only, no range-like crops, no
    over-precise concatenations (22.1 + 18.5-24.9 -> 22.13185249 bug)."""

    def test_first_number_wins_over_reference_column(self):
        from ocr.services.pipeline import _parse_reread_value

        self.assertEqual(_parse_reread_value("22.1 18.5-24.9", "bmi"), 22.1)
        self.assertEqual(_parse_reread_value("97.5 97.0-99.0", "body_temperature"), 97.5)
        self.assertEqual(_parse_reread_value("91 60 - 100", "heart_rate"), 91)

    def test_combined_bp_token_split_by_slash(self):
        from ocr.services.pipeline import _parse_reread_value

        self.assertEqual(_parse_reread_value("161/100", "systolic_bp"), 161)
        self.assertEqual(_parse_reread_value("161/100", "diastolic_bp"), 100)

    def test_overprecise_garbage_rejected(self):
        from ocr.services.pipeline import _parse_reread_value

        self.assertIsNone(_parse_reread_value("22.1185249", "bmi"))


class EasyOcrLineGroupingTests(TestCase):
    """Boxes on the same visual row merge into one line, left-to-right."""

    def test_row_boxes_merge_into_one_line(self):
        from ocr.services.engine_easyocr import _group_lines

        def box(x0, y0, x1, y1):
            return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

        results = [
            (box(10, 100, 200, 130), "BLOOD PRESSURE", 0.99),
            (box(240, 102, 330, 128), "144 / 92", 0.99),
            (box(350, 104, 420, 126), "mmHg", 0.99),
            (box(440, 103, 520, 127), "140 / 90", 0.99),
            (box(10, 400, 200, 430), "BODY MASS INDEX", 0.99),
            (box(240, 402, 330, 428), "22.1", 0.99),
        ]
        lines = _group_lines(results)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["text"], "BLOOD PRESSURE 144 / 92 mmHg 140 / 90")
        self.assertEqual(lines[1]["text"], "BODY MASS INDEX 22.1")
