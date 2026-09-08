import logging

from django.contrib.auth import authenticate
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.models import User
from accounts.serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserAdminSerializer,
    UserSerializer,
)
from audit import services as audit_svc
from core.permissions import IsAdmin

logger = logging.getLogger(__name__)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [IsAdmin]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        audit_svc.log_event(request, "REGISTER", target_type="user", target_id=str(user.id))
        return Response(
            {
                "success": True,
                "data": {
                    "user": UserSerializer(user).data,
                    "tokens": None,
                },
            },
            status=status.HTTP_201_CREATED,
        )


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class LogoutView(APIView):
    """Blacklists the provided refresh token so it can no longer be used."""

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "refresh token required", "details": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh).blacklist()
        except Exception:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid refresh token.", "details": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"success": True, "data": {"logged_out": True}})


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        audit_svc.log_event(request, "PROFILE_UPDATED", target_type="user", target_id=str(request.user.id))
        return response


class ChangePasswordView(APIView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        audit_svc.log_event(request, "PASSWORD_CHANGED", target_type="user", target_id=str(request.user.id))
        return Response({"success": True, "data": {"changed": True}})


class PasswordResetRequestView(APIView):
    """Password-reset request architecture.

    Always responds generically (never reveals whether an email exists).
    Delivery uses the configured Django email backend; in local development
    with the console backend the token link is printed to the server log.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            token = RefreshToken.for_user(user)
            reset_link = f"/reset-password?token={str(token.access_token)}"
            try:
                from django.conf import settings as dj_settings
                from django.core.mail import send_mail

                send_mail(
                    subject="AIMHRA password reset request",
                    message=f"Use this link to reset your password: {reset_link}\n"
                    "If you did not request this, ignore this email.",
                    from_email=dj_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=True,
                )
            except Exception:
                logger.warning("Password-reset email could not be sent; check EMAIL_BACKEND settings.")
        return Response({"success": True, "data": {"detail": "If the email is registered, reset instructions have been sent."}})


class UserManagementView(generics.ListCreateAPIView):
    """Admin-only user management. Creates staff/admin/healthcare-worker accounts."""

    permission_classes = [IsAdmin]
    queryset = User.objects.all().order_by("-date_joined")

    def get_serializer_class(self):
        return UserAdminSerializer

    def perform_create(self, serializer):
        user = serializer.save()
        audit_svc.log_event(
            self.request, "USER_UPDATED", target_type="user", target_id=str(user.id),
            detail={"created": True, "role": user.role},
        )


class UserManagementDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdmin]
    queryset = User.objects.all()
    serializer_class = UserAdminSerializer

    def perform_update(self, serializer):
        user = serializer.save()
        audit_svc.log_event(
            self.request, "USER_UPDATED", target_type="user", target_id=str(user.id),
            detail={"updated": True, "role": user.role, "is_active": user.is_active},
        )

    def perform_destroy(self, instance):
        # Soft-delete style: deactivate instead of deleting, preserving audit history.
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        audit_svc.log_event(
            self.request, "USER_UPDATED", target_type="user", target_id=str(instance.id),
            detail={"deactivated": True},
        )
