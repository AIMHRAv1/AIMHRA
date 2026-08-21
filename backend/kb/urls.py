from django.urls import path

from kb import views

urlpatterns = [
    path("documents/", views.KnowledgeDocumentListCreateView.as_view(), name="kb-documents"),
    path("documents/<int:pk>/", views.KnowledgeDocumentDetailView.as_view(), name="kb-document-detail"),
    path("documents/<int:pk>/chunks/", views.DocumentChunksView.as_view(), name="kb-document-chunks"),
    path("reindex/", views.ReindexView.as_view(), name="kb-reindex"),
    path("retrieve/", views.RetrieveView.as_view(), name="kb-retrieve"),
]
