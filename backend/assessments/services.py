"""Assessment workflow service (requirements #4, #13, #16, #53):

    validated input -> ML prediction -> SHAP -> rule engine -> persistence
    -> trend computation -> structured response
"""
import logging

from django.db import transaction
from django.utils import timezone

from assessments.models import Alert, Assessment, Prediction
from assessments.rules import evaluate as rules_evaluate
from assessments.trends import MEASUREMENT_FIELDS, compute_trend
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
    """Persist the assessment and rule outcome independently of ML availability."""
    feature_values = {f: float(data[f]) for f in (
        "age", "body_temperature", "heart_rate", "systolic_bp", "diastolic_bp",
        "bmi", "hba1c", "fasting_glucose",
    )}

    current_symptoms = [s for s in (data.get("symptoms") or []) if s != "none"]
    rule_inputs = {
        **feature_values,
        "gestational_week": data.get("gestational_week"),
    }
    rules_out = rules_evaluate(rule_inputs, current_symptoms)

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
            symptoms=current_symptoms,
            recommendations=rules_out["recommendations"],
            notes=data.get("notes", ""),
            **feature_values,
        )
        alerts = []
        if rules_out["category"] != "NORMAL":
            alert = Alert.objects.create(
                assessment=assessment,
                patient=patient,
                category=rules_out["category"],
                rule_id=",".join(t["id"] for t in rules_out["triggered"]),
                rule_description="; ".join(t["description"] for t in rules_out["triggered"]),
                message=rules_out["message"],
                rules_version=rules_out["rules_version"],
            )
            alerts.append(alert)

    prediction = None
    prediction_message = None
    try:
        prediction_out = model_predict(feature_values)
    except ModelUnavailableError as exc:
        prediction_message = (
            "ML prediction is unavailable. The assessment and clinical rule evaluation "
            "were saved; no ML risk classification was produced."
        )
        logger.warning("ML prediction unavailable for assessment %s: %s", assessment.id, exc)
    else:
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

    log_event(
        request, "ASSESSMENT_CREATED", target_type="assessment", target_id=str(assessment.id),
        detail={"patient": patient.id},
    )
    if prediction:
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

    return build_response(
        assessment, prediction, rules_out, alerts, trend, prediction_message=prediction_message
    )


def prediction_series(patient):
    """Serialized assessment history for a patient, oldest first."""
    rows = (
        Assessment.objects.filter(patient=patient)
        .select_related("prediction", "created_by")
        .order_by("visit_date", "id")
    )
    history = []
    for assessment in rows:
        prediction = getattr(assessment, "prediction", None)
        history.append({
            "id": prediction.id if prediction else None,
            "assessment_id": assessment.id,
            "risk_level": prediction.risk_level if prediction else None,
            "probability": prediction.probability if prediction else None,
            "model": (
                f"{prediction.model_name} {prediction.model_version}" if prediction else None
            ),
            "visit_date": assessment.visit_date.isoformat(),
            "gestational_week": assessment.gestational_week,
            "recommendations": assessment.recommendations,
            "assessed_by": (
                assessment.created_by.full_name or assessment.created_by.username
                if assessment.created_by else None
            ),
            **{feature: getattr(assessment, feature) for feature in MEASUREMENT_FIELDS},
        })
    return history


def build_response(assessment, prediction, rules_out, alerts, trend, prediction_message=None):
    return {
        "assessment": {
            "id": assessment.id,
            "visit_date": assessment.visit_date.isoformat(),
            "gestational_week": assessment.gestational_week,
            "symptoms": assessment.symptoms,
            "notes": assessment.notes,
            "assessed_by": (
                assessment.created_by.full_name or assessment.created_by.username
                if assessment.created_by else None
            ),
        },
        "risk_level": prediction.risk_level if prediction else None,
        "probability": prediction.probability if prediction else None,
        "probabilities": prediction.probabilities if prediction else {},
        "model": (
            {"name": prediction.model_name, "version": prediction.model_version}
            if prediction else None
        ),
        "explanation": prediction.explanation if prediction else None,
        "prediction_status": "available" if prediction else "unavailable",
        "prediction_message": prediction_message,
        "rules": {
            "category": rules_out["category"],
            "escalate": rules_out["escalate"],
            "message": rules_out["message"],
            "triggered": rules_out["triggered"],
            "rules_version": rules_out["rules_version"],
            "recommendations": rules_out["recommendations"],
        },
        "recommendations": assessment.recommendations,
        "alerts": [
            {"id": a.id, "category": a.category, "message": a.message, "status": a.status} for a in alerts
        ],
        "trend": trend,
        "disclaimer": DISCLAIMER,
    }
