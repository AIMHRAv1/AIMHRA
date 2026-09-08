from django.urls import path

from assessments import views

app_name = "assessments"

urlpatterns = [
    path("", views.AssessmentListCreateView.as_view(), name="assessments"),
    path("<int:pk>/", views.AssessmentDetailView.as_view(), name="assessment-detail"),
    path("risk-history/", views.RiskHistoryView.as_view(), name="risk-history"),
    path("risk-trends/", views.RiskTrendView.as_view(), name="risk-trends"),
    path("alerts/", views.AlertListView.as_view(), name="alerts"),
    path("alerts/<int:pk>/ack/", views.AlertAckView.as_view(), name="alert-ack"),
]
