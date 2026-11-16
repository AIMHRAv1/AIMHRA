"""Temporary reproduction: multipart upload exactly like the admin Knowledge page."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken

KB_TEXT = ("Iron deficiency in pregnancy is common. Iron-rich foods include "
           "lentils, lean red meat, spinach and fortified cereals. Vitamin C "
           "improves iron absorption. Warning: severe fatigue, pallor or "
           "breathlessness should be assessed by a healthcare professional.")


class MultiPartUploadReproTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import User

        cls.admin = User.objects.create_user(
            username="mpadmin", email="mp@x.com", password="x", role="ADMIN"
        )

    def test_upload_file_multipart(self):
        file = SimpleUploadedFile(
            "guideline.txt", b"Guideline text for upload.\n" * 200
        )
        data = {
            "title": "Repro Guideline",
            "source_url": "https://example.test/guideline",
            "file": file,
        }
        token = RefreshToken.for_user(self.admin).access_token
        resp = self.client.post(
            "/api/rag/documents/",
            data,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        print("--- MULTIPART FILE UPLOAD STATUS:", resp.status_code)
        print(resp.content.decode()[:2000])

    def test_upload_text_content_text_multipart(self):
        data = {
            "title": "Repro Text",
            "content_text": KB_TEXT,
        }
        token = RefreshToken.for_user(self.admin).access_token
        resp = self.client.post(
            "/api/rag/documents/",
            data,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        print("--- MULTIPART TEXT UPLOAD STATUS:", resp.status_code)
        print(resp.content.decode()[:2000])
