from django.db import models


class KnowledgeDocument(models.Model):
    """An ingested medical knowledge document (PDF/TXT/MD)."""

    title = models.CharField(max_length=255)
    source_url = models.CharField(max_length=512, blank=True, default="", help_text="Provenance URL if available")
    file = models.FileField(upload_to="kb/documents/", blank=True)
    content_text = models.TextField(blank=True, default="", help_text="Extracted full text for text-based sources")
    sha256 = models.CharField(max_length=64, blank=True, default="")
    chunk_count = models.PositiveIntegerField(default=0)
    indexed_at = models.DateTimeField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL, related_name="kb_documents"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class DocumentChunk(models.Model):
    """A chunk of a document with its embedding vector (local backend).

    With the OpenAI embedding backend the vector is also cached here so
    retrieval works without re-calling the API."""

    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    section = models.CharField(max_length=255, blank=True, default="")
    text = models.TextField()
    embedding = models.JSONField(default=list)
    embedding_backend = models.CharField(max_length=32, default="local")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document", "chunk_index"]
        indexes = [models.Index(fields=["document", "chunk_index"])]
