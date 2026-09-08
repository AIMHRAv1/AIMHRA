from django.db import models

# Keep action names a controlled vocabulary so logs are searchable.
ACTION_LOGIN = "LOGIN"
ACTION_LOGIN_FAILED = "LOGIN_FAILED"
ACTION_REGISTER = "REGISTER"
ACTION_PROFILE_UPDATED = "PROFILE_UPDATED"
ACTION_PASSWORD_CHANGED = "PASSWORD_CHANGED"
ACTION_ASSESSMENT_CREATED = "ASSESSMENT_CREATED"
ACTION_PREDICTION = "PREDICTION"
ACTION_RULE_ESCALATION = "RULE_ESCALATION"
ACTION_CHAT_ACCESS = "CHAT_ACCESS"
ACTION_REPORT_GENERATED = "REPORT_GENERATED"
ACTION_MODEL_TRAINED = "MODEL_TRAINED"
ACTION_MODEL_ACTIVATED = "MODEL_ACTIVATED"
ACTION_KB_UPLOADED = "KB_UPLOADED"
ACTION_KB_REINDEXED = "KB_REINDEXED"
ACTION_KB_DELETED = "KB_DELETED"
ACTION_USER_UPDATED = "USER_UPDATED"
ACTION_PATIENT_ASSIGNED = "PATIENT_ASSIGNED"
ACTION_PATIENT_CREATED = "PATIENT_CREATED"
ACTION_PATIENT_UPDATED = "PATIENT_UPDATED"


class AuditLog(models.Model):
    ACTIONS = (
        (ACTION_LOGIN, "Login"),
        (ACTION_LOGIN_FAILED, "Failed login"),
        (ACTION_REGISTER, "User registration"),
        (ACTION_PROFILE_UPDATED, "Profile updated"),
        (ACTION_PASSWORD_CHANGED, "Password changed"),
        (ACTION_ASSESSMENT_CREATED, "Assessment created"),
        (ACTION_PREDICTION, "Prediction generated"),
        (ACTION_RULE_ESCALATION, "Rule-based escalation"),
        (ACTION_CHAT_ACCESS, "Chat access"),
        (ACTION_REPORT_GENERATED, "Report generated"),
        (ACTION_MODEL_TRAINED, "Model trained"),
        (ACTION_MODEL_ACTIVATED, "Model activated"),
        (ACTION_KB_UPLOADED, "Knowledge document uploaded"),
        (ACTION_KB_REINDEXED, "Knowledge base re-indexed"),
        (ACTION_KB_DELETED, "Knowledge document deleted"),
        (ACTION_USER_UPDATED, "User account updated"),
        (ACTION_PATIENT_ASSIGNED, "Patient assigned to healthcare worker"),
        (ACTION_PATIENT_CREATED, "Patient record created"),
        (ACTION_PATIENT_UPDATED, "Patient record updated"),
    )

    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=32, choices=ACTIONS)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    # Non-sensitive summary only. Never store medical values or chat content here.
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["action", "created_at"])]

    def __str__(self):
        return f"{self.action} {self.target_type}#{self.target_id} by {self.user} at {self.created_at}"
