"""Assessment workflow service (requirements #4, #13, #16, #53):

    validated input -> ML prediction -> SHAP -> rule engine -> persistence
    -> trend computation -> structured response
"""
import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from accounts.utils import user_photo_url
from assessments.models import Alert, Assessment, Prediction
from assessments.references import attach_document_versions, guideline_references
from assessments.rules import evaluate as rules_evaluate
from assessments.rules.trend_engine import evaluate_trends
from assessments.trends import compare_measurements, compute_trend, measurement_series
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
        visit_date = date.fromisoformat(visit_date)

    gestational_week = data.get("gestational_week")
    if gestational_week is None and patient.gestational_week_at_registration:
        registered_date = timezone.localtime(patient.created_at).date()
        elapsed_days = max(0, (visit_date - registered_date).days)
        gestational_week = min(
            45,
            patient.gestational_week_at_registration + elapsed_days // 7,
        )

    with transaction.atomic():
        assessment = Assessment.objects.create(
            patient=patient,
            created_by=getattr(request, "user", None),
            visit_date=visit_date,
            gestational_week=gestational_week,
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

    history = prediction_series(patient, request=request)
    trend = compute_trend(history)

    # Measurement-trend checks: deterministic arithmetic over stored visits,
    # evaluated by the separately-configured trend rules. No alert can be
    # produced while the trend ruleset is not clinically reviewed.
    series = measurement_series(patient)
    comparisons = compare_measurements(series)
    trend_rules_out = evaluate_trends(comparisons)
    if trend_rules_out["active"] and trend_rules_out["category"] != "NORMAL" and trend_rules_out["triggered"]:
        with transaction.atomic():
            trend_alert = Alert.objects.create(
                assessment=assessment,
                patient=patient,
                category=trend_rules_out["category"],
                rule_id=",".join(t["id"] for t in trend_rules_out["triggered"][:5]),
                rule_description="; ".join(t["description"] for t in trend_rules_out["triggered"][:5]),
                message=trend_rules_out["message"],
                rules_version=trend_rules_out["rules_version"],
            )
            alerts.append(trend_alert)
        log_event(
            request, "RULE_ESCALATION", target_type="assessment", target_id=str(assessment.id),
            detail={
                "kind": "measurement_trend",
                "category": trend_rules_out["category"],
                "rules": [t["id"] for t in trend_rules_out["triggered"]],
            },
        )

    response = build_response(assessment, prediction, rules_out, alerts, trend)
    # Persist the citations that were shown for this assessment so they stay
    # traceable even if the knowledge base changes later (additive JSONField
    # key — no migration).
    prediction.explanation = {**prediction.explanation, "references": response["decision_support"]["references"]}
    prediction.save(update_fields=["explanation"])
    response["measurement_trend"] = {
        "note": "deterministic rule calculations over stored measurements — not machine learning",
        "comparisons": comparisons,
        "rules": {
            "active": trend_rules_out["active"],
            "category": trend_rules_out["category"],
            "escalate": trend_rules_out["escalate"],
            "rules_version": trend_rules_out["rules_version"],
            "message": trend_rules_out["message"],
            "triggered": trend_rules_out["triggered"],
        },
    }
    return response


def prediction_series(patient, request=None):
    """Serialized predictions for a patient, oldest first. Each entry names
    the health worker who recorded the visit (worker names are not patient
    PII — the administrator history view depends on them)."""
    rows = (
        Prediction.objects.filter(assessment__patient=patient)
        .select_related("assessment", "assessment__created_by")
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
            "recorded_by": (
                p.assessment.created_by.full_name or p.assessment.created_by.username
                if p.assessment.created_by
                else None
            ),
            "recorded_by_photo_url": (
                user_photo_url(p.assessment.created_by.photo, request)
                if p.assessment.created_by
                else None
            ),
        }
        for p in rows
    ]


def treating_workers(patient):
    """Health workers connected to this patient: the record creator plus every
    worker who recorded an assessment, most recent first. Shown on the
    administrator history view ("who treated this patient")."""
    names = []
    for a in patient.assessments.exclude(created_by=None).order_by("-visit_date", "-id").select_related("created_by"):
        name = a.created_by.full_name or a.created_by.username
        if name and name not in names:
            names.append(name)
    if patient.created_by:
        name = patient.created_by.full_name or patient.created_by.username
        if name and name not in names:
            names.append(name)
    return names


def build_response(assessment, prediction, rules_out, alerts, trend):
    prediction_out = {
        "risk_level": prediction.risk_level,
        "probability": prediction.probability,
        "probabilities": prediction.probabilities,
        "model": {"name": prediction.model_name, "version": prediction.model_version},
        "explanation": prediction.explanation,
    }
    references, reference_warnings = guideline_references(rules_out, prediction_out)
    references = attach_document_versions(references)
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
        # Structured decision support: the ML estimate, the deterministic
        # rule outcome and the retrieved guideline passages, clearly
        # separated and traceable. References are retrieved citations, not
        # clinical endorsements; SHAP factors are model attributions, not
        # medical causes.
        "decision_support": {
            "ml": {
                "risk_level": prediction.risk_level,
                "probability": prediction.probability,
                "probabilities": prediction.probabilities,
                "model": {"name": prediction.model_name, "version": prediction.model_version},
                "top_factors": [
                    {
                        "feature": f["feature"],
                        "label": f["label"],
                        "impact": f["impact"],
                        "direction": f["direction"],
                        "note": "contribution to the model's prediction (SHAP), not a medical cause",
                    }
                    for f in ((prediction.explanation or {}).get("features") or [])[:3]
                ],
            },
            "rules": {
                "category": rules_out["category"],
                "escalate": rules_out["escalate"],
                "triggered": rules_out["triggered"],
                "rules_version": rules_out["rules_version"],
                "note": "deterministic, versioned rule evaluation — not machine learning",
            },
            "references": references,
            "reference_warnings": reference_warnings,
        },
        "disclaimer": DISCLAIMER,
    }
