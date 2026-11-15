from rest_framework import generics
from rest_framework.views import APIView

from audit import services as audit_svc
from core.exceptions import ApiError
from core.permissions import IsAdmin
from core.responses import ok
from mlcore.models import ModelVersion
from mlcore.registry import feature_importance, get_production_bundle
from mlcore.serializers import ModelVersionSerializer


class ModelListView(generics.ListAPIView):
    """All registered model versions with their full metric payloads."""

    serializer_class = ModelVersionSerializer

    def get_queryset(self):
        return ModelVersion.objects.all()


class ModelComparisonView(APIView):
    """Side-by-side comparison of the latest version of each model family."""

    def get(self, request):
        comparison = []
        for name in ("DecisionTree", "RandomForest", "XGBoost"):
            row = ModelVersion.objects.filter(name=name).order_by("-trained_at").first()
            if row:
                validation_metrics = row.validation_metrics or {}
                test_metrics = row.metrics or {}
                comparison.append(
                    {
                        "id": row.id,
                        "model": row.name,
                        "version": row.version,
                        "status": row.status,
                        "metrics_split": "validation",
                        "accuracy": validation_metrics.get("accuracy"),
                        "precision": validation_metrics.get("precision_macro"),
                        "recall": validation_metrics.get("recall_macro"),
                        "f1": validation_metrics.get("f1_macro"),
                        "roc_auc": validation_metrics.get("roc_auc_ovr_macro"),
                        "high_risk_recall": validation_metrics.get("high_risk_recall"),
                        "per_class": validation_metrics.get("per_class"),
                        "confusion_matrix": validation_metrics.get("confusion_matrix"),
                        "validation_metrics": validation_metrics,
                        "test_metrics": test_metrics if row.status == "PRODUCTION" and test_metrics else None,
                    }
                )
        production = ModelVersion.objects.filter(status="PRODUCTION").first()
        return ok(
            {
                "models": comparison,
                "production": (
                    {"id": production.id, "model": production.name, "version": production.version}
                    if production else None
                ),
                "criterion": production.selection_criterion if production else "high_risk_recall_then_f1",
            }
        )


class ModelActivateView(APIView):
    """Admin promotes a candidate to production (demotes same-name rows)."""

    permission_classes = [IsAdmin]

    def post(self, request, pk):
        row = ModelVersion.objects.filter(pk=pk).first()
        if not row:
            raise ApiError("Model version not found.", code="NOT_FOUND", status_code=404)
        if row.status == "PRODUCTION":
            return ok({"model": ModelVersionSerializer(row).data, "activated": False})
        ModelVersion.objects.filter(status="PRODUCTION").exclude(pk=row.pk).update(status="RETIRED")
        row.status = "PRODUCTION"
        row.save(update_fields=["status"])
        get_production_bundle(force_reload=True)
        audit_svc.log_event(
            request, "MODEL_ACTIVATED", target_type="model_version", target_id=str(row.id),
            detail={"name": row.name, "version": row.version},
        )
        return ok({"model": ModelVersionSerializer(row).data, "activated": True})


class FeatureImportanceView(APIView):
    """Global feature importance of the current production model."""

    def get(self, request):
        try:
            bundle, row = get_production_bundle()
        except Exception as exc:
            raise ApiError(str(exc), code="MODEL_UNAVAILABLE", status_code=503)
        return ok({"model": {"name": row.name, "version": row.version}, "importance": feature_importance(bundle)})


class ModelDiagnosticsView(APIView):
    """What the prediction service currently serves; powers admin status."""

    def get(self, request):
        try:
            _bundle, row = get_production_bundle()
            return ok(
                {
                    "available": True,
                    "production": {"name": row.name, "version": row.version, "trained_at": row.trained_at},
                }
            )
        except Exception as exc:
            return ok({"available": False, "reason": str(exc)})
