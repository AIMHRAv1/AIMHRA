"""Assessment workflow service (requirements #4, #13, #16, #53):

    validated input -> ML prediction -> SHAP -> rule engine -> persistence
    -> trend computation -> structured response
"""
import logging

from django.db import transaction
from django.utils import timezone

from assessments.models import Alert, Assessment, Prediction
from assessments.rules import evaluate as rules_evaluate
from assessments.trends import compute_trend
from audit.services import log_event
from mlcore.exceptions import ModelUnavailableError
from mlcore.registry import predict as model_predict

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "This is an AI-generated risk estimate produced by a statistical model. "
    "It is not a medical diagnosis and does not replace professional medical assessment. "
    "If you feel unwell or notice warning signs, contact a healthcare professional."
)


def create_assessment(patient, data, request=None):
    """Create assessment + prediction + alerts atomically.

    Raises ModelUnavailableError (503) if no production model exists — a
    prediction is never fabricated.
    """
    feature_values = {f: float(data[f]) for f in (
        "age", "body_temperature", "heart_rate", "systolic_bp", "diastolic_bp",
        "bmi", "hba1c", "fasting_glucose",
    )}

    prediction_out = model_predict(feature_values)
    rules_out = rules_evaluate(feature_values, data.get("symptoms") or [])

    visit_date = data.get("visit_date") or timezone.localdate()
    if isinstance(visit_date, str):
        from datetime import date as date_type

        visit_date = date_type.fromisoformat(visit_date)

    with transaction.atomic():
        assessment = Assessment.objects.create(
            patient=patient,
            created_by=getattr(request, "user", None),
            visit_date=visit_date,
            gestational_week=data.get("gestational_week"),
            symptoms=[s for s in (data.get("symptoms") or []) if s != "none"],
            notes=data.get("notes", ""),
            **feature_values,
        )
        prediction = Prediction.objects.create(
            assessment=assessment,
            risk_level=prediction_out["risk_level"],
            probability=prediction_out["probability"],
            probabilities=prediction_out["probabilities"],
            explanation=prediction_out["explanation"],
            model_name=prediction_out["model"]["name"],
            model_version=prediction_out["model"]["version"],
            model_ref_id=prediction_out["model"]["id"],
        )
        alerts = []
        if rules_out["category"] != "NORMAL":
            alert = Alert.objects.create(
                assessment=assessment,
                patient=patient,
                category=rules_out["category"],
                rule_id=",".join(t["id"] for t in rules_out["triggered"][:5]),
                rule_description="; ".join(t["description"] for t in rules_out["triggered"][:5]),
                message=rules_out["message"],
                rules_version=rules_out["rules_version"],
            )
            alerts.append(alert)

    log_event(
        request, "ASSESSMENT_CREATED", target_type="assessment", target_id=str(assessment.id),
        detail={"patient": patient.id},
    )
    log_event(
        request, "PREDICTION", target_type="prediction", target_id=str(prediction.id),
        detail={"risk_level": prediction.risk_level, "model": f"{prediction.model_name} {prediction.model_version}"},
    )
    if rules_out["escalate"]:
        log_event(
            request, "RULE_ESCALATION", target_type="assessment", target_id=str(assessment.id),
            detail={"category": rules_out["category"], "rules": [t["id"] for t in rules_out["triggered"]]},
        )

    history = prediction_series(patient)
    trend = compute_trend(history)

    return build_response(assessment, prediction, rules_out, alerts, trend)


def prediction_series(patient):
    """Serialized predictions for a patient, oldest first."""
    rows = (
        Prediction.objects.filter(assessment__patient=patient)
        .select_related("assessment")
        .order_by("assessment__visit_date", "id")
    )
    return [
        {
            "id": p.id,
            "risk_level": p.risk_level,
            "probability": p.probability,
            "model": f"{p.model_name} {p.model_version}",
            "visit_date": p.assessment.visit_date.isoformat(),
            "gestational_week": p.assessment.gestational_week,
        }
        for p in rows
    ]


def build_response(assessment, prediction, rules_out, alerts, trend):
    return {
        "assessment": {
            "id": assessment.id,
            "visit_date": assessment.visit_date.isoformat(),
            "gestational_week": assessment.gestational_week,
            "symptoms": assessment.symptoms,
            "notes": assessment.notes,
        },
        "risk_level": prediction.risk_level,
        "probability": prediction.probability,
        "probabilities": prediction.probabilities,
        "model": {"name": prediction.model_name, "version": prediction.model_version},
        "explanation": prediction.explanation,
        "rules": {
            "category": rules_out["category"],
            "escalate": rules_out["escalate"],
            "message": rules_out["message"],
            "triggered": rules_out["triggered"],
            "rules_version": rules_out["rules_version"],
        },
        "alerts": [
            {"id": a.id, "category": a.category, "message": a.message, "status": a.status} for a in alerts
        ],
        "trend": trend,
        "disclaimer": DISCLAIMER,
    }
