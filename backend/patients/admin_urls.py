from django.urls import path

from patients import views

urlpatterns = [
    path("stats/", views.SystemStatsView.as_view(), name="admin-stats"),
]
