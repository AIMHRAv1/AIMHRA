from django.contrib import admin

from assessments.models import Alert, Assessment, Prediction


class PredictionInline(admin.StackedInline):
    model = Prediction
    extra = 0


class AlertInline(admin.TabularInline):
    model = Alert
    extra = 0


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "visit_date", "gestational_week", "created_at")
    list_filter = ("visit_date",)
    inlines = [PredictionInline, AlertInline]


@admin.register(Prediction)
@admin.register(Alert)
class SimpleAdmin(admin.ModelAdmin):
    pass
