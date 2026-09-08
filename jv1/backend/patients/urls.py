from django.urls import path

from patients import views

urlpatterns = [
    path("create/", views.PatientCreateView.as_view(), name="patient-create"),
    path("me/", views.MyProfileView.as_view(), name="my-patient-profile"),
    path("", views.PatientListView.as_view(), name="patient-list"),
    path("<int:pk>/", views.PatientDetailView.as_view(), name="patient-detail"),
    path("assignments/", views.PatientAssignmentListView.as_view(), name="patient-assignments"),
    path("assignments/<int:pk>/", views.PatientAssignmentDetailView.as_view(), name="patient-assignment-detail"),
]
