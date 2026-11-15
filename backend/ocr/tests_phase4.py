"""Step 2 tests: unit policy, fuzzy labels, decimal suggestions."""
from django.test import TestCase, override_settings

from ocr.services.parser import parse_lines
from ocr.services.units import normalize_temperature
from ocr.services.validate import decimal_suggestion, validate_fields


def _lines(pairs):
    return [{"text": t, "conf": c, "source": "tesseract"} for t, c in pairs]


class TemperatureUnitPolicyTests(TestCase):
    def test_explicit_celsius_converts(self):
        value, warning, suggestion = normalize_temperature(37.0, "C")
        self.assertEqual(value, 98.6)
        self.assertIsNone(warning)
        self.assertIsNone(suggestion)

    def test_explicit_celsius_implausible_never_converted(self):
        value, warning, suggestion = normalize_temperature(380.0, "C")
        self.assertEqual(value, 380.0)  # raw kept
        self.assertIn("not a plausible Celsius", warning)
        self.assertIsNone(suggestion)

    def test_no_unit_never_guessed_keeps_raw_with_suggestion(self):
        value, warning, suggestion = normalize_temperature(37.0, None)
        self.assertEqual(value, 37.0)  # raw kept — NOT converted
        self.assertIn("no unit", warning)
        self.assertEqual(suggestion, {"value": 98.6})  # offered, not applied

    def test_no_unit_fahrenheit_scale_kept_without_suggestion(self):
        value, warning, suggestion = normalize_temperature(98.6, None)
        self.assertEqual(value, 98.6)
        self.assertIn("no unit", warning)
        self.assertIsNone(suggestion)  # 98.6 already looks like °F

    def test_explicit_fahrenheit_unchanged(self):
        value, warning, suggestion = normalize_temperature(98.6, "F")
        self.assertEqual(value, 98.6)
        self.assertIsNone(warning)
        self.assertIsNone(suggestion)


class GlucoseUnitPolicyTests(TestCase):
    def test_mgdl_label_ambiguous_value_not_converted(self):
        fields, warnings = parse_lines(_lines([("FBS: 5.6 mg/dL", 0.9)]))
        self.assertEqual(fields["fasting_glucose"]["value"], 5.6)  # NOT converted
        self.assertTrue(any("mg/dL" in w and "NOT converted" in w for w in warnings))

    def test_mgdl_label_with_mgdl_scale_value_is_invalid(self):
        fields, warnings = parse_lines(_lines([("FBS: 110 mg/dL", 0.9)]))
        self.assertEqual(fields["fasting_glucose"]["value"], 110)
        self.assertFalse(fields["fasting_glucose"]["valid"])

    def test_mmol_label_clean(self):
        fields, warnings = parse_lines(_lines([("FBS: 5.6 mmol/L", 0.9)]))
        self.assertEqual(fields["fasting_glucose"]["value"], 5.6)
        self.assertFalse(any("mg/dL" in w for w in warnings))


class FuzzyLabelTests(TestCase):
    def test_garbled_label_rescued_with_fuzzy_flag(self):
        # "TEMPRATURE" is misspelled -> no exact synonym matches -> fuzzy rescue.
        fields, warnings = parse_lines(_lines([("BOOS TEMPRATURE 975 F", 0.9)]))
        self.assertIn("body_temperature", fields)
        self.assertTrue(fields["body_temperature"].get("fuzzy"))
        self.assertTrue(any("approximately" in w for w in warnings))

    def test_partially_garbled_label_still_matches_exact_synonym(self):
        # "BOOS TEMPERATURE" keeps the exact word "temperature" -> exact path.
        fields, warnings = parse_lines(_lines([("BOOS TEMPERATURE 975 F", 0.9)]))
        self.assertIn("body_temperature", fields)
        self.assertNotIn("fuzzy", fields["body_temperature"])

    def test_ambiguous_garbled_label_returns_candidates(self):
        # "BIuod pressure" could be blood pressure (sys or dia) — ambiguous.
        fields, warnings = parse_lines(_lines([("BIuod pressure 120", 0.8)]))
        entry = fields.get("systolic_bp")
        self.assertIsNotNone(entry)
        self.assertIn("suggestion_candidates", entry)

    def test_exact_labels_still_win_no_fuzzy_penalty(self):
        fields, warnings = parse_lines(_lines([("Age: 28", 0.95)]))
        self.assertNotIn("fuzzy", fields["age"])
        self.assertEqual(fields["age"]["confidence"], 0.95)


class DecimalSuggestionTests(TestCase):
    def test_decimal_suggestion_proposed_never_applied(self):
        fields, warnings = parse_lines(_lines([("BMI: 249 kg/m2", 0.9)]))
        fields, _ = validate_fields(fields)
        entry = fields["bmi"]
        self.assertEqual(entry["value"], 249)          # raw kept
        self.assertFalse(entry["valid"])               # still invalid
        self.assertEqual(entry["suggestion"]["value"], 24.9)  # amber suggestion
        self.assertIn("did you mean 24.9", entry["warning"])

    def test_temperature_decimal_suggestion(self):
        fields, _ = parse_lines(_lines([("Body Temp: 975 F", 0.9)]))
        fields, _ = validate_fields(fields)
        self.assertEqual(fields["body_temperature"]["suggestion"]["value"], 97.5)
        self.assertFalse(fields["body_temperature"]["valid"])

    def test_no_suggestion_when_no_decimal_helps(self):
        fields, _ = parse_lines(_lines([("Heart rate: 300", 0.9)]))
        fields, _ = validate_fields(fields)
        self.assertNotIn("suggestion", fields["heart_rate"])  # 30/3.0/0.3 all implausible

    def test_decimal_suggestion_function_direct(self):
        self.assertEqual(decimal_suggestion("bmi", 249), 24.9)
        self.assertEqual(decimal_suggestion("body_temperature", 975), 97.5)
        self.assertIsNone(decimal_suggestion("heart_rate", 300))
