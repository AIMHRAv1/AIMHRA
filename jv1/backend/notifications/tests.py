from django.test import TestCase, override_settings

from assessments.models import Alert
from notifications.models import SmsLog
from notifications.services import send_sms_alert


class SmsSandboxTests(TestCase):
    @override_settings(SPARROW_SMS_TOKEN="")
    def test_sandbox_send_is_logged_without_credentials(self):
        self.assertTrue(send_sms_alert("9800000000", "Test alert"))
        log = SmsLog.objects.get()
        self.assertEqual(log.status, "sandbox")
        self.assertEqual(log.recipient, "9800000000")