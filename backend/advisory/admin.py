from django.contrib import admin

from .models import Advisory


@admin.register(Advisory)
class AdvisoryAdmin(admin.ModelAdmin):
    list_display = ("id", "assessment", "risk_level", "rules_category", "generation_mode", "created_at")
    list_filter = ("risk_level", "rules_category", "generation_mode")
    readonly_fields = ("created_at",)
