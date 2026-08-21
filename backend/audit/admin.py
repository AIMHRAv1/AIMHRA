from django.contrib import admin

from audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "target_type", "target_id", "ip_address", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("target_id", "user__username")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
