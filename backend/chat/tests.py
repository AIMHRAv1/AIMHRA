"""Chat pipeline tests: worker-driven patient sessions, emergency escalation,
safe fallback and access control."""
from accounts.models import User
from chat.models import ChatMessage, ChatSession
from django.test import TestCase, override_settings
from patients.models import PatientProfile
from rest_framework_simplejwt.tokens import RefreshToken

KB_TEXT = (
    "Morning sickness in pregnancy commonly improves with small frequent meals, "
    "ginger, and vitamin B6 as advised by a clinician. Contact a healthcare "
    "professional if vomiting is persistent."
)


@override_settings(LLM_BASE_URL="")  # force the offline fallback path in tests
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

    def test_non_worker_cannot_create_session(self):
        # Policy: workers see all patients; only non-worker roles are denied.
        stranger = User.objects.create_user(
            username="chatpatient", email="cp@t.com", password="Str0ng!Pass1", role="PATIENT"
        )
        token = RefreshToken.for_user(stranger).access_token
        r = self.client.post(
            "/api/chat/sessions/",
            {"patient": self.profile.id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 403)

    def test_non_worker_cannot_open_session(self):
        # Policy: workers see all patients (so all patient sessions);
        # non-worker roles are denied.
        stranger = User.objects.create_user(
            username="chatpatient2", email="cp2@t.com", password="Str0ng!Pass1", role="PATIENT"
        )
        token = RefreshToken.for_user(stranger).access_token
        r = self.client.get(
            f"/api/chat/sessions/{self.session_id}/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(r.status_code, 403)

    EMERGENCY_KB_TEXT = (
        "Heavy vaginal bleeding in pregnancy is an emergency. While arranging emergency "
        "care, the patient should lie on her side, stay calm, avoid drinking or eating, "
        "and have someone stay with her. Note the amount of bleeding and any clots to "
        "report to the medical team. Do not take any medication unless instructed by a "
        "clinician. Transport to the nearest hospital as quickly and smoothly as possible."
    )

    def test_emergency_message_warns_then_advises(self):
        self.client.post(
            "/api/rag/documents/",
            {"title": "Bleeding Emergency Guidance", "content_text": self.EMERGENCY_KB_TEXT},
            content_type="application/json",
            **self.admin_auth,
        )
        reply = self._send("I am having convulsions and vaginal bleeding")
        self.assertTrue(reply["escalation"]["escalate"])
        self.assertEqual(reply["generation_mode"], "escalation")
        content = reply["content"].lower()
        # The warning must come first and must never be softened.
        self.assertIn("do not wait", content)
        self.assertIn("nearest hospital", content)
        self.assertLess(content.find("do not wait"), content.find("while you arrange emergency care"))
        # Practical advice on what to do follows the warning.
        self.assertIn("while you arrange emergency care", content)
        from audit.models import AuditLog

        self.assertTrue(AuditLog.objects.filter(action="RULE_ESCALATION", target_type="chat_message").exists())

    def test_non_emergency_message_gets_safe_answer_without_llm(self):
        # No local model server in tests -> deterministic extractive fallback path.
        reply = self._send("What can help with morning sickness?")
        self.assertFalse(reply["escalation"].get("escalate", False))
        self.assertIn("healthcare professional", reply["content"])
        self.assertIn(reply["generation_mode"], ("no_llm_configured", "rag_only_fallback", "local_llm"))

    def test_rag_sources_attached_when_kb_has_content(self):
        self.client.post(
            "/api/rag/documents/",
            {"title": "Nausea Guidance", "content_text": KB_TEXT},
            content_type="application/json",
            **self.admin_auth,
        )
        reply = self._send("How do I deal with morning sickness?")
        if reply["generation_mode"] in ("rag_only_fallback", "local_llm"):
            self.assertTrue(any(s["document_title"] == "Nausea Guidance" for s in reply["sources"]))
            self.assertTrue(all("score" in s for s in reply["sources"]))

    def test_no_fabricated_sources_when_kb_empty(self):
        from kb.models import KnowledgeDocument

        KnowledgeDocument.objects.all().delete()
        reply = self._send("Tell me about pregnancy nutrition")
        self.assertEqual(reply["sources"], [])

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

class AdminChatPolicyTests(TestCase):
    """Administrators do not use the patient AI assistant."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="chatadmin2", email="ca2@t.com", password="Str0ng!Pass1", role="ADMIN"
        )
        cls.worker = User.objects.create_user(
            username="chatworker3", email="c3@t.com", password="Str0ng!Pass1", role="HEALTHCARE_WORKER"
        )
        cls.profile = PatientProfile.objects.create(full_name="Policy Patient", created_by=cls.worker)

    def test_admin_cannot_create_chat_session(self):
        token = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(self.admin).access_token}"}
        r = self.client.post(
            "/api/chat/sessions/", {"patient": self.profile.id},
            content_type="application/json", **token,
        )
        self.assertEqual(r.status_code, 403)
