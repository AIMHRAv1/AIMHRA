from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name", "phone", "role", "date_joined", "is_active"]
        read_only_fields = ["id", "role", "date_joined", "is_active"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["username", "email", "full_name", "phone", "password", "confirm_password"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(attrs["password"])
        return attrs

    def create(self, validated_data):
        # Self-registration always creates a PATIENT. Healthcare-worker and
        # admin accounts are created by an administrator.
        return User.objects.create_user(role=User.ROLE_PATIENT, **validated_data)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login serializer that also logs attempts for the audit trail."""

    def validate(self, attrs):
        from audit import services as audit_svc

        try:
            data = super().validate(attrs)
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

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name", "phone", "role", "is_active", "date_joined"]
        read_only_fields = ["id", "date_joined"]
