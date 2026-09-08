from django.contrib import admin

from reports.models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "assessment", "generated_by", "created_at")
