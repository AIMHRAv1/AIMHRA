from rest_framework import serializers

from patients.models import PatientAssignment, PatientProfile


class PatientProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=False, required=False)
    username = serializers.CharField(source="user.username", read_only=True, allow_null=True)
    email = serializers.CharField(source="user.email", read_only=True, allow_null=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not data["full_name"] and instance.user_id:
            data["full_name"] = instance.user.full_name
        if not data["phone_number"] and instance.user_id:
            data["phone_number"] = instance.user.phone
        return data

    class Meta:
        model = PatientProfile
        fields = [
            "id", "patient_code", "username", "full_name", "email", "phone_number",
            "emergency_contact_number", "district",
            "date_of_birth", "blood_group", "gestational_week_at_registration",
            "estimated_due_date", "gravidity", "parity", "medical_history_notes",
            "allergies", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "patient_code", "created_at", "updated_at"]

    def validate_gravidity(self, value):
        if value is not None and value > 30:
            raise serializers.ValidationError("Gravidity looks implausible (max 30).")
        return value

    def validate_gestational_week_at_registration(self, value):
        if value is not None and not (1 <= value <= 45):
            raise serializers.ValidationError("Gestational week must be between 1 and 45.")
        return value


class PatientAssignmentSerializer(serializers.ModelSerializer):
    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
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
            "patient", "patient_code", "assigned_by", "assigned_by_username", "created_at",
        ]
        read_only_fields = ["id", "assigned_by", "created_at"]
