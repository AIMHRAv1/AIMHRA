from django.contrib import admin

from .models import OcrExtraction


@admin.register(OcrExtraction)
class OcrExtractionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "file_type", "engine", "fields_extracted", "fields_flagged", "duration_ms", "created_at")
    list_filter = ("file_type", "engine")
    readonly_fields = ("created_at",)
