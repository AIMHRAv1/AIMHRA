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
        raise serializers.ValidationError("Public registration is disabled. Ask an administrator to create your account.")


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

    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name", "phone", "role", "password", "is_active", "date_joined"]
        read_only_fields = ["id", "date_joined"]

    def validate_role(self, value):
        if value == User.ROLE_PATIENT:
            raise serializers.ValidationError("Patient records do not require user accounts.")
        return value

    def validate_password(self, value):
        if not value:
            raise serializers.ValidationError("A password is required when creating an account.")
        validate_password(value)
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "A password is required when creating an account."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=["password"])
        return instance
