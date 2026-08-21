"""Role-based permission helpers.

Roles: PATIENT, HEALTHCARE_WORKER, ADMIN (stored on accounts.User).
"""
from rest_framework.permissions import BasePermission


class IsPatient(BasePermission):
    message = "This endpoint is restricted to patient accounts."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "PATIENT")


class IsHealthcareWorker(BasePermission):
    message = "This endpoint is restricted to healthcare workers."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("HEALTHCARE_WORKER", "ADMIN")
        )


class IsAdmin(BasePermission):
    message = "This endpoint is restricted to administrators."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "ADMIN")


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role == "ADMIN"
