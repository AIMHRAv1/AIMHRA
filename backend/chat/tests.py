"""Chat pipeline tests: emergency escalation, safe fallback, access control."""
from accounts.models import User
from chat.models import ChatMessage, ChatSession
from django.test import TestCase
from patients.models import PatientProfile
from rest_framework_simplejwt.tokens import RefreshToken

KB_TEXT = (
    "Morning sickness in pregnancy commonly improves with small frequent meals, "
    "ginger, and vitamin B6 as advised by a clinician. Contact a healthcare "
    "professional if vomiting is persistent."
)


class ChatPipelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="chatpat", email="c@t.com", password="Str0ng!Pass1", role="PATIENT"
        )
        cls.profile = PatientProfile.objects.create(user=cls.user)
        admin = User.objects.create_user(
            username="chatadmin", email="ca@t.com", password="Adm1n!Pass9", role="ADMIN"
        )
        admin_token = RefreshToken.for_user(admin).access_token
        cls.admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {admin_token}"}

    def setUp(self):
        token = RefreshToken.for_user(self.user).access_token
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        # No title -> defaults to "New conversation" -> replaced by first message.
        r = self.client.post("/api/chat/sessions/", {}, content_type="application/json", **self.auth)
        self.session_id = (r.json().get("data") or r.json())["session"]["id"]

    def _send(self, message):
        r = self.client.post(f"/api/chat/sessions/{self.session_id}/send/",
                             {"message": message}, content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 200, r.content)
        return (r.json().get("data") or r.json())["reply"]

    def test_emergency_message_bypasses_llm(self):
        reply = self._send("I am having convulsions and vaginal bleeding")
        self.assertTrue(reply["escalation"]["escalate"])
        self.assertEqual(reply["generation_mode"], "escalation")
        self.assertIn("emergency", reply["content"].lower())
        from audit.models import AuditLog

        self.assertTrue(AuditLog.objects.filter(action="RULE_ESCALATION", target_type="chat_message").exists())

    def test_non_emergency_message_gets_safe_answer_without_llm(self):
        # LLM_API_KEY is unset in tests -> deterministic fallback path.
        reply = self._send("What can help with morning sickness?")
        self.assertFalse(reply["escalation"].get("escalate", False))
        self.assertIn("healthcare professional", reply["content"])
        self.assertIn(reply["generation_mode"], ("no_llm_configured", "rag_only_fallback", "llm"))

    def test_rag_sources_attached_when_kb_has_content(self):
        self.client.post("/api/rag/documents/", {
            "title": "Nausea Guidance", "content_text": KB_TEXT,
        }, content_type="application/json", **self.admin_auth)
        reply = self._send("How do I deal with morning sickness?")
        if reply["generation_mode"] in ("rag_only_fallback", "llm"):
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
        r = self.client.post(f"/api/chat/sessions/{self.session_id}/send/",
                             {"message": "  "}, content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 400)

    def test_session_isolation(self):
        other = User.objects.create_user(username="chatpat2", email="c2@t.com", password="Str0ng!Pass1")
        other_token = RefreshToken.for_user(other).access_token
        r = self.client.get(f"/api/chat/sessions/{self.session_id}/",
                            HTTP_AUTHORIZATION=f"Bearer {other_token}")
        self.assertEqual(r.status_code, 403)

    def test_session_title_from_first_message(self):
        self._send("Question about iron supplements during pregnancy")
        session = ChatSession.objects.get(pk=self.session_id)
        self.assertIn("iron", session.title.lower())
