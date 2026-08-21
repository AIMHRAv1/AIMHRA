from django.urls import path

from reports import views

urlpatterns = [
    path("", views.ReportListCreateView.as_view(), name="reports"),
    path("<int:pk>/download/", views.ReportDownloadView.as_view(), name="report-download"),
]
