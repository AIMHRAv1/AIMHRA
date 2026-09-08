from django.db import models


class Facility(models.Model):
    name = models.CharField(max_length=160)
    district = models.CharField(max_length=128)
    phone_number = models.CharField(max_length=32)
    is_ceonc = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.district})"


class SmsLog(models.Model):
    recipient = models.CharField(max_length=32)
    message = models.TextField()
    status = models.CharField(max_length=32)
    sent_at = models.DateTimeField(auto_now_add=True)
    related_alert = models.ForeignKey(
        "assessments.Alert", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="sms_logs",
    )