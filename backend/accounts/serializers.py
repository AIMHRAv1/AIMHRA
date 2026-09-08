from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.db.models import Q

from accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name", "phone", "role", "date_joined", "is_active"]
        read_only_fields = ["id", "role", "date_joined", "is_active"]


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login serializer that also logs attempts for the audit trail."""

    def validate(self, attrs):
        from audit import services as audit_svc

        failure_reason = "invalid_credentials"
        try:
            data = super().validate(attrs)
            if self.user.role not in (User.ROLE_HEALTHCARE_WORKER, User.ROLE_ADMIN):
                # Legacy / unexpected roles (e.g. a pre-migration PATIENT account)
                # must never authenticate through the application login flow.
                failure_reason = "role_not_allowed"
                raise AuthenticationFailed("No active account found with the given credentials.")
        except Exception:
            audit_svc.log_event(
                self.context.get("request"),
                "LOGIN_FAILED",
                target_type="user",
                target_id=attrs.get("username", ""),
                detail={"reason": failure_reason},
            )
            raise
        audit_svc.log_event(
            self.context.get("request"), "LOGIN", target_type="user", target_id=str(self.user.id)
        )
        data["user"] = UserSerializer(self.user).data
        return data


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh flow that refuses tokens belonging to legacy/deactivated accounts.

    JWT access tokens are already rejected by the authentication backend when the
    user is inactive; this serializer closes the refresh loophole so a legacy
    PATIENT (or deactivated) account can never mint a fresh session.
    """

    def validate(self, attrs):
        data = super().validate(attrs)
        try:
            from rest_framework_simplejwt.tokens import RefreshToken

            refresh = RefreshToken(attrs["refresh"])
            user_id = refresh.payload.get("user_id")
            user = User.objects.filter(pk=user_id).first()
            valid = (
                user is not None
                and user.is_active
                and user.role in (User.ROLE_HEALTHCARE_WORKER, User.ROLE_ADMIN)
            )
            if not valid:
                raise AuthenticationFailed("No active account found with the given credentials.")
        except AuthenticationFailed:
            raise
        except Exception as exc:
            raise AuthenticationFailed("Invalid token.") from exc
        return data


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class UserAdminSerializer(serializers.ModelSerializer):
    """Admin-facing user serializer (role editing allowed)."""

    patients_handled_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name", "phone", "role", "is_active", "date_joined", "patients_handled_count"]
        read_only_fields = ["id", "date_joined"]

    def get_patients_handled_count(self, user):
        from patients.models import PatientProfile

        return PatientProfile.objects.filter(
            Q(created_by=user) | Q(assigned_workers__healthcare_worker=user)
        ).distinct().count()
