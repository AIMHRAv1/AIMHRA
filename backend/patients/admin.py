from django.contrib import admin

from patients.models import PatientAssignment, PatientProfile


class PatientAssignmentInline(admin.TabularInline):
    model = PatientAssignment
    extra = 0


@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ("patient_code", "full_name", "phone", "created_by", "is_active", "created_at")
    search_fields = ("patient_code", "full_name", "phone", "email")
    inlines = [PatientAssignmentInline]
    list_filter = ("is_active",)


@admin.register(PatientAssignment)
class PatientAssignmentAdmin(admin.ModelAdmin):
    list_display = ("healthcare_worker", "patient", "assigned_by", "created_at")
