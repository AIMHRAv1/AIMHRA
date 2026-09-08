from django.urls import path

from patients import views

urlpatterns = [
    path("", views.PatientListView.as_view(), name="patient-list"),
    path("<int:pk>/", views.PatientDetailView.as_view(), name="patient-detail"),
    path("assignments/", views.PatientAssignmentListView.as_view(), name="patient-assignments"),
    path("assignments/<int:pk>/", views.PatientAssignmentDetailView.as_view(), name="patient-assignment-detail"),
]