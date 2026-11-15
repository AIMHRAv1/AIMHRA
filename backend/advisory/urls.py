from django.urls import path

from advisory import views

urlpatterns = [
    path("", views.AdvisoryGenerateView.as_view(), name="advisory-generate"),
    path("detail/", views.AdvisoryDetailView.as_view(), name="advisory-detail"),
]
