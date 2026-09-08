"""
Structured API error handling.

Every error response uses the shape:

    {"success": false, "error": {"code": ..., "message": ..., "details": {...}}}
"""
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import set_rollback

logger = logging.getLogger(__name__)

ERROR_CODE_BY_STATUS = {
    400: "VALIDATION_ERROR",
    401: "AUTHENTICATION_ERROR",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class ApiError(Exception):
    """Raise from services/views for a clean structured error response."""

    def __init__(self, message, code="INTERNAL_ERROR", status_code=400, details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


def error_response(code, message, details=None, status_code=400):
    return Response(
        {"success": False, "error": {"code": code, "message": message, "details": details or {}}},
        status=status_code,
    )


def flatten_error_messages(detail):
    """Flatten nested DRF error detail (dicts / lists / ErrorDetail) into one
    human-readable message so validation errors are never hidden behind a
    generic banner."""
    messages = []

    def collect(value):
        if isinstance(value, str):
            messages.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                collect(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                collect(v)
        elif value is not None:
            messages.append(str(value))

    collect(detail)
    return " ".join(m.strip() for m in messages if m.strip()) or "Request could not be processed."


def structured_exception_handler(exc, context):
    """DRF exception handler producing the project-wide error envelope."""
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    if isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()
    if isinstance(exc, ApiError):
        return error_response(exc.code, exc.message, exc.details, exc.status_code)
    if isinstance(exc, exceptions.APIException):
        set_rollback()
        code = ERROR_CODE_BY_STATUS.get(exc.status_code, "API_ERROR")
        details = {}
        if isinstance(exc, exceptions.ValidationError):
            code = "VALIDATION_ERROR"
            details = exc.detail
        elif isinstance(exc, exceptions.NotAuthenticated):
            code = "AUTHENTICATION_ERROR"
        elif isinstance(exc, exceptions.AuthenticationFailed):
            code = "AUTHENTICATION_ERROR"
        message = flatten_error_messages(exc.detail)
        return error_response(code, message, details, exc.status_code)
    # Unhandled exception: log it, never leak stack traces to the client.
    logger.exception("Unhandled API error in %s", context.get("view"), exc_info=exc)
    set_rollback()
    return error_response(
        "INTERNAL_ERROR",
        "An unexpected error occurred. The issue has been logged.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
