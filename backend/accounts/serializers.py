from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import User
from accounts.utils import user_photo_url


class UserSerializer(serializers.ModelSerializer):
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "full_name", "phone", "photo", "photo_url", "role",
            "date_joined", "is_active", "is_superuser",
        ]
        read_only_fields = ["id", "role", "date_joined", "is_active", "is_superuser"]

    def get_photo_url(self, obj):
        return user_photo_url(obj.photo, self.context.get("request"))

    def validate_photo(self, value):
        if value and value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Photo must be 5 MB or smaller.")
        return value


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login serializer that also logs attempts for the audit trail."""

    def validate(self, attrs):
        from audit import services as audit_svc

        try:
            data = super().validate(attrs)
            if self.user.role not in (User.ROLE_HEALTHCARE_WORKER, User.ROLE_ADMIN):
                # Legacy / unexpected roles (e.g. a pre-migration PATIENT account)
                # must never authenticate through the application login flow.
                audit_svc.log_event(
                    self.context.get("request"),
                    "LOGIN_FAILED",
                    target_type="user",
                    target_id=str(self.user.id),
                    detail={"reason": "role_not_allowed"},
                )
                raise AuthenticationFailed("No active account found with the given credentials.")
        except Exception:
            audit_svc.log_event(
                self.context.get("request"),
                "LOGIN_FAILED",
                target_type="user",
                target_id=attrs.get("username", ""),
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

    patients_handled = serializers.IntegerField(read_only=True, default=0)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "full_name", "phone", "photo", "photo_url", "role",
            "is_active", "date_joined", "is_superuser", "patients_handled",
        ]
        read_only_fields = ["id", "date_joined", "is_superuser", "patients_handled"]

    def get_photo_url(self, obj):
        return user_photo_url(obj.photo, self.context.get("request"))

    def validate_photo(self, value):
        role = self.initial_data.get("role", getattr(self.instance, "role", None))
        if value and role != User.ROLE_HEALTHCARE_WORKER:
            raise serializers.ValidationError("Only healthcare worker accounts can have a profile photo.")
        if value and value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Photo must be 5 MB or smaller.")
        return value

    def validate_role(self, value):
        request = self.context.get("request")
        user = request.user if request else None
        instance = self.instance
        if value == User.ROLE_ADMIN and not (user and user.is_superuser):
            raise serializers.ValidationError("Only a superuser can create administrator accounts.")
        if instance and instance.is_superuser and value != User.ROLE_ADMIN:
            raise serializers.ValidationError("A superuser account cannot be changed to another role.")
        if instance and instance.role == User.ROLE_ADMIN and not (user and user.is_superuser):
            if value != instance.role:
                raise serializers.ValidationError("Only a superuser can change an administrator's role.")
        return value

    def validate_is_active(self, value):
        request = self.context.get("request")
        user = request.user if request else None
        instance = self.instance
        if instance and instance.is_superuser and not value:
            raise serializers.ValidationError("A superuser account cannot be deactivated.")
        if (
            instance
            and instance.role == User.ROLE_ADMIN
            and instance.is_active != value
            and not (user and user.is_superuser)
        ):
            raise serializers.ValidationError("Only a superuser can activate or deactivate an administrator.")
        return value
