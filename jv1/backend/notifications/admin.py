from django.contrib import admin

from notifications.models import Facility, SmsLog

admin.site.register(Facility)
admin.site.register(SmsLog)