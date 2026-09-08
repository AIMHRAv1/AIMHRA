import logging

import requests
from django.conf import settings

from notifications.models import SmsLog

logger = logging.getLogger(__name__)


def send_sms_alert(to_number: str, message: str, related_alert=None) -> bool:
    """Send through Sparrow when configured; otherwise record sandbox intent."""
    token = getattr(settings, "SPARROW_SMS_TOKEN", "")
    sender = getattr(settings, "SPARROW_SMS_FROM", "")
    status = "sandbox"
    success = True
    try:
        if token:
            response = requests.post(
                "https://api.sparrowsms.com/v2/sms/",
                data={"token": token, "from": sender, "to": to_number, "text": message},
                timeout=5,
            )
            response.raise_for_status()
            status = "sent"
        else:
            logger.info("SMS sandbox: would send to %s: %s", to_number, message)
    except Exception:
        success = False
        status = "failed"
        logger.exception("SMS delivery failed for %s", to_number)
    SmsLog.objects.create(recipient=to_number, message=message, status=status, related_alert=related_alert)
    return success