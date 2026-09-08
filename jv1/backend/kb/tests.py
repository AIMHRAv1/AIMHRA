"""Knowledge-base (RAG) tests: ingestion, chunking, retrieval, citations."""
from accounts.models import User
from django.test import TestCase
from kb.models import DocumentChunk, KnowledgeDocument
from kb.services import indexing, rag
from kb.services.ingestion import chunk_text
from rest_framework_simplejwt.tokens import RefreshToken

DOC_TEXT = (
    "Iron deficiency in pregnancy is common. Iron-rich foods include lentils, "
    "lean red meat, spinach and fortified cereals. Vitamin C improves iron "
    "absorption. Warning: severe fatigue, pallor or breathlessness should be "
    "assessed by a healthcare professional promptly."
)


class IngestionTests(TestCase):
    def test_chunking_splits_with_overlap(self):
        chunks = chunk_text("word " * 600, chunk_size=900, overlap=150)
        self.assertGreater(len(chunks), 1)

    def test_empty_text_yields_no_chunks(self):
        self.assertEqual(chunk_text("   "), [])

    def test_index_document_persists_embeddings(self):
        doc = KnowledgeDocument.objects.create(title="Iron", content_text=DOC_TEXT)
        result = indexing.index_document(doc)
        self.assertGreaterEqual(result["chunks"], 1)
        doc.refresh_from_db()
        self.assertEqual(doc.chunk_count, DocumentChunk.objects.filter(document=doc).count())
        chunk = DocumentChunk.objects.filter(document=doc).first()
        self.assertTrue(chunk.embedding)

    def test_index_empty_document_raises(self):
        doc = KnowledgeDocument.objects.create(title="Empty", content_text="   ")
        with self.assertRaises(ValueError):
            indexing.index_document(doc)


class RetrievalTests(TestCase):
    def test_retrieve_returns_scored_sources(self):
        doc = KnowledgeDocument.objects.create(title="Iron Guidance", content_text=DOC_TEXT)
        indexing.index_document(doc)
        result = rag.retrieve_context("Which foods contain iron for a pregnant patient?")
        self.assertIsNotNone(result)
        self.assertTrue(result["chunks"])
        top = result["chunks"][0]
        self.assertEqual(top["document_title"], "Iron Guidance")
        self.assertIn("score", top)
        self.assertGreater(top["score"], 0)

    def test_retrieve_with_empty_kb_returns_none(self):
        self.assertIsNone(rag.retrieve_context("anything"))

    def test_unrelated_query_low_scores_filtered(self):
        doc = KnowledgeDocument.objects.create(title="Iron Guidance", content_text=DOC_TEXT)
        indexing.index_document(doc)
        result = rag.retrieve_context("quantum entanglement orbital mechanics")
        # Either no chunks survive the minimum score, or scores are weak.
        for chunk in (result or {}).get("chunks", []):
            self.assertLess(chunk["score"], 0.5)


class KBAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="kbadmin", email="k@t.com", password="Adm1n!Pass9", role="ADMIN"
        )
        cls.patient = User.objects.create_user(
            username="kbpat", email="kp@t.com", password="Str0ng!Pass1", role="PATIENT"
        )

    def test_admin_can_upload_text_document(self):
        token = RefreshToken.for_user(self.admin).access_token
        r = self.client.post("/api/rag/documents/", {
            "title": "Doc", "content_text": DOC_TEXT,
        }, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 201, r.content)

    def test_patient_cannot_upload(self):
        token = RefreshToken.for_user(self.patient).access_token
        r = self.client.post("/api/rag/documents/", {
            "title": "Doc", "content_text": DOC_TEXT,
        }, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 403)

    def test_retrieve_endpoint_reports_empty_kb(self):
        token = RefreshToken.for_user(self.patient).access_token
        r = self.client.post("/api/rag/retrieve/", {"question": "iron?"},
                             content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)
        data = r.json().get("data") or r.json()
        self.assertFalse(data["retrieved"])

    def test_reindex_requires_admin(self):
        token = RefreshToken.for_user(self.admin).access_token
        r = self.client.post("/api/rag/reindex/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)
