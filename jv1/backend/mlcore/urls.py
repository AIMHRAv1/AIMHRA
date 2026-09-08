from django.urls import path

from mlcore import views

urlpatterns = [
    path("", views.ModelListView.as_view(), name="model-list"),
    path("compare/", views.ModelComparisonView.as_view(), name="model-compare"),
    path("<int:pk>/activate/", views.ModelActivateView.as_view(), name="model-activate"),
    path("feature-importance/", views.FeatureImportanceView.as_view(), name="model-feature-importance"),
    path("diagnostics/", views.ModelDiagnosticsView.as_view(), name="model-diagnostics"),
]
