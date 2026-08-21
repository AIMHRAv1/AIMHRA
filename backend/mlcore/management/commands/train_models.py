"""Train Random Forest and XGBoost, evaluate on the test split, register
model versions, and promote the winner per the configured criterion.

Usage:
    python manage.py train_models            # full training + registration
    python manage.py train_models --quick    # tiny smoke run, not registered
"""
import pathlib
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from audit.services import log_event
from mlcore import evaluation as ev
from mlcore.models import ModelVersion
from mlcore.training import train_all


class Command(BaseCommand):
    help = "Train RF + XGBoost, evaluate, persist artifacts and register model versions."

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
        outcome = train_all(dataset, settings.ML_ARTIFACTS_DIR, quick=options["quick"])

        if options["quick"]:
            for r in outcome["results"]:
                m = r["test_metrics"]
                self.stdout.write(f"[quick] {r['name']}: f1_macro={m['f1_macro']:.4f}")
            return

        criterion = settings.MODEL_SELECTION_CRITERION
        best = max(outcome["results"], key=lambda r: ev.selection_score(r["test_metrics"], criterion))
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
                    metrics=r["test_metrics"],
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
                            "f1_macro": round(r["test_metrics"]["f1_macro"], 4)},
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Registered {row.name} {row.version} [{row.status}] "
                        f"test_f1_macro={r['test_metrics']['f1_macro']:.4f} "
                        f"test_high_risk_recall={r['test_metrics']['high_risk_recall']:.4f}"
                    )
                )

        self.stdout.write(f"Production model selected by criterion '{criterion}': {best['name']}")
