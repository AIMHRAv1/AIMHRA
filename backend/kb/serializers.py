from rest_framework import serializers

from kb.models import DocumentChunk, KnowledgeDocument


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True, default=None)

    class Meta:
        model = KnowledgeDocument
        fields = [
            "id", "title", "source_url", "file", "content_text", "sha256",
            "chunk_count", "indexed_at", "uploaded_by_username", "created_at",
        ]
        read_only_fields = ["id", "sha256", "chunk_count", "indexed_at", "created_at"]


class DocumentChunkSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source="document.title", read_only=True)

    class Meta:
        model = DocumentChunk
        fields = ["id", "document", "document_title", "chunk_index", "text", "embedding_backend"]


class KnowledgeDocumentUploadSerializer(serializers.ModelSerializer):
    """Admin upload: file (PDF/TXT/MD) or raw text."""

    class Meta:
        model = KnowledgeDocument
        fields = ["id", "title", "source_url", "file", "content_text"]
        read_only_fields = ["id"]
