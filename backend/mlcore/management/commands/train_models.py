"""Train Decision Tree, Random Forest and XGBoost, select on validation,
evaluate the selected model on test, and register all model versions.

Usage:
    python manage.py train_models            # full training + registration
    python manage.py train_models --quick    # tiny smoke run, not registered
"""
import pathlib
import json
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from audit.services import log_event
from mlcore.models import ModelVersion
from mlcore.training import train_all


class Command(BaseCommand):
    help = "Train DT + RF + XGBoost, select on validation and report final test metrics."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default=settings.DATASET_PATH)
        parser.add_argument("--quick", action="store_true", help="Fast smoke training; nothing is registered.")

    def handle(self, *args, **options):
        dataset = pathlib.Path(options["dataset"])
        if not dataset.is_absolute():
            dataset = settings.BASE_DIR / dataset
        if not dataset.exists():
            raise CommandError(f"Dataset not found at {dataset}")

        self.stdout.write(f"Training on {dataset} ...")
        criterion = settings.MODEL_SELECTION_CRITERION
        outcome = train_all(
            dataset,
            settings.ML_ARTIFACTS_DIR,
            quick=options["quick"],
            selection_criterion=criterion,
        )

        if options["quick"]:
            for r in outcome["results"]:
                m = r["validation_metrics"]
                self.stdout.write(
                    f"[quick] {r['name']} validation: accuracy={m['accuracy']:.4f} "
                    f"macro_f1={m['f1_macro']:.4f} high_risk_recall={m['high_risk_recall']:.4f}"
                )
            self.stdout.write(f"[quick] selected by validation: {outcome['selected_model']}")
            self.stdout.write("[quick] selected model test metrics:")
            self.stdout.write(json.dumps(outcome["selected_test_metrics"], indent=2))
            return

        best = next(r for r in outcome["results"] if r["name"] == outcome["selected_model"])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")

        with transaction.atomic():
            for r in outcome["results"]:
                is_winner = r is best
                existing = ModelVersion.objects.filter(name=r["name"], status="PRODUCTION").exclude(
                    version=f"v1.{stamp}"
                )
                version = f"v1.{stamp}"
                ModelVersion.objects.filter(name=r["name"]).update(status="RETIRED")
                row = ModelVersion.objects.create(
                    name=r["name"],
                    version=version,
                    dataset_version=outcome["dataset_md5"],
                    features=r["bundle"]["features"],
                    training_config={
                        **outcome["train_config"],
                        "split_sizes": outcome["split_sizes"],
                        "cleaning_stats": outcome["cleaning_stats"],
                        "train_seconds": r["train_seconds"],
                    },
                    metrics=r["test_metrics"] or {},
                    validation_metrics=r["validation_metrics"],
                    artifact_path=str(r["artifact_path"]),
                    selection_criterion=criterion,
                    status="PRODUCTION" if is_winner else "CANDIDATE",
                )
                # Keep prior production rows of other families intact only if
                # this family didn't just win; simplest policy: single global
                # production model. Retire everything else.
                if is_winner:
                    ModelVersion.objects.exclude(pk=row.pk).filter(status="PRODUCTION").update(status="RETIRED")
                log_event(
                    None, "MODEL_TRAINED", target_type="model_version", target_id=str(row.id),
                    detail={"name": row.name, "version": row.version, "status": row.status,
                            "validation_f1_macro": round(r["validation_metrics"]["f1_macro"], 4),
                            "final_test_f1_macro": (
                                round(r["test_metrics"]["f1_macro"], 4) if r["test_metrics"] else None
                            )},
                )
                self.stdout.write(f"Registered {row.name} {row.version} [{row.status}]")

        self.stdout.write(f"Production model selected on validation by '{criterion}': {best['name']}")
        for r in outcome["results"]:
            self.stdout.write(f"\n{r['name']} validation metrics:")
            self.stdout.write(json.dumps(r["validation_metrics"], indent=2))
        self.stdout.write(f"\n{best['name']} final test metrics (selected model only):")
        self.stdout.write(json.dumps(best["test_metrics"], indent=2))
