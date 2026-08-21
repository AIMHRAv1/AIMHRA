"""
Middleware that guarantees a structured JSON error envelope even for
exceptions raised outside DRF views (e.g. middleware/URL resolution errors).
"""
import logging
import traceback

from django.http import JsonResponse

from core.exceptions import ERROR_CODE_BY_STATUS

logger = logging.getLogger(__name__)


class StructuredErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Django's 404/500 HTML pages for /api/ paths become JSON.
        if request.path.startswith("/api/") and response.status_code >= 400:
            ctype = response.headers.get("Content-Type", "")
            if "html" in ctype:
                code = ERROR_CODE_BY_STATUS.get(response.status_code, "API_ERROR")
                return JsonResponse(
                    {
                        "success": False,
                        "error": {
                            "code": code,
                            "message": "Request failed with status %d." % response.status_code,
                            "details": {},
                        },
                    },
                    status=response.status_code,
                )
        return response

    def process_exception(self, request, exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.path)
        from django.conf import settings as dj_settings

        message = "An unexpected error occurred. The issue has been logged."
        details = {}
        if dj_settings.DEBUG:
            details["debug_trace"] = traceback.format_exc()
        return JsonResponse(
            {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": message, "details": details},
            },
            status=500,
        )
