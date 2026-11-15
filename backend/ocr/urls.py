from django.urls import path

from ocr import views

urlpatterns = [
    path("extract/", views.OcrExtractView.as_view(), name="ocr-extract"),
    path("feedback/", views.OcrFeedbackView.as_view(), name="ocr-feedback"),
]
