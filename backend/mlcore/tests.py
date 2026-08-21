"""ML-layer tests: preprocessing, feature selection, leakage, training,
persistence, prediction shape, labels and explainability."""
import numpy as np
from django.conf import settings
from django.test import TestCase

from mlcore.constants import FEATURES, RISK_LEVELS, SAFE_FEATURES, LEAKAGE_FEATURES, UNUSED_FEATURES
from mlcore.dataset import clean_dataset, feature_matrix, load_raw_dataset, validate_dataset
from mlcore.models import ModelVersion
from mlcore.preprocessing import Preprocessor
from mlcore.training import train_all

DATASET = settings.BASE_DIR / "data" / "Mathernal_Risk.csv"

VALID_INPUT = {
    "age": 28, "body_temperature": 98.4, "heart_rate": 86,
    "systolic_bp": 120, "diastolic_bp": 78, "bmi": 23.0,
    "hba1c": 38.0, "fasting_glucose": 5.5,
}


class DatasetTests(TestCase):
    def test_dataset_loads_and_validates(self):
        df = load_raw_dataset(DATASET)
        report = validate_dataset(df, RISK_LEVELS)
        self.assertEqual(report["rows"], 6103)
        self.assertEqual(len(report["class_distribution"]), 3)

    def test_cleaning_only_removes_documented_rows(self):
        df = load_raw_dataset(DATASET)
        clean, stats = clean_dataset(df)
        self.assertLess(stats["rows_out"], stats["rows_in"])
        self.assertGreater(stats["rows_out"], 5000)
        self.assertGreaterEqual(stats["exact_duplicates_dropped"], 1)

    def test_identifiers_are_not_features(self):
        # Leakage prevention contract: no identifiers in the feature matrix.
        df = load_raw_dataset(DATASET)
        X = feature_matrix(df)
        self.assertEqual(X.shape[1], len(SAFE_FEATURES))
        self.assertNotIn("Patient ID", SAFE_FEATURES)
        self.assertNotIn("Name", SAFE_FEATURES)
        self.assertIn("Patient ID", UNUSED_FEATURES)
        self.assertEqual(LEAKAGE_FEATURES, [])


class PreprocessingTests(TestCase):
    def test_fit_transform_and_missing_imputation(self):
        X = np.array([[1.0, 2.0], [3.0, 6.0], [np.nan, 4.0]])
        p = Preprocessor().fit(X)
        out = p.transform(X)
        self.assertFalse(np.isnan(out).any())
        # median of [1,3] = 2 -> imputed at index 2,0
        self.assertEqual(out[2, 0], 2.0)

    def test_roundtrip_serialization(self):
        p = Preprocessor().fit(np.array([[1.0], [3.0]]))
        restored = Preprocessor.from_dict(p.to_dict())
        self.assertTrue(np.allclose(restored.medians, p.medians))

    def test_transform_before_fit_raises(self):
        with self.assertRaises(RuntimeError):
            Preprocessor().transform(np.zeros((1, 2)))


class TrainingAndPredictionTests(TestCase):
    """Trains a QUICK model once and registers it as production, then tests
    the serving path (registry.predict + SHAP)."""

    @classmethod
    def setUpTestData(cls):
        import pathlib

        outcome = train_all(DATASET, settings.ML_ARTIFACTS_DIR, quick=True)
        best = max(outcome["results"], key=lambda r: r["test_metrics"]["f1_macro"])
        for r in outcome["results"]:
            ModelVersion.objects.create(
                name=r["name"],
                version=f"test-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"],
                features=r["bundle"]["features"],
                training_config={"quick": True},
                metrics=r["test_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )

    def test_production_model_exists(self):
        from mlcore.registry import get_production_bundle

        bundle, row = get_production_bundle()
        self.assertIn(bundle["model_name"], ("RandomForest", "XGBoost"))
        self.assertEqual(bundle["classes"], RISK_LEVELS)

    def test_prediction_shape_and_labels(self):
        from mlcore.registry import predict

        out = predict(VALID_INPUT)
        self.assertIn(out["risk_level"], RISK_LEVELS)
        self.assertTrue(0.0 <= out["probability"] <= 1.0)
        self.assertAlmostEqual(sum(out["probabilities"].values()), 1.0, places=2)
        self.assertIn("name", out["model"])
        self.assertIn("version", out["model"])

    def test_prediction_records_model_version(self):
        from mlcore.registry import predict

        out = predict(VALID_INPUT)
        self.assertTrue(ModelVersion.objects.filter(
            name=out["model"]["name"], version=out["model"]["version"], status="PRODUCTION"
        ).exists())

    def test_explanation_structure(self):
        from mlcore.registry import predict

        explanation = predict(VALID_INPUT)["explanation"]
        self.assertIn(explanation["method"], ("SHAP (TreeExplainer)", "unavailable"))
        if explanation["features"]:
            item = explanation["features"][0]
            self.assertIn(item["feature"], FEATURES)
            self.assertIn(item["direction"], ("increasing", "decreasing", "neutral"))
        self.assertIn("contributed", explanation["disclaimer"])

    def test_missing_feature_raises_no_fabricated_prediction(self):
        from mlcore.registry import predict
        from mlcore.exceptions import ModelUnavailableError

        bad = dict(VALID_INPUT)
        bad.pop("bmi")
        with self.assertRaises(ModelUnavailableError):
            predict(bad)

    def test_no_model_registered_returns_503_shape(self):
        from mlcore.exceptions import ModelUnavailableError

        ModelVersion.objects.all().delete()
        with self.assertRaises(ModelUnavailableError):
            from mlcore.registry import get_production_bundle

            get_production_bundle(force_reload=True)
