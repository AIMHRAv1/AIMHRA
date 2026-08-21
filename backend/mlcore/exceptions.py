from rest_framework import status

from core.exceptions import ApiError


class ModelUnavailableError(ApiError):
    """Raised when no usable model exists — never fabricate a prediction."""

    def __init__(self, message):
        super().__init__(
            message,
            code="MODEL_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"hint": "Ask an administrator to train and activate a model."},
        )
