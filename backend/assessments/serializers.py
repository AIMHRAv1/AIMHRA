from django.utils import timezone
from rest_framework import serializers

from assessments.models import Alert, Assessment, Prediction
from assessments.rules.engine import load_rules
from mlcore.constants import PLAUSIBILITY_RANGES


class AssessmentSerializer(serializers.ModelSerializer):
    """Backend-authoritative validation for assessment input.

    Range checks use the same documented plausibility ranges that clean the
    training data, so inference inputs are consistent with training inputs.
    """

    prediction = serializers.SerializerMethodField()

    class Meta:
        model = Assessment
        fields = [
            "id", "patient", "visit_date", "gestational_week", "age", "body_temperature",
            "heart_rate", "systolic_bp", "diastolic_bp", "bmi", "hba1c", "fasting_glucose",
            "symptoms", "notes", "created_at", "prediction",
        ]
        read_only_fields = ["id", "patient", "created_at", "prediction"]

    def get_prediction(self, obj):
        pred = getattr(obj, "prediction", None)
        if pred is None:
            return None
        return {
            "risk_level": pred.risk_level,
            "probability": pred.probability,
            "probabilities": pred.probabilities,
            "model": {"name": pred.model_name, "version": pred.model_version},
            "explanation": pred.explanation,
        }

    def validate_visit_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Visit date cannot be in the future.")
        return value

    def validate_gestational_week(self, value):
        if value is not None and not (1 <= value <= 45):
            raise serializers.ValidationError("Gestational week must be between 1 and 45.")
        return value

    def validate_symptoms(self, value):
        vocabulary = set(load_rules().get("symptom_vocabulary", []))
        unknown = [s for s in value if s not in vocabulary]
        if unknown:
            raise serializers.ValidationError(f"Unknown symptom codes: {unknown}.")
        return value

    def validate(self, attrs):
        for field, (low, high) in PLAUSIBILITY_RANGES.items():
            value = attrs.get(field)
            if value is not None and not (low <= float(value) <= high):
                raise serializers.ValidationError(
                    {field: f"Value must be between {low} and {high} (physiologically plausible range)."}
                )
        sys_bp = attrs.get("systolic_bp")
        dia_bp = attrs.get("diastolic_bp")
        if sys_bp is not None and dia_bp is not None and dia_bp > sys_bp:
            raise serializers.ValidationError(
                {"diastolic_bp": "Diastolic blood pressure cannot exceed systolic blood pressure."}
            )
        return attrs


class AlertSerializer(serializers.ModelSerializer):
    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)

    class Meta:
        model = Alert
        fields = [
            "id", "assessment", "patient", "patient_code", "patient_name", "category", "rule_id",
            "rule_description", "message", "rules_version", "status", "created_at",
        ]


class AlertAckSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ACKNOWLEDGED", "RESOLVED"])
