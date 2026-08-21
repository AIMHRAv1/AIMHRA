from django.contrib import admin

from kb.models import DocumentChunk, KnowledgeDocument


class DocumentChunkInline(admin.TabularInline):
    model = DocumentChunk
    extra = 0
    max_num = 0


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "chunk_count", "indexed_at", "uploaded_by")
    search_fields = ("title",)


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "embedding_backend")
    list_filter = ("embedding_backend",)
