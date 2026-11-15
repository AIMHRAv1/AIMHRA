"""ML-layer tests: preprocessing, feature selection, leakage, training,
persistence, prediction shape, labels and explainability."""
import numpy as np
from django.conf import settings
from django.test import TestCase

from mlcore.constants import (
    FEATURES, FEATURE_LABELS, RISK_LEVELS, SAFE_FEATURES,
    LEAKAGE_FEATURES, UNUSED_FEATURES,
)
from mlcore.dataset import clean_dataset, feature_matrix, load_raw_dataset, validate_dataset
from mlcore.evaluation import selection_score
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
        self.assertEqual(stats["rows_in"], 6103)
        self.assertEqual(stats["exact_duplicates_dropped"], 0)
        self.assertEqual(stats["implausible_rows_dropped_total"], 45)
        self.assertEqual(stats["rows_out"], 6058)
        self.assertEqual(len(clean), 6058)

    def test_identical_clinical_records_with_different_identifiers_are_retained(self):
        df = load_raw_dataset(DATASET)
        duplicate_mask = df.duplicated(subset=FEATURES + ["risk_level"], keep=False)
        duplicates = df.loc[duplicate_mask]
        self.assertEqual(len(duplicates), 2)
        self.assertEqual(duplicates["Patient ID"].nunique(), 2)
        self.assertEqual(duplicates["Name"].nunique(), 2)

        clean, stats = clean_dataset(df)
        retained = clean.loc[clean.index.isin(duplicates.index)]
        self.assertEqual(len(retained), 2)
        self.assertEqual(stats["exact_duplicates_dropped"], 0)

    def test_identifiers_are_not_features(self):
        # Leakage prevention contract: no identifiers in the feature matrix.
        df = load_raw_dataset(DATASET)
        X = feature_matrix(df)
        self.assertEqual(X.shape[1], len(SAFE_FEATURES))
        self.assertNotIn("Patient ID", SAFE_FEATURES)
        self.assertNotIn("Name", SAFE_FEATURES)
        self.assertIn("Patient ID", UNUSED_FEATURES)
        self.assertNotIn("Patient ID", FEATURES)
        self.assertNotIn("Name", FEATURES)
        self.assertEqual(LEAKAGE_FEATURES, [])

    def test_glucose_feature_units_are_explicit(self):
        self.assertEqual(FEATURE_LABELS["hba1c"], "HbA1c (mmol/mol)")
        self.assertEqual(FEATURE_LABELS["fasting_glucose"], "Fasting blood glucose (mmol/L)")


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
        best = next(r for r in outcome["results"] if r["name"] == outcome["selected_model"])
        for r in outcome["results"]:
            ModelVersion.objects.create(
                name=r["name"],
                version=f"test-{r['name'][:3].lower()}",
                dataset_version=outcome["dataset_md5"],
                features=r["bundle"]["features"],
                training_config={"quick": True},
                metrics=r["test_metrics"] or {},
                validation_metrics=r["validation_metrics"],
                artifact_path=str(r["artifact_path"]),
                status="PRODUCTION" if r is best else "CANDIDATE",
            )

    def test_production_model_exists(self):
        from mlcore.registry import get_production_bundle

        bundle, row = get_production_bundle()
        self.assertIn(bundle["model_name"], ("DecisionTree", "RandomForest", "XGBoost"))
        self.assertEqual(bundle["classes"], RISK_LEVELS)

    def test_validation_selects_models_and_only_selected_model_has_test_metrics(self):
        outcome = train_all(
            DATASET,
            settings.ML_ARTIFACTS_DIR,
            quick=True,
            selection_criterion=settings.MODEL_SELECTION_CRITERION,
        )
        self.assertEqual(
            {result["name"] for result in outcome["results"]},
            {"DecisionTree", "RandomForest", "XGBoost"},
        )
        selected = next(r for r in outcome["results"] if r["name"] == outcome["selected_model"])
        expected = max(
            outcome["results"],
            key=lambda r: selection_score(
                r["validation_metrics"], settings.MODEL_SELECTION_CRITERION
            ),
        )
        self.assertIs(selected, expected)
        self.assertEqual(outcome["selected_test_metrics"], selected["test_metrics"])
        for result in outcome["results"]:
            self.assertIsNotNone(result["validation_metrics"])
            if result is selected:
                self.assertIsNotNone(result["test_metrics"])
                for metric in (
                    "accuracy", "precision_macro", "recall_macro", "f1_macro",
                    "roc_auc_ovr_macro", "high_risk_recall", "per_class", "confusion_matrix",
                ):
                    self.assertIn(metric, result["test_metrics"])
                self.assertIn("high risk", result["test_metrics"]["per_class"])
            else:
                self.assertIsNone(result["test_metrics"])

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
