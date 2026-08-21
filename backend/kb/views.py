from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from audit.services import log_event
from core.exceptions import ApiError
from core.permissions import IsAdmin, IsAdminOrReadOnly
from core.responses import ok
from kb.models import DocumentChunk, KnowledgeDocument
from kb.serializers import (
    DocumentChunkSerializer,
    KnowledgeDocumentSerializer,
    KnowledgeDocumentUploadSerializer,
)
from kb.services import indexing, rag


class KnowledgeDocumentListCreateView(generics.ListCreateAPIView):
    # JSON for text-based documents (content_text); multipart for file uploads.
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAdminOrReadOnly]
    queryset = KnowledgeDocument.objects.all()

    def get_serializer_class(self):
        return KnowledgeDocumentUploadSerializer if self.request.method == "POST" else KnowledgeDocumentSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Respond with the full read serializer so chunk_count/indexed_at
        # reflect the completed indexing.
        document = serializer.instance
        return ok(KnowledgeDocumentSerializer(document).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        if not (serializer.validated_data.get("file") or serializer.validated_data.get("content_text")):
            raise ApiError("Provide either a file or content_text.", code="VALIDATION_ERROR", status_code=400)
        document = serializer.save(uploaded_by=self.request.user)
        document.sha256 = indexing.ingestion.document_sha256(document)
        document.save(update_fields=["sha256"])
        try:
            indexing.index_document(document)
        except ValueError as exc:
            document.delete()
            raise ApiError(str(exc), code="VALIDATION_ERROR", status_code=400)
        log_event(self.request, "KB_UPLOADED", target_type="kb_document", target_id=str(document.id),
                  detail={"title": document.title, "chunks": document.chunk_count})


class KnowledgeDocumentDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminOrReadOnly]
    queryset = KnowledgeDocument.objects.all()
    serializer_class = KnowledgeDocumentSerializer

    def perform_update(self, serializer):
        document = serializer.save()
        if any(f in self.request.data for f in ("file", "content_text")):
            indexing.index_document(document)
        log_event(self.request, "KB_UPLOADED", target_type="kb_document", target_id=str(document.id),
                  detail={"title": document.title, "updated": True})

    def perform_destroy(self, instance):
        log_event(self.request, "KB_DELETED", target_type="kb_document", target_id=str(instance.id),
                  detail={"title": instance.title})
        instance.delete()


class ReindexView(APIView):
    """Re-fit embeddings and re-index every document (admin)."""

    permission_classes = [IsAdmin]

    def post(self, request):
        documents = KnowledgeDocument.objects.all()
        count = 0
        for document in documents:
            try:
                indexing.index_document(document)
                count += 1
            except Exception:
                continue
        log_event(request, "KB_REINDEXED", target_type="kb", target_id="all", detail={"documents": count})
        return ok({"reindexed": count})


class DocumentChunksView(generics.ListAPIView):
    serializer_class = DocumentChunkSerializer

    def get_queryset(self):
        document = get_object_or_404(KnowledgeDocument, pk=self.kwargs["pk"])
        return DocumentChunk.objects.filter(document=document)


class RetrieveView(APIView):
    """Raw RAG retrieval endpoint (retrieval only, no generation)."""

    def post(self, request):
        question = (request.data.get("question") or "").strip()
        if not question:
            raise ApiError("`question` is required.", code="VALIDATION_ERROR", status_code=400)
        result = rag.retrieve_context(question, top_k=int(request.data.get("top_k", 5)))
        if result is None:
            return ok(
                {
                    "chunks": [],
                    "retrieved": False,
                    "message": "No indexed knowledge is available to answer this question.",
                }
            )
        return ok({"chunks": result["chunks"], "retrieved": True})
