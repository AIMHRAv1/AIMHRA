"""Chat pipeline tests: worker-driven patient sessions, emergency escalation,
safe fallback and access control."""
from accounts.models import User
from chat.models import ChatMessage, ChatSession
from django.test import TestCase, override_settings
from patients.models import PatientAssignment, PatientProfile
from rest_framework_simplejwt.tokens import RefreshToken

KB_TEXT = (
    "Morning sickness in pregnancy commonly improves with small frequent meals, "
    "ginger, and vitamin B6 as advised by a clinician. Contact a healthcare "
    "professional if vomiting is persistent."
)


class ChatPipelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.worker = User.objects.create_user(
            username="chatworker", email="c@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        cls.other_worker = User.objects.create_user(
            username="chatworker2", email="c2@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        cls.profile = PatientProfile.objects.create(
            full_name="Chat Patient", created_by=cls.worker
        )
        cls.other_profile = PatientProfile.objects.create(
            full_name="Other Worker Patient", created_by=cls.other_worker
        )
        admin = User.objects.create_user(
            username="chatadmin", email="ca@t.com", password="Adm1n!Pass9", role="ADMIN"
        )
        admin_token = RefreshToken.for_user(admin).access_token
        cls.admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {admin_token}"}

    def setUp(self):
        token = RefreshToken.for_user(self.worker).access_token
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        # Worker starts a conversation for their patient.
        r = self.client.post(
            "/api/chat/sessions/",
            {"patient": self.profile.id},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.session_id = (r.json().get("data") or r.json())["session"]["id"]

    def _send(self, message):
        r = self.client.post(
            f"/api/chat/sessions/{self.session_id}/send/",
            {"message": message},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(r.status_code, 200, r.content)
        return (r.json().get("data") or r.json())["reply"]

    def test_worker_can_create_patient_specific_session(self):
        session = ChatSession.objects.get(pk=self.session_id)
        self.assertEqual(session.patient_id, self.profile.id)
        self.assertEqual(session.created_by_id, self.worker.id)

    def test_worker_can_open_chat_for_patient_assigned_to_another_worker(self):
        PatientAssignment.objects.create(
            healthcare_worker=self.other_worker, patient=self.other_profile
        )
        token = RefreshToken.for_user(self.worker).access_token
        r = self.client.post(
            "/api/chat/sessions/",
            {"patient": self.other_profile.id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 201, r.content)
        session_id = (r.json().get("data") or r.json())["session"]["id"]
        session = ChatSession.objects.get(pk=session_id)
        self.assertEqual(session.patient_id, self.other_profile.id)
        self.assertEqual(session.created_by_id, self.worker.id)

        from unittest.mock import patch

        with patch("chat.services.rag.retrieve_context", return_value=None):
            response = self.client.post(
                f"/api/chat/sessions/{session_id}/send/",
                {"message": "What is antenatal care?"},
                content_type="application/json",
                **self.auth,
            )
        self.assertEqual(response.status_code, 200, response.content)
        reply = (response.json().get("data") or response.json())["reply"]
        self.assertIn("No guideline-based answer is available", reply["content"])
        self.assertTrue(
            ChatMessage.objects.filter(
                session_id=session_id, role=ChatMessage.ROLE_USER,
                content="What is antenatal care?",
            ).exists()
        )
        self.assertTrue(
            ChatMessage.objects.filter(
                session_id=session_id, role=ChatMessage.ROLE_ASSISTANT,
                content=reply["content"],
            ).exists()
        )

    def test_worker_cannot_open_another_workers_session(self):
        token = RefreshToken.for_user(self.other_worker).access_token
        r = self.client.get(
            f"/api/chat/sessions/{self.session_id}/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 403)

    def test_assigned_worker_can_create_and_access_a_chat_session(self):
        PatientAssignment.objects.create(
            healthcare_worker=self.worker, patient=self.other_profile
        )
        response = self.client.post(
            "/api/chat/sessions/",
            {"patient": self.other_profile.id},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        session_id = (response.json().get("data") or response.json())["session"]["id"]

        response = self.client.get(f"/api/chat/sessions/{session_id}/", **self.auth)
        self.assertEqual(response.status_code, 200, response.content)

    def test_second_worker_can_start_independent_chat_for_the_same_patient(self):
        PatientAssignment.objects.create(
            healthcare_worker=self.other_worker, patient=self.other_profile
        )
        other_auth = {
            "HTTP_AUTHORIZATION": "Bearer "
            + str(RefreshToken.for_user(self.other_worker).access_token)
        }
        response = self.client.post(
            "/api/chat/sessions/",
            {"patient": self.other_profile.id},
            content_type="application/json",
            **other_auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        session_id = (response.json().get("data") or response.json())["session"]["id"]
        session = ChatSession.objects.get(pk=session_id)
        self.assertEqual(session.patient_id, self.other_profile.id)
        self.assertEqual(session.created_by_id, self.other_worker.id)

    def test_worker_cannot_access_another_workers_session(self):
        other_auth = {
            "HTTP_AUTHORIZATION": "Bearer "
            + str(RefreshToken.for_user(self.other_worker).access_token)
        }
        response = self.client.post(
            "/api/chat/sessions/",
            {"patient": self.profile.id},
            content_type="application/json",
            **other_auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        session_id = (response.json().get("data") or response.json())["session"]["id"]

        response = self.client.get(f"/api/chat/sessions/{session_id}/", **self.auth)
        self.assertEqual(response.status_code, 403)

    def test_chat_sessions_are_private_to_their_creator(self):
        response = self.client.get("/api/chat/sessions/", **self.auth)
        sessions = (response.json().get("data") or response.json())["sessions"]
        self.assertEqual([session["id"] for session in sessions], [self.session_id])

    def test_general_question_works_without_patient_context(self):
        response = self.client.post(
            "/api/chat/sessions/",
            {"title": "General question"},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        session_id = (response.json().get("data") or response.json())["session"]["id"]
        self.assertIsNone(ChatSession.objects.get(pk=session_id).patient_id)

        from unittest.mock import patch

        with patch("chat.services.rag.retrieve_context", return_value=None):
            response = self.client.post(
                f"/api/chat/sessions/{session_id}/send/",
                {"message": "What is antenatal care?"},
                content_type="application/json",
                **self.auth,
            )
        self.assertEqual(response.status_code, 200, response.content)
        reply = (response.json().get("data") or response.json())["reply"]
        self.assertIn("No guideline-based answer is available", reply["content"])

    def test_admin_and_non_worker_roles_cannot_use_chat_api(self):
        response = self.client.get("/api/chat/sessions/")
        self.assertIn(response.status_code, (401, 403))

        response = self.client.get("/api/chat/sessions/", **self.admin_auth)
        self.assertEqual(response.status_code, 403)

        patient_user = User.objects.create_user(
            username="chatpatient", email="patient@t.com", password="test-password",
            role="PATIENT",
        )
        token = RefreshToken.for_user(patient_user).access_token
        response = self.client.get(
            "/api/chat/sessions/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_emergency_message_bypasses_llm(self):
        reply = self._send("I am having convulsions and vaginal bleeding")
        self.assertTrue(reply["escalation"]["escalate"])
        self.assertEqual(reply["generation_mode"], "escalation")
        self.assertIn("emergency", reply["content"].lower())
        from audit.models import AuditLog

        self.assertTrue(AuditLog.objects.filter(action="RULE_ESCALATION", target_type="chat_message").exists())

    def test_preeclampsia_question_is_not_misclassified_as_convulsions(self):
        from unittest.mock import patch

        with (
            patch("chat.services.rag.retrieve_context", return_value=None),
            patch("chat.services.generate_answer") as generate,
        ):
            reply = self._send("What is preeclampsia?")

        self.assertFalse(reply["escalation"]["escalate"])
        self.assertEqual(reply["generation_mode"], "no_relevant_context")
        generate.assert_not_called()

    def test_informational_convulsions_question_does_not_escalate(self):
        from unittest.mock import patch

        with (
            patch("chat.services.rag.retrieve_context", return_value=None),
            patch("chat.services.generate_answer") as generate,
        ):
            reply = self._send("What are convulsions?")

        self.assertFalse(reply["escalation"]["escalate"])
        generate.assert_not_called()

    def test_symptom_report_in_a_question_still_escalates(self):
        reply = self._send("What should I do? I am having convulsions.")

        self.assertTrue(reply["escalation"]["escalate"])
        self.assertEqual(reply["generation_mode"], "escalation")

    def test_explicit_eclampsia_report_still_escalates(self):
        reply = self._send("I have eclampsia.")

        self.assertTrue(reply["escalation"]["escalate"])
        self.assertEqual(reply["generation_mode"], "escalation")

    def test_non_emergency_message_gets_safe_answer_without_llm(self):
        # LLM_API_KEY is unset in tests -> deterministic fallback path.
        with override_settings(LLM_API_KEY=""):
            reply = self._send("What can help with morning sickness?")
        self.assertFalse(reply["escalation"].get("escalate", False))
        self.assertIn("healthcare professional", reply["content"])
        self.assertIn(
            reply["generation_mode"],
            ("no_relevant_context", "no_llm_configured", "rag_only_fallback", "llm"),
        )

    def test_llm_receives_only_approved_recommendations_for_explanation(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from django.test import override_settings

        from chat.llm import generate_answer

        client = Mock()
        client.chat.completions.create.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(
                content='[S1] “Please contact your clinic today.”'
            ))
        ]
        context_chunks = [{
            "document_title": "Clinic guidance",
            "text": "Please contact your clinic today.",
            "chunk_index": 0,
        }]
        recommendations = {
            "medical_consultation": [{
                "title": "Prompt medical consultation",
                "suggested_next_action": "Please contact your clinic or midwife today.",
                "triggering_rule_ids": ["HC-HEADACHE"],
            }]
        }
        with override_settings(LLM_API_KEY="test-key"), patch("openai.OpenAI", return_value=client):
            answer, mode = generate_answer(
                "What does this mean?",
                context_chunks=context_chunks,
                approved_recommendations=recommendations,
            )

        self.assertEqual(mode, "llm")
        self.assertEqual(answer, '[S1] “Please contact your clinic today.”')
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertIn("Do not independently create", messages[0]["content"])
        self.assertIn("must never be overridden or contradicted", messages[0]["content"])
        self.assertIn("HC-HEADACHE", messages[-1]["content"])
        self.assertIn("Please contact your clinic or midwife today.", messages[-1]["content"])

    def test_llm_prompt_allows_grounded_summaries_and_limits_sources(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from django.test import override_settings

        from chat.llm import generate_answer

        client = Mock()
        client.chat.completions.create.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(content="Check blood pressure. [S1]"))
        ]
        chunks = [{
            "document_title": "ANC guidance",
            "issuing_organization": "National Maternal Health Office",
            "section": "Hypertension",
            "page_number": 12,
            "source_url": "https://example.test/anc",
            "chunk_index": 3,
            "text": "Assess blood pressure at antenatal contacts.",
        }]
        with override_settings(LLM_API_KEY="test-key"), patch("openai.OpenAI", return_value=client):
            generate_answer("How is hypertension assessed?", context_chunks=chunks)

        messages = client.chat.completions.create.call_args.kwargs["messages"]
        prompt = "\n".join(message["content"] for message in messages)
        self.assertIn("summarize retrieved guideline excerpts", messages[0]["content"])
        self.assertIn("Cite every factual sentence", messages[0]["content"])
        self.assertIn("Do not invent or extrapolate clinical thresholds", messages[0]["content"])
        self.assertIn("[S1] ANC guidance | National Maternal Health Office", prompt)
        self.assertIn("section: Hypertension", prompt)
        self.assertIn("page: 12", prompt)
        self.assertIn("URL: https://example.test/anc", prompt)

    def test_grounded_natural_language_summary_with_valid_citation_is_accepted(self):
        from chat.llm import validate_grounded_answer

        chunks = [{
            "text": "Antenatal contacts include assessment and follow-up throughout pregnancy.",
        }]

        self.assertTrue(validate_grounded_answer(
            "Antenatal care includes regular checks and follow-up [S1].",
            chunks,
        ))

    def test_grounded_answer_rejects_uncited_or_unknown_sources(self):
        from chat.llm import validate_grounded_answer

        chunks = [{"text": "Antenatal care includes assessment and follow-up."}]

        self.assertFalse(validate_grounded_answer(
            "Antenatal care includes assessment and follow-up.", chunks
        ))
        self.assertFalse(validate_grounded_answer(
            "Antenatal care includes assessment and follow-up [S2].", chunks
        ))

    def test_grounded_answer_rejects_unsupported_numeric_thresholds(self):
        from chat.llm import validate_grounded_answer

        chunks = [{"text": "Antenatal care includes assessment and follow-up."}]

        self.assertFalse(validate_grounded_answer(
            "Antenatal care should occur at 24 weeks [S1].", chunks
        ))

    def test_grounded_answer_rejects_claims_with_unrelated_source_text(self):
        from chat.llm import validate_grounded_answer

        chunks = [{
            "text": "Antenatal contacts include assessment and follow-up throughout pregnancy.",
        }]

        self.assertFalse(validate_grounded_answer(
            "Antenatal care cures diabetes [S1].", chunks
        ))

    def test_grounded_answer_rejects_prescriptions_and_patient_diagnoses(self):
        from chat.llm import validate_grounded_answer

        chunks = [{"text": "Antenatal care includes assessment and follow-up."}]

        self.assertFalse(validate_grounded_answer(
            "Take a medication at the prescribed dose [S1].", chunks
        ))
        self.assertFalse(validate_grounded_answer(
            "You have preeclampsia [S1].", chunks
        ))

    def test_llm_is_told_when_no_guidelines_were_retrieved(self):
        from unittest.mock import patch

        from django.test import override_settings

        from chat.llm import generate_answer

        with override_settings(LLM_API_KEY="test-key"), patch("openai.OpenAI") as openai_client:
            answer, mode = generate_answer("Question without a guideline source")

        self.assertIsNone(answer)
        self.assertEqual(mode, "no_relevant_context")
        openai_client.assert_not_called()

    def test_rag_sources_attached_when_kb_has_content(self):
        self.client.post(
            "/api/rag/documents/",
            {
                "title": "Nausea Guidance",
                "issuing_organization": "National Maternal Health Office",
                "source_url": "https://example.test/nausea",
                "content_text": KB_TEXT,
            },
            content_type="application/json",
            **self.admin_auth,
        )
        with override_settings(LLM_API_KEY=""):
            reply = self._send("How do I deal with morning sickness?")
        self.assertTrue(any(s["document_title"] == "Nausea Guidance" for s in reply["sources"]))
        source = reply["sources"][0]
        self.assertEqual(source["issuing_organization"], "National Maternal Health Office")
        self.assertEqual(source["source_url"], "https://example.test/nausea")
        self.assertEqual(source["citation_id"], "S1")
        self.assertIn("[S1]", reply["content"])
        self.assertIn("Sources:", reply["content"])
        self.assertEqual(reply["knowledge_status"], "retrieved_guidelines")
        self.assertTrue(all("score" in s for s in reply["sources"]))

    def test_uncited_llm_answer_falls_back_to_cited_retrieved_excerpt(self):
        from unittest.mock import patch

        from kb.models import KnowledgeDocument
        from kb.services.indexing import index_document

        document = KnowledgeDocument.objects.create(
            title="Antenatal guidance",
            issuing_organization="National Maternal Health Office",
            source_url="https://example.test/antenatal",
            content_text="# Antenatal care\n\nAntenatal contacts include assessment and follow-up.",
        )
        index_document(document)

        with patch("chat.services.generate_answer", return_value=("An uncited claim.", "llm")):
            reply = self._send("What happens during antenatal care?")

        self.assertEqual(reply["generation_mode"], "rag_only_fallback")
        self.assertNotIn("An uncited claim.", reply["content"])
        self.assertIn("[S1]", reply["content"])
        self.assertIn("Antenatal contacts include assessment and follow-up.", reply["content"])
        self.assertTrue(reply["sources"])

    def test_grounded_natural_language_answer_is_returned_with_source_label(self):
        from unittest.mock import patch

        chunks = [{
            "document_id": 41,
            "document_title": "Antenatal guidance",
            "issuing_organization": "World Health Organization",
            "section": "Antenatal care",
            "page_number": 12,
            "source_url": "https://example.test/anc",
            "chunk_id": 71,
            "chunk_index": 0,
            "text": "Antenatal contacts include assessment and follow-up throughout pregnancy.",
            "score": 0.9,
        }]
        generated = (
            "Antenatal care involves regular assessment and follow-up throughout pregnancy [S1].",
            "llm",
        )
        with (
            patch("chat.services.rag.retrieve_context", return_value={"chunks": chunks}),
            patch("chat.services.generate_answer", return_value=generated),
        ):
            reply = self._send("What does antenatal care involve?")

        self.assertEqual(reply["generation_mode"], "llm")
        self.assertIn("Guideline-based explanation (from retrieved sources)", reply["content"])
        self.assertIn(generated[0], reply["content"])
        self.assertEqual(reply["sources"][0]["citation_id"], "S1")

    def test_llm_fabricated_claim_with_valid_marker_is_rejected(self):
        from unittest.mock import patch

        chunks = [{
            "document_id": 41,
            "document_title": "Antenatal guidance",
            "issuing_organization": "Source organization",
            "section": "Care",
            "page_number": 2,
            "source_url": "https://example.test/anc",
            "chunk_id": 71,
            "chunk_index": 0,
            "text": "Antenatal care includes assessment and follow-up.",
            "score": 0.9,
        }]
        with (
            patch("chat.services.rag.retrieve_context", return_value={"chunks": chunks}),
            patch(
                "chat.services.generate_answer",
                return_value=("Take a medication at a specific dose. [S1]", "llm"),
            ),
        ):
            reply = self._send("What does antenatal care include?")

        self.assertEqual(reply["generation_mode"], "rag_only_fallback")
        self.assertNotIn("specific dose", reply["content"])
        self.assertIn("Antenatal care includes assessment and follow-up.", reply["content"])
        self.assertIn("[S1]", reply["content"])

    def test_irrelevant_question_does_not_call_llm_or_invent_answer(self):
        from unittest.mock import patch

        with (
            patch("chat.services.rag.retrieve_context", return_value=None),
            patch("chat.services.generate_answer") as generate,
        ):
            reply = self._send("Write a poem about the moon.")

        generate.assert_not_called()
        self.assertEqual(reply["generation_mode"], "no_relevant_context")
        self.assertEqual(reply["sources"], [])
        self.assertIn("no relevant guideline information was retrieved", reply["content"])
        self.assertNotIn("general educational information", reply["content"])

    def test_approved_assessment_recommendations_remain_visible_without_rag(self):
        from datetime import date
        from unittest.mock import patch

        from assessments.models import Assessment

        Assessment.objects.create(
            patient=self.profile,
            visit_date=date.today(),
            age=28,
            body_temperature=98.6,
            heart_rate=80,
            systolic_bp=110,
            diastolic_bp=70,
            bmi=24,
            hba1c=38,
            fasting_glucose=5.1,
            recommendations={
                "routine_monitoring": [{
                    "title": "Routine clinical follow-up",
                    "suggested_next_action": "Mention this finding at the next contact.",
                }]
            },
        )
        with (
            patch("chat.services.rag.retrieve_context", return_value=None),
            patch("chat.services.generate_answer") as generate,
        ):
            reply = self._send("Can you explain my visit?")

        generate.assert_not_called()
        self.assertIn("No guideline-based answer is available", reply["content"])
        self.assertIn("Approved assessment recommendations (unchanged", reply["content"])
        self.assertIn("Mention this finding at the next contact.", reply["content"])

    def test_conflicting_sources_are_quoted_separately_and_not_reconciled(self):
        from unittest.mock import patch

        chunks = [
            {
                "document_id": 41, "document_title": "Guideline A",
                "issuing_organization": "Organization A", "section": "Visits",
                "page_number": 2, "source_url": "https://example.test/a",
                "chunk_id": 71, "chunk_index": 0,
                "text": "Source A says visits should be more frequent.",
                "score": 0.9,
            },
            {
                "document_id": 42, "document_title": "Guideline B",
                "issuing_organization": "Organization B", "section": "Visits",
                "page_number": 4, "source_url": "https://example.test/b",
                "chunk_id": 72, "chunk_index": 0,
                "text": "Source B says visits should be less frequent.",
                "score": 0.8,
            },
        ]
        generated = (
            '[S1] “Source A says visits should be more frequent.”\n'
            '[S2] “Source B says visits should be less frequent.”',
            "llm",
        )
        with (
            patch("chat.services.rag.retrieve_context", return_value={"chunks": chunks}),
            patch("chat.services.generate_answer", return_value=generated),
        ):
            reply = self._send("How often should visits happen?")

        self.assertIn("Source A says visits should be more frequent.", reply["content"])
        self.assertIn("Source B says visits should be less frequent.", reply["content"])
        self.assertIn("have not been reconciled", reply["content"])
        self.assertIn("does not choose between them", reply["content"])
        self.assertEqual([source["citation_id"] for source in reply["sources"]], ["S1", "S2"])

    def test_llm_api_failure_returns_retrieved_quotes_with_sources(self):
        from unittest.mock import patch

        chunks = [{
            "document_id": 41, "document_title": "Antenatal guidance",
            "issuing_organization": "", "section": "", "page_number": None,
            "source_url": "", "chunk_id": 71, "chunk_index": 0,
            "text": "Antenatal care includes assessment and follow-up.",
            "score": 0.9,
        }]
        with (
            patch("chat.services.rag.retrieve_context", return_value={"chunks": chunks}),
            patch("chat.services.generate_answer", return_value=(None, "no_llm_configured")),
        ):
            reply = self._send("What does antenatal care include?")

        self.assertEqual(reply["generation_mode"], "rag_only_fallback")
        self.assertTrue(reply["sources"])
        self.assertIn("Antenatal care includes assessment and follow-up.", reply["content"])
        self.assertIn("[S1]", reply["content"])

    def test_no_fabricated_sources_when_kb_empty(self):
        from kb.models import KnowledgeDocument

        KnowledgeDocument.objects.all().delete()
        reply = self._send("Tell me about pregnancy nutrition")
        self.assertEqual(reply["sources"], [])
        self.assertEqual(reply["knowledge_status"], "no_relevant_guidelines_retrieved")
        self.assertIn("No guideline-based answer is available", reply["content"])

    def test_emergency_escalation_bypasses_rag_and_llm(self):
        from unittest.mock import patch

        with (
            patch("chat.services.rag.retrieve_context") as retrieve,
            patch("chat.services.generate_answer") as generate,
        ):
            reply = self._send("I am having convulsions")

        self.assertTrue(reply["escalation"]["escalate"])
        retrieve.assert_not_called()
        generate.assert_not_called()

    def test_message_persisted_with_history(self):
        self._send("Hello there")
        self.assertTrue(ChatMessage.objects.filter(session_id=self.session_id, role="USER").exists())
        self.assertTrue(ChatMessage.objects.filter(session_id=self.session_id, role="ASSISTANT").exists())

    def test_empty_message_rejected(self):
        r = self.client.post(
            f"/api/chat/sessions/{self.session_id}/send/",
            {"message": "  "},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(r.status_code, 400)

    def test_session_title_from_first_message(self):
        self._send("Question about iron supplements during pregnancy")
        session = ChatSession.objects.get(pk=self.session_id)
        self.assertIn("iron", session.title.lower())

    def test_worker_can_delete_own_session(self):
        r = self.client.delete(
            f"/api/chat/sessions/{self.session_id}/",
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ChatSession.objects.filter(pk=self.session_id).exists())

    def test_worker_cannot_delete_others_session(self):
        token = RefreshToken.for_user(self.other_worker).access_token
        r = self.client.delete(
            f"/api/chat/sessions/{self.session_id}/",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 403)
        self.assertTrue(ChatSession.objects.filter(pk=self.session_id).exists())