"""Phase 2/Step-2 tests: digit checks, candidate merging, vision stage,
compute cascade, engine dispatch, provenance and the feedback endpoint."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from audit.models import AuditLog
from ocr.services import engine_easyocr, llm_extract, vision_extract
from ocr.services.pipeline import _merge_candidate
from ocr.tests import PNG_BYTES


class DigitCheckTests(TestCase):
    """Anti-hallucination: LLM values must have their digits in the OCR text."""

    def test_digits_present_accepts_exact_and_substring(self):
        text = "Age: 28 BP 120/80 HbA1c 36,5"
        self.assertTrue(llm_extract.digits_present(28, text))
        self.assertTrue(llm_extract.digits_present(120, text))
        self.assertTrue(llm_extract.digits_present(36.5, text))  # comma normalized

    def test_digits_present_rejects_invented_values(self):
        text = "Age: 28"
        self.assertFalse(llm_extract.digits_present(82, text))   # transposed
        self.assertFalse(llm_extract.digits_present(29, text))   # near miss
        self.assertFalse(llm_extract.digits_present(None, text))

    def test_llm_extract_parses_strict_json_and_rejects_hallucinations(self):
        ocr_text = "Age: 28\nBlood Pressure: 120/80\nHbA1c: 36,5"
        answer = '{"age": 28, "systolic_bp": 120, "diastolic_bp": 80, "hba1c": 36.5, "bmi": 27.4, "visit_date": null}'
        with patch.object(llm_extract, "_call_ollama", return_value=answer):
            extracted, model = llm_extract.llm_extract_fields(
                ocr_text, ["age", "systolic_bp", "diastolic_bp", "hba1c", "bmi"]
            )
        # bmi=27.4 has no digit match in the OCR text -> hallucination, dropped
        self.assertNotIn("bmi", extracted)
        self.assertEqual(extracted["age"]["value"], 28)
        self.assertEqual(extracted["age"]["source"], "llm")
        self.assertEqual(extracted["systolic_bp"]["value"], 120)

    def test_llm_extract_handles_null_and_garbage_and_errors(self):
        with patch.object(llm_extract, "_call_ollama", return_value='{"age": null, "bmi": null}'):
            extracted, _ = llm_extract.llm_extract_fields("Age: 28", ["age", "bmi"])
        self.assertEqual(extracted, {})
        with patch.object(llm_extract, "_call_ollama", return_value="I cannot do that"):
            extracted, _ = llm_extract.llm_extract_fields("Age: 28", ["age"])
        self.assertEqual(extracted, {})
        with patch.object(llm_extract, "_call_ollama", side_effect=Exception("server down")):
            extracted, _ = llm_extract.llm_extract_fields("Age: 28", ["age"])
        self.assertEqual(extracted, {})



class MergeCandidateTests(TestCase):
    def test_missing_field_accepted_with_low_confidence(self):
        fields, warnings = {}, []
        _merge_candidate(fields, warnings, "age", {"value": 28, "source": "llm", "confidence": 0.55}, "Age: 28")
        self.assertEqual(fields["age"]["value"], 28)
        self.assertEqual(fields["age"]["source"], "llm")
        self.assertEqual(fields["age"]["confidence"], 0.55)
        self.assertTrue(fields["age"]["valid"])

    def test_agreement_records_second_source(self):
        fields = {"age": {"value": 28, "confidence": 0.95, "raw_text": "Age: 28", "source": "tesseract", "valid": True, "warning": ""}}
        warnings = []
        _merge_candidate(fields, warnings, "age", {"value": 28, "source": "llm", "confidence": 0.55}, "Age: 28")
        self.assertEqual(fields["age"]["value"], 28)
        self.assertIn("llm", fields["age"]["also_found_by"])
        self.assertNotIn("candidates", fields["age"])

    def test_disagreement_flags_red_with_both_candidates(self):
        # Non-LLM sources (reread/easyocr) still red-flag disagreements.
        fields = {"systolic_bp": {"value": 120, "confidence": 0.95, "raw_text": "BP 120/80", "source": "tesseract", "valid": True, "warning": ""}}
        warnings = []
        _merge_candidate(fields, warnings, "systolic_bp", {"value": 210, "source": "reread", "confidence": 0.8}, "BP 120/80")
        entry = fields["systolic_bp"]
        self.assertFalse(entry["valid"])  # red flag
        self.assertEqual(len(entry["candidates"]), 2)
        self.assertEqual(entry["candidates"][0]["value"], 120)
        self.assertEqual(entry["candidates"][1]["value"], 210)
        self.assertTrue(any("disagree" in w for w in warnings))

    def test_llm_disagreement_flags_red_with_both_candidates(self):
        # LLM disagreement against an INVALID tesseract value still red-flags.
        fields = {"systolic_bp": {"value": 120, "confidence": 0.95, "raw_text": "BP 120/80", "source": "tesseract", "valid": False, "warning": "out of test range"}}
        warnings = []
        _merge_candidate(fields, warnings, "systolic_bp", {"value": 210, "source": "llm", "confidence": 0.55}, "BP 120/80")
        entry = fields["systolic_bp"]
        self.assertFalse(entry["valid"])
        self.assertEqual(len(entry["candidates"]), 2)
        self.assertTrue(any("disagree" in w for w in warnings))



class VisionStageTests(TestCase):
    def test_disabled_by_default_and_never_called(self):
        self.assertFalse(vision_extract.vision_enabled())
        with patch.object(vision_extract, "_call_ollama", side_effect=AssertionError("must not be called")):
            extracted, _ = vision_extract.vision_extract_fields(b"png", ["age"])
        self.assertEqual(extracted, {})

    def test_enabled_returns_low_confidence_vlm_source(self):
        with override_settings(OCR_VISION_ENABLED=True):
            answer = '{"age": 28, "systolic_bp": null}'
            with patch.object(vision_extract, "_call_ollama", return_value=answer):
                extracted, model = vision_extract.vision_extract_fields(b"png", ["age", "systolic_bp"])
        self.assertEqual(model, vision_extract.vision_model())
        self.assertEqual(extracted["age"]["source"], "vlm")
        self.assertEqual(extracted["age"]["value"], 28)



class CascadeTests(TestCase):
    """Small photos lose decimals/digits; the cascade runs a fast pass first
    and adds a CLAHE variant + field re-reads only for wanted fields."""

    def _lines(self, pairs):
        return [{"text": t, "conf": c, "source": "tesseract"} for t, c in pairs]

    @override_settings(LLM_BASE_URL="")
    def test_clahe_variant_runs_when_fields_wanted(self):
        fast = self._lines([("Body Temp: 975 F", 0.9)])  # decimal lost -> invalid -> wanted
        clahe = self._lines([("Body Temp: 97.5 F", 0.9), ("Pulse: 88", 0.9)])
        from unittest.mock import patch

        with patch(
            "ocr.services.ocr_engine.ocr_image",
            side_effect=[(fast, {"engine": "tesseract"}), (clahe, {"engine": "tesseract"})],
        ):
            from ocr.services.pipeline import extract

            payload = extract("png", PNG_BYTES)
        self.assertEqual(payload["fields"]["body_temperature"]["value"], 97.5)
        self.assertEqual(payload["fields"]["heart_rate"]["value"], 88)
        self.assertIn("clahe", payload["engine_info"]["passes"])
        self.assertIn("fast", payload["engine_info"]["passes"])

    @override_settings(LLM_BASE_URL="")
    def test_fast_pass_only_when_nothing_wanted(self):
        fast = self._lines([
            ("Age: 28", 0.95), ("Pulse: 88", 0.95), ("BMI: 23.4", 0.95),
            ("Blood Pressure: 120/80", 0.95), ("Body Temp: 98.6 F", 0.95),
            ("HbA1c: 36", 0.95), ("FBS: 5.6", 0.95),
        ])
        from unittest.mock import patch

        with patch(
            "ocr.services.ocr_engine.ocr_image",
            side_effect=[(fast, {"engine": "tesseract"}), AssertionError("must not run")],
        ):
            from ocr.services.pipeline import extract

            payload = extract("png", PNG_BYTES)
        self.assertEqual(payload["engine_info"]["passes"], ["fast"])
        self.assertEqual(len(payload["fields"]), 8)  # BP expands to two fields

    def test_small_images_upscaled_to_ocr_target(self):
        from ocr.services.preprocess import decode_image, preprocess_image, preprocess_variant
        import cv2
        import numpy as np

        small = np.full((734, 550, 3), 255, dtype=np.uint8)  # 3x -> target 2200? 550*3=1650...
        out = preprocess_variant(small, level=0)
        self.assertGreaterEqual(max(out.shape[:2]), 1650)  # capped 3x
        # larger small-image reaches the 2200 target
        mid = np.full((900, 700, 3), 255, dtype=np.uint8)
        out2 = preprocess_variant(mid, level=0)
        self.assertGreaterEqual(max(out2.shape[:2]), 2100)


# ------------------------- decimal/digit-loss fixes -------------------------


class EngineDispatchTests(TestCase):
    def _lines(self):
        return [{"text": "Age: 28", "conf": 0.95}]

    @override_settings(OCR_ENGINE="easyocr")
    def test_easyocr_missing_falls_back_to_tesseract(self):
        with patch.object(engine_easyocr, "easyocr_available", return_value=False), patch(
            "ocr.services.ocr_engine.ocr_image", return_value=(self._lines(), {"engine": "tesseract"})
        ) as mock_ocr:
            from ocr.services.pipeline import extract

            payload = extract("png", PNG_BYTES)
        self.assertTrue(mock_ocr.called)
        self.assertEqual(payload["engine_info"]["engine"], "tesseract")

    def test_idle_release_drops_cached_reader(self):
        engine_easyocr._CACHE["reader"] = object()
        engine_easyocr._CACHE["used_at"] = engine_easyocr.time.monotonic() - 999
        engine_easyocr.release_idle_engine(max_idle_seconds=10)
        self.assertIsNone(engine_easyocr._CACHE["reader"])
        engine_easyocr.force_release()


class PipelineProvenanceTests(TestCase):
    def test_llm_never_overrides_valid_tesseract_value(self):
        # Step 4: the LLM runs only for MISSING fields; a valid Tesseract
        # value (even at low confidence) is never overridden or flagged.
        lines = [{"text": "Age: 28", "conf": 0.4}, {"text": "Pulse: 88", "conf": 0.95}]
        with patch("ocr.services.ocr_engine.ocr_image", return_value=(lines, {"engine": "tesseract"})), patch(
            "ocr.services.llm_extract.llm_extract_fields",
            return_value=({"age": {"value": 29, "raw_text": "llm:m", "source": "llm"}}, "llama3.2:3b"),
        ) as mock_llm:
            from ocr.services.pipeline import extract

            payload = extract("png", PNG_BYTES)
        age = payload["fields"]["age"]
        self.assertEqual(age["value"], 28)   # tesseract value kept
        self.assertTrue(age["valid"])        # never flagged by the LLM
        self.assertIn("llm", age.get("also_found_by", []))
        # The LLM was only asked about MISSING fields, not age:
        asked = mock_llm.call_args[0][1]
        self.assertNotIn("age", asked)
        self.assertIn("systolic_bp", asked)

    def test_llm_agreement_records_provenance(self):
        lines = [{"text": "Age: 28", "conf": 0.4}, {"text": "Pulse: 88", "conf": 0.95}]
        with patch("ocr.services.ocr_engine.ocr_image", return_value=(lines, {"engine": "tesseract"})), patch(
            "ocr.services.llm_extract.llm_extract_fields",
            return_value=({"age": {"value": 28, "raw_text": "llm:m", "source": "llm"}}, "llama3.2:3b"),
        ):
            from ocr.services.pipeline import extract

            payload = extract("png", PNG_BYTES)
        self.assertIn("llm", payload["fields"]["age"].get("also_found_by", []))


class OcrFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="ocrfb", email="fb@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )

    def setUp(self):
        self.client = APIClient()
        from rest_framework_simplejwt.tokens import RefreshToken

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def test_feedback_logs_names_only_never_values(self):
        r = self.client.post(
            "/api/ocr/feedback/",
            {"entries": [{"field": "age", "changed": True, "value": 999}, {"field": "bmi", "changed": False, "value": 1}]},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        detail = AuditLog.objects.filter(action="OCR_FEEDBACK").latest("id").detail
        self.assertEqual(detail["changed_fields"], ["age"])
        self.assertEqual(detail["kept_fields"], ["bmi"])
        self.assertNotIn("999", str(detail))  # values never enter the audit trail

    def test_feedback_requires_entries(self):
        r = self.client.post("/api/ocr/feedback/", {"entries": []}, content_type="application/json")
        self.assertEqual(r.status_code, 400)


# ------------------------- decimal/digit-loss fixes -------------------------
