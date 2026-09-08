from rest_framework import serializers

from audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default=None)
    actor = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()
    target_label = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    ACTION_LABELS = {
        "LOGIN": "Signed in",
        "LOGIN_FAILED": "Failed sign-in",
        "PROFILE_UPDATED": "Updated profile",
        "PASSWORD_CHANGED": "Changed password",
        "ASSESSMENT_CREATED": "Recorded assessment",
        "PREDICTION": "Generated risk prediction",
        "RULE_ESCALATION": "Triggered clinical escalation",
        "CHAT_ACCESS": "Started patient chat",
        "REPORT_GENERATED": "Generated report",
        "MODEL_TRAINED": "Trained prediction model",
        "MODEL_ACTIVATED": "Activated prediction model",
        "KB_UPLOADED": "Updated knowledge document",
        "KB_REINDEXED": "Rebuilt knowledge index",
        "KB_DELETED": "Deleted knowledge document",
        "USER_UPDATED": "Updated user account",
        "PATIENT_ASSIGNED": "Assigned patient",
        "PATIENT_CREATED": "Created patient record",
        "PATIENT_UPDATED": "Updated patient record",
    }

    TARGET_LABELS = {
        "assessment": "Assessment",
        "chat_message": "Chat message",
        "chat_session": "Patient chat",
        "kb": "Knowledge base",
        "kb_document": "Knowledge document",
        "model_version": "Model version",
        "patient": "Patient record",
        "prediction": "Risk prediction",
        "report": "Clinical report",
        "user": "User account",
    }

    def get_actor(self, obj):
        if not obj.user:
            return "System"
        return obj.user.full_name or obj.user.username

    def get_action_label(self, obj):
        return self.ACTION_LABELS.get(obj.action, obj.get_action_display())

    def get_target_label(self, obj):
        label = self.TARGET_LABELS.get(obj.target_type, obj.target_type or "System")
        return f"{label} #{obj.target_id}" if obj.target_id and obj.target_id != "all" else label

    def get_summary(self, obj):
        detail = obj.detail or {}
        action = obj.action
        if action == "LOGIN_FAILED":
            return "Sign-in was rejected."
        if action == "ASSESSMENT_CREATED":
            return f"Assessment recorded for patient #{detail.get('patient', 'unknown')}."
        if action == "PREDICTION":
            risk = detail.get("risk_level")
            return f"Risk prediction generated{f' ({risk})' if risk else ''}."
        if action == "RULE_ESCALATION":
            return f"Escalation triggered: {detail.get('category', 'clinical rule') }."
        if action == "PATIENT_CREATED":
            return f"Patient record {detail.get('patient_code', 'created')}."
        if action == "PATIENT_UPDATED":
            return f"Patient record {detail.get('patient_code', 'updated')}."
        if action == "PATIENT_ASSIGNED":
            return "Patient access assignment changed."
        if action in {"KB_UPLOADED", "KB_DELETED"}:
            return str(detail.get("title") or "Knowledge document changed.")
        if action == "KB_REINDEXED":
            return f"{detail.get('documents', 0)} document(s) reindexed."
        if action == "MODEL_ACTIVATED":
            return f"Production model set to {detail.get('name', 'selected model')}."
        if action == "MODEL_TRAINED":
            return "A new prediction model was trained."
        if action == "CHAT_ACCESS":
            return "A patient chat session was created."
        if action == "REPORT_GENERATED":
            return "A clinical report was generated."
        if action == "PROFILE_UPDATED":
            return "User profile details were updated."
        if action == "PASSWORD_CHANGED":
            return "Account password was changed."
        if action == "USER_UPDATED":
            return "User account settings were updated."
        return self.get_action_label(obj)

    class Meta:
        model = AuditLog
        fields = [
            "id", "username", "actor", "action", "action_label", "target_type",
            "target_id", "target_label", "summary", "detail", "ip_address", "created_at",
        ]
