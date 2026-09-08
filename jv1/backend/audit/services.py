"""Central audit logging service. Import this everywhere instead of writing
AuditLog rows directly, so redaction rules stay in one place."""
import logging

from audit.models import AuditLog

logger = logging.getLogger(__name__)

# Keys that must never be written into audit detail payloads.
REDACTED_KEYS = {"password", "token", "access", "refresh", "secret", "ssn"}


def _redact(detail):
    if not isinstance(detail, dict):
        return {}
    return {k: ("[redacted]" if k.lower() in REDACTED_KEYS else v) for k, v in detail.items()}


def log_event(request, action, target_type="", target_id="", detail=None):
    """Persist an audit entry. `request` may be None for system events."""
    try:
        user = getattr(request, "user", None) if request is not None else None
        ip = None
        if request is not None:
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
            ip = (forwarded.split(",")[0].strip() if forwarded else None) or request.META.get("REMOTE_ADDR")
        AuditLog.objects.create(
            user=user if (user and user.is_authenticated) else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id or ""),
            detail=_redact(detail or {}),
            ip_address=ip,
        )
    except Exception:  # audit must never break the request path
        logger.exception("Failed to write audit log for action %s", action)
