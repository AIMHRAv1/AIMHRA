"""ML-layer tests: preprocessing, feature selection, leakage, training,
persistence, prediction shape, labels and explainability."""
import numpy as np
import pandas as pd
from accounts.models import User
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from mlcore.constants import FEATURES, RISK_LEVELS, SAFE_FEATURES, LEAKAGE_FEATURES, UNUSED_FEATURES
from mlcore.dataset import (
    clean_dataset,
    feature_matrix,
    grouped_split_indices,
    load_raw_dataset,
    near_duplicate_groups,
    validate_dataset,
)
from mlcore.evaluation import bootstrap_ci, calibration_metrics
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

    def test_glucose_units_match_documented_ranges(self):
        # Unit contract: the production model trains on the dataset's own
        # magnitudes; validate_dataset must report them as consistent.
        df = load_raw_dataset(DATASET)
        report = validate_dataset(df, RISK_LEVELS)
        self.assertTrue(report["unit_check"]["hba1c"]["consistent"])
        self.assertTrue(report["unit_check"]["fasting_glucose"]["consistent"])

    def test_unit_check_rejects_mgdl_magnitude_flip(self):
        # A future CSV corrected to true mg/dL magnitudes must FAIL loudly,
        # not silently invalidate the deployed model.
        df = load_raw_dataset(DATASET).copy()
        df.loc[df.index[:100], "hba1c"] = 11.0  # % scale instead of mmol/mol
        with self.assertRaises(ValueError):
            validate_dataset(df, RISK_LEVELS)

    def test_near_duplicate_groups_are_deterministic_and_sound(self):
        df = load_raw_dataset(DATASET)
        g1 = near_duplicate_groups(df)
        g2 = near_duplicate_groups(df)
        np.testing.assert_array_equal(g1, g2)
        # Two rows identical on all 8 features share a group.
        a, b = df.iloc[0], df.iloc[1]
        twin = a.copy()
        twin["risk_level"] = b["risk_level"]  # label ignored for grouping
        df2 = pd.concat([df, twin.to_frame().T], ignore_index=True)
        for f in FEATURES:
            df2[f] = pd.to_numeric(df2[f])
        g3 = near_duplicate_groups(df2)
        self.assertEqual(g3[0], g3[-1])

    def test_grouped_split_keeps_groups_whole_and_is_reproducible(self):
        y = np.array([0, 0, 1, 1, 0, 1, 0, 1, 0, 1])
        groups = np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
        tr1, te1 = grouped_split_indices(y, groups, test_size=0.4, seed=7)
        tr2, te2 = grouped_split_indices(y, groups, test_size=0.4, seed=7)
        np.testing.assert_array_equal(tr1, tr2)
        np.testing.assert_array_equal(te1, te2)
        self.assertEqual(len(tr1) + len(te1), len(y))
        self.assertEqual(set(tr1) & set(te1), set())
        # Every group lands entirely on one side.
        for g in np.unique(groups):
            rows = np.where(groups == g)[0]
            same_side = all((r in set(te1)) for r in rows) or all((r not in set(te1)) for r in rows)
            self.assertTrue(same_side, f"group {g} straddled the split")


class CalibrationAndCITests(TestCase):
    def test_calibration_perfect_predictions_score_zero_brier(self):
        y_true = ["low risk", "mid risk", "high risk"]
        y_proba = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        m = calibration_metrics(y_true, y_proba)
        self.assertEqual(m["brier_multiclass"], 0.0)
        self.assertEqual(m["expected_calibration_error"], 0.0)

    def test_calibration_overconfident_predictions_produce_nonzero_ece(self):
        y_true = ["low risk", "high risk"]
        y_proba = np.array([
            [0.95, 0.03, 0.02],  # confident low risk, correct
            [0.95, 0.03, 0.02],  # confident low risk, WRONG
        ])
        m = calibration_metrics(y_true, y_proba)
        self.assertGreater(m["expected_calibration_error"], 0.3)
        self.assertGreater(m["brier_multiclass"], 0.5)

    def test_bootstrap_ci_on_constant_metric_is_degenerate(self):
        y_true = ["low risk"] * 10
        y_pred = ["low risk"] * 10
        ci = bootstrap_ci(y_true, y_pred, lambda yt, yp: 1.0, n_resamples=50)
        self.assertEqual(ci["low"], 1.0)
        self.assertEqual(ci["high"], 1.0)


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
        cls.outcome = outcome
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

    def test_training_split_is_group_aware(self):
        report = self.outcome["split_report"]
        self.assertGreater(report["near_duplicate_groups"], 0)
        self.assertGreater(report["rows_in_multi_row_groups"], 0)
        # Near-duplicate clusters never straddle the test boundary.
        self.assertEqual(report["groups_shared_across_splits"], 0)

    def test_test_metrics_carry_calibration_and_ci(self):
        for r in self.outcome["results"]:
            m = r["test_metrics"]
            self.assertIn("calibration", m)
            self.assertTrue(0.0 <= m["calibration"]["brier_multiclass"] <= 3.0)
            self.assertTrue(0.0 <= m["calibration"]["expected_calibration_error"] <= 1.0)
            self.assertIn("f1_macro_ci95", m)
            self.assertLessEqual(m["f1_macro_ci95"]["low"], m["f1_macro"] + 1e-9)
            self.assertGreaterEqual(m["f1_macro_ci95"]["high"], m["f1_macro"] - 1e-9)

    def test_training_includes_diverse_classifiers(self):
        names = {result["name"] for result in self.outcome["results"]}
        self.assertEqual(
            names,
            {
                "RandomForest", "XGBoost", "DecisionTree", "ExtraTrees",
                "GradientBoosting", "LogisticRegression",
            },
        )
        for result in self.outcome["results"]:
            self.assertEqual(len(result["test_metrics"]["per_class"]), len(RISK_LEVELS))

    def test_logistic_regression_has_model_contributions(self):
        from mlcore.explain import explain_prediction

        result = next(r for r in self.outcome["results"] if r["name"] == "LogisticRegression")
        bundle = result["bundle"]
        preprocessor = Preprocessor.from_dict(bundle["preprocessor"])
        vector = preprocessor.transform(np.array([list(VALID_INPUT.values())]))[0]
        bundle["_predicted_index"] = 0
        bundle["_predicted_label"] = RISK_LEVELS[0]

        explanation = explain_prediction(bundle, vector)

        self.assertEqual(explanation["method"], "Standardized linear-model contribution")
        self.assertTrue(explanation["features"])
        self.assertEqual(explanation["target_class"], RISK_LEVELS[0])

    def test_model_comparison_lists_latest_classifier_families(self):
        admin = User.objects.create_user(
            username="model_compare_admin",
            email="model_compare@example.com",
            password="test-password",
            role="ADMIN",
        )
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get("/api/models/compare/")

        self.assertEqual(response.status_code, 200)
        comparison = response.json()["data"]
        self.assertEqual(
            {model["model"] for model in comparison["models"]},
            {
                "RandomForest", "XGBoost", "DecisionTree", "ExtraTrees",
                "GradientBoosting", "LogisticRegression",
            },
        )

    def test_production_model_exists(self):
        from mlcore.registry import get_production_bundle

        bundle, row = get_production_bundle()
        self.assertIn(
            bundle["model_name"],
            {"RandomForest", "XGBoost", "DecisionTree", "ExtraTrees", "GradientBoosting", "LogisticRegression"},
        )
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
        self.assertIn(
            explanation["method"],
            ("SHAP (TreeExplainer)", "Standardized linear-model contribution", "unavailable"),
        )
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
