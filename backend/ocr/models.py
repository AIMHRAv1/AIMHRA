from django.conf import settings
from django.db import models


class OcrExtraction(models.Model):
    """Metadata record for one OCR extraction.

    Deliberately stores NO patient text and NO extracted values — only
    operational metadata (engine, counts, latency), mirroring the audit rule
    that medical values never enter logs.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="ocr_extractions"
    )
    file_type = models.CharField(max_length=8)  # jpg | png | pdf
    engine = models.CharField(max_length=32)  # tesseract | pymupdf_text
    fields_extracted = models.PositiveIntegerField(default=0)
    fields_flagged = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"OcrExtraction({self.file_type}, {self.engine}, {self.fields_extracted} fields)"
