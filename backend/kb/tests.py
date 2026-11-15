"""Knowledge-base (RAG) tests: ingestion, chunking, retrieval, citations."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accounts.models import User
from django.test import TestCase, override_settings
from kb.models import DocumentChunk, KnowledgeDocument
from kb.services import embeddings, indexing, rag, store
from kb.services.ingestion import chunk_document, chunk_text
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

    def test_chapter_and_recommendation_headings_are_saved_as_sections(self):
        doc = KnowledgeDocument.objects.create(
            title="Structured guidance",
            content_text=(
                "Chapter 1. Introduction\n\n"
                "This chapter introduces antenatal care.\n\n"
                "A.2: Iron and folic acid supplements\n\n"
                "Daily supplementation is discussed in this section."
            ),
        )

        chunks, _metadata = chunk_document(doc)

        self.assertIn("Chapter 1. Introduction", {section for _, _, section in chunks})
        self.assertIn(
            "A.2: Iron and folic acid supplements",
            {section for _, _, section in chunks},
        )

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

    def test_unrelated_natural_language_query_does_not_match_common_words(self):
        doc = KnowledgeDocument.objects.create(title="Iron Guidance", content_text=DOC_TEXT)
        indexing.index_document(doc)

        result = rag.retrieve_context("How do I repair a diesel engine?")

        self.assertFalse((result or {}).get("chunks", []))

    def test_maternal_health_queries_retrieve_relevant_sections_and_metadata(self):
        examples = [
            (
                "Hypertension guidance",
                "National Maternal Health Office",
                "https://example.test/hypertension",
                "# Hypertension in pregnancy\n\n"
                "Measure blood pressure during antenatal contacts. Raised blood pressure "
                "needs clinical assessment. Refer urgently when severe features are present.",
                "hypertension",
                "Hypertension in pregnancy",
            ),
            (
                "Pre-eclampsia guidance",
                "National Maternal Health Office",
                "https://example.test/preeclampsia",
                "# Pre-eclampsia\n\n"
                "Pre-eclampsia is a hypertensive disorder of pregnancy. Assess raised blood "
                "pressure and proteinuria according to the applicable clinical protocol.",
                "What is pre-eclampsia and how is it assessed?",
                "Pre-eclampsia",
            ),
            (
                "Antenatal care guidance",
                "National Maternal Health Office",
                "https://example.test/antenatal",
                "# Antenatal care contacts\n\n"
                "Antenatal care includes scheduled pregnancy contacts, health assessment, "
                "counselling and follow-up throughout pregnancy.",
                "What happens during antenatal care?",
                "Antenatal care contacts",
            ),
            (
                "Maternal danger signs",
                "National Maternal Health Office",
                "https://example.test/danger-signs",
                "# Danger signs in pregnancy\n\n"
                "Vaginal bleeding, convulsions, severe headache, blurred vision, difficulty "
                "breathing and reduced fetal movement require prompt clinical attention.",
                "What maternal danger signs require urgent attention?",
                "Danger signs in pregnancy",
            ),
        ]
        for title, organization, source, content, _question, _section in examples:
            doc = KnowledgeDocument.objects.create(
                title=title,
                issuing_organization=organization,
                source_url=source,
                content_text=content,
            )
            indexing.index_document(doc)

        for title, organization, source, _content, question, section in examples:
            with self.subTest(question=question):
                result = rag.retrieve_context(question)
                self.assertTrue(result and result["chunks"])
                top = result["chunks"][0]
                self.assertEqual(top["document_title"], title)
                self.assertEqual(top["issuing_organization"], organization)
                self.assertEqual(top["source_url"], source)
                self.assertEqual(top["section"], section)


class IndexPersistenceTests(TestCase):
    def test_local_vectorizer_survives_application_restart(self):
        with tempfile.TemporaryDirectory() as artifact_directory:
            with override_settings(RAG_ARTIFACTS_DIR=Path(artifact_directory)):
                doc = KnowledgeDocument.objects.create(
                    title="Iron Guidance",
                    source_url="https://example.test/iron",
                    content_text=DOC_TEXT,
                )
                indexing.index_document(doc)
                expected_vectors = list(
                    DocumentChunk.objects.filter(document=doc).values_list("embedding", flat=True)
                )

                embeddings._VECTORIZER = None
                embeddings._CORPUS_HASH = None
                embeddings._BACKEND = None
                result = rag.retrieve_context("Which foods contain iron?")

                self.assertTrue(result["chunks"])
                self.assertEqual(result["chunks"][0]["document_title"], "Iron Guidance")
                self.assertEqual(result["chunks"][0]["source"], "https://example.test/iron")
                self.assertEqual(
                    list(DocumentChunk.objects.filter(document=doc).values_list("embedding", flat=True)),
                    expected_vectors,
                )

    def test_invalid_local_artifact_rebuilds_from_persisted_chunks(self):
        with tempfile.TemporaryDirectory() as artifact_directory:
            with override_settings(RAG_ARTIFACTS_DIR=Path(artifact_directory)):
                doc = KnowledgeDocument.objects.create(title="Iron Guidance", content_text=DOC_TEXT)
                indexing.index_document(doc)
                artifact_path = Path(artifact_directory) / "tfidf.joblib"
                artifact_path.write_bytes(b"not a joblib artifact")
                embeddings._VECTORIZER = None
                embeddings._CORPUS_HASH = None
                embeddings._BACKEND = None

                result = rag.retrieve_context("Which foods contain iron?")

                self.assertTrue(result["chunks"])
                self.assertTrue(artifact_path.stat().st_size > len(b"not a joblib artifact"))

    def test_reindexing_replaces_chunks_without_duplicates(self):
        doc = KnowledgeDocument.objects.create(title="Iron Guidance", content_text=DOC_TEXT)
        first_result = indexing.index_document(doc)
        first_texts = list(
            DocumentChunk.objects.filter(document=doc).order_by("chunk_index").values_list("text", flat=True)
        )
        second_result = indexing.index_document(doc)

        chunks = DocumentChunk.objects.filter(document=doc)
        self.assertEqual(first_result["chunks"], second_result["chunks"])
        self.assertEqual(chunks.count(), second_result["chunks"])
        self.assertEqual(
            list(chunks.order_by("chunk_index").values_list("text", flat=True)),
            first_texts,
        )

    def test_pdf_page_numbers_are_preserved_on_chunks(self):
        doc = KnowledgeDocument.objects.create(title="Paged source", content_text="unused")
        page_texts = ["First page guidance.", "Second page guidance."]
        with patch(
            "kb.services.ingestion.extract_text",
            return_value=("\n\n".join(page_texts), {"pages": 2, "page_texts": page_texts}),
        ):
            indexing.index_document(doc)

        self.assertEqual(
            list(
                DocumentChunk.objects.filter(document=doc)
                .order_by("chunk_index")
                .values_list("page_number", flat=True)
            ),
            [1, 2],
        )
        retrieved = rag.retrieve_context("First page guidance")
        self.assertEqual(retrieved["chunks"][0]["page_number"], 1)
        self.assertIsNotNone(retrieved["chunks"][0]["chunk_id"])


class QdrantIndexingTests(TestCase):
    class FakeQdrantClient:
        def __init__(self):
            self.points = {}
            self.collection_created = False

        def collection_exists(self, collection_name):
            return self.collection_created

        def create_collection(self, collection_name, vectors_config):
            self.collection_created = True
            self.dimension = vectors_config.size

        def get_collection(self, collection_name):
            return SimpleNamespace(
                config=SimpleNamespace(
                    params=SimpleNamespace(vectors=SimpleNamespace(size=self.dimension))
                )
            )

        def delete(self, collection_name, points_selector, wait):
            self.points.clear()

        def upsert(self, collection_name, points, wait):
            for point in points:
                self.points[point.id] = point

        def query_points(self, collection_name, query, query_filter, limit, with_payload):
            return SimpleNamespace(
                points=[
                    SimpleNamespace(id=point.id, score=1.0, payload=point.payload)
                    for point in list(self.points.values())[:limit]
                ]
            )

    @override_settings(VECTOR_BACKEND="qdrant", VECTOR_DB_URL="http://qdrant.test")
    def test_qdrant_index_upserts_retrievable_chunks_once(self):
        client = self.FakeQdrantClient()
        doc = KnowledgeDocument.objects.create(
            title="Iron Guidance",
            source_url="https://example.test/iron",
            content_text=DOC_TEXT,
        )
        with patch("kb.services.store._qdrant_client", return_value=client):
            indexing.index_document(doc)
            expected_count = DocumentChunk.objects.filter(document=doc).count()
            self.assertEqual(len(client.points), expected_count)

            first_point = next(iter(client.points.values()))
            self.assertEqual(first_point.payload["document_title"], "Iron Guidance")
            self.assertEqual(first_point.payload["source"], "https://example.test/iron")
            self.assertEqual(
                store.retrieve(embeddings.embed_texts(["iron-rich foods"])[0], top_k=5)[0][0],
                first_point.payload["chunk_id"],
            )

            indexing.index_document(doc)
            self.assertEqual(
                len(client.points),
                DocumentChunk.objects.filter(document=doc).count(),
            )

    @override_settings(VECTOR_BACKEND="qdrant", VECTOR_DB_URL="http://qdrant.test")
    def test_missing_qdrant_collection_is_reported_as_unavailable(self):
        with override_settings(VECTOR_BACKEND="local"):
            doc = KnowledgeDocument.objects.create(title="Iron Guidance", content_text=DOC_TEXT)
            indexing.index_document(doc)

        client = self.FakeQdrantClient()
        with patch("kb.services.store._qdrant_client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "Qdrant knowledge index is missing"):
                store.retrieve(embeddings.embed_texts(["iron-rich foods"])[0], top_k=5)


class KBAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="kbadmin", email="k@t.com", password="Adm1n!Pass9", role="ADMIN"
        )
        cls.worker = User.objects.create_user(
            username="kbworker", email="kp@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )

    def test_admin_can_upload_text_document(self):
        token = RefreshToken.for_user(self.admin).access_token
        r = self.client.post("/api/rag/documents/", {
            "title": "Doc", "content_text": DOC_TEXT,
        }, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 201, r.content)

    def test_worker_cannot_upload(self):
        token = RefreshToken.for_user(self.worker).access_token
        r = self.client.post("/api/rag/documents/", {
            "title": "Doc", "content_text": DOC_TEXT,
        }, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 403)

    def test_retrieve_endpoint_reports_empty_kb(self):
        token = RefreshToken.for_user(self.worker).access_token
        r = self.client.post("/api/rag/retrieve/", {"question": "iron?"},
                             content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)
        data = r.json().get("data") or r.json()
        self.assertFalse(data["retrieved"])

    def test_reindex_requires_admin(self):
        token = RefreshToken.for_user(self.admin).access_token
        r = self.client.post("/api/rag/reindex/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200)
