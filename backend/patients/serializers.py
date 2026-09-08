from rest_framework import serializers

from patients.models import PatientAssignment, PatientProfile


class PatientProfileSerializer(serializers.ModelSerializer):
    """Serializes a standalone patient record with optional clinical summary
    fields (provided via the ``patient_summaries`` serializer context)."""

    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    current_risk = serializers.SerializerMethodField()
    current_confidence = serializers.SerializerMethodField()
    current_trend_status = serializers.SerializerMethodField()
    current_trend_direction = serializers.SerializerMethodField()
    assessment_count = serializers.SerializerMethodField()
    last_assessment_date = serializers.SerializerMethodField()
    open_alert_count = serializers.SerializerMethodField()

    class Meta:
        model = PatientProfile
        fields = [
            "id", "patient_code", "full_name", "email", "phone", "address",
            "date_of_birth", "blood_group", "gestational_week_at_registration",
            "estimated_due_date", "gravidity", "parity", "medical_history_notes",
            "allergies", "emergency_contact_name", "emergency_contact_phone",
            "obstetric_history_notes", "current_medications", "additional_notes",
            "created_by", "created_by_name", "is_active", "archived_at",
            "created_at", "updated_at",
            "current_risk", "current_confidence", "assessment_count",
            "last_assessment_date", "open_alert_count",
            "current_trend_status", "current_trend_direction",
        ]
        read_only_fields = [
            "id", "patient_code", "created_by", "created_at", "updated_at",
            "current_trend_status", "current_trend_direction",
            "last_assessment_date", "open_alert_count",
        ]

    def _summary(self, obj):
        return (self.context.get("patient_summaries") or {}).get(obj.id, {})

    def get_current_risk(self, obj):
        return self._summary(obj).get("current_risk")

    def get_current_confidence(self, obj):
        return self._summary(obj).get("current_confidence")

    def get_current_trend_status(self, obj):
        return self._summary(obj).get("current_trend_status")

    def get_current_trend_direction(self, obj):
        return self._summary(obj).get("current_trend_direction")

    def get_assessment_count(self, obj):
        return self._summary(obj).get("assessment_count", 0)

    def get_last_assessment_date(self, obj):
        return self._summary(obj).get("last_assessment_date")

    def get_open_alert_count(self, obj):
        return self._summary(obj).get("open_alert_count", 0)

    def validate_gravidity(self, value):
        if value is not None and value > 30:
            raise serializers.ValidationError("Gravidity looks implausible (max 30).")
        return value

    def validate_gestational_week_at_registration(self, value):
        if value is not None and not (1 <= value <= 45):
            raise serializers.ValidationError("Gestational week must be between 1 and 45.")
        return value

    def validate_blood_group(self, value):
        if value:
            normalized = value.upper().replace(" ", "")
            # Rh factor may be unknown in practice, so the plain A / B / AB / O
            # forms are accepted alongside the fully-qualified ones.
            allowed = {
                "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-",
                "A", "B", "AB", "O", "UNKNOWN",
            }
            if normalized not in allowed:
                raise serializers.ValidationError(
                    "Blood group must be one of A+, A-, B+, B-, AB+, AB-, O+, O- "
                    "(or A, B, AB, O if the Rh factor is unknown)."
                )
            return normalized
        return value

class PatientAssignmentSerializer(serializers.ModelSerializer):
    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    healthcare_worker_username = serializers.CharField(
        source="healthcare_worker.username", read_only=True
    )
    assigned_by_username = serializers.CharField(
        source="assigned_by.username", read_only=True, default=None
    )

    class Meta:
        model = PatientAssignment
        fields = [
            "id", "healthcare_worker", "healthcare_worker_username",
            "patient", "patient_code", "patient_name", "assigned_by", "assigned_by_username", "created_at",
        ]
        read_only_fields = ["id", "assigned_by", "created_at"]
