"""End-to-end smoke test of the full workflow through Django's test client:
register -> login -> profile -> assessment -> prediction + SHAP + rules ->
history/trend -> chat escalation -> chat fallback -> KB ingest + retrieve -> report PDF.
Run: python scripts/smoke_test.py (from backend/)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

# Clean slate: remove users created by previous smoke runs.
from accounts.models import User

User.objects.filter(username__in=["smoke_patient", "smoke_admin"]).delete()

from django.test import Client

c = Client()
FAILURES = []


def J(r):
    d = r.json()
    return d.get("data", d)


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# --- register & login ---
r = c.post("/api/auth/register/", {
    "username": "smoke_patient", "email": "smoke@example.com",
    "full_name": "Smoke Patient", "phone": "+1000000000",
    "password": "Sm0ke!Test42", "confirm_password": "Sm0ke!Test42",
}, content_type="application/json")
check("register returns 201", r.status_code == 201, r.content[:200])
token = J(r)["tokens"]["access"]
auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

r = c.post("/api/auth/login/", {"username": "smoke_patient", "password": "Sm0ke!Test42"},
           content_type="application/json")
check("login returns 200 with user role", r.status_code == 200 and J(r)["user"]["role"] == "PATIENT",
      r.content[:200])

# --- profile ---
r = c.get("/api/patients/me/", **auth)
check("patient profile auto-created", r.status_code == 200 and J(r)["patient_code"].startswith("P-"))

# --- assessment with emergency vitals ---
payload = {
    "visit_date": "2026-08-19", "gestational_week": 24,
    "age": 29, "body_temperature": 98.6, "heart_rate": 88,
    "systolic_bp": 165, "diastolic_bp": 105, "bmi": 24.1,
    "hba1c": 38, "fasting_glucose": 5.5,
    "symptoms": ["severe_headache"], "notes": "smoke test",
}
r = c.post("/api/assessments/", payload, content_type="application/json", **auth)
body = r.json()
check("assessment returns 201", r.status_code == 201, r.content[:300])
data = body.get("data") or body
check("risk level valid", data.get("risk_level") in ("low risk", "mid risk", "high risk"), str(data.get("risk_level")))
check("probability present", 0 <= data.get("probability", -1) <= 1)
check("model version recorded", bool(data.get("model", {}).get("version")))
check("SHAP explanation present", len(data.get("explanation", {}).get("features", [])) > 0)
check("rule engine escalated to EMERGENCY", data.get("rules", {}).get("category") == "EMERGENCY",
      str(data.get("rules", {}).get("category")))
check("alert created", len(data.get("alerts", [])) == 1)
check("disclaimer present", "not a medical diagnosis" in data.get("disclaimer", ""))
assessment_id = data.get("assessment", {}).get("id")

# --- validation rejection ---
bad = dict(payload, systolic_bp=300)
r = c.post("/api/assessments/", bad, content_type="application/json", **auth)
check("out-of-range input rejected 400", r.status_code == 400 and not r.json().get("success"))

# --- second assessment (normal) + history/trend ---
normal = dict(payload, systolic_bp=118, diastolic_bp=76, symptoms=["none"])
r = c.post("/api/assessments/", normal, content_type="application/json", **auth)
check("second assessment created", r.status_code == 201)

r = c.get("/api/assessments/risk-history/", **auth)
check("risk history has 2 entries", r.status_code == 200 and len(r.json()["data"]["history"]) == 2)

r = c.get("/api/assessments/risk-trends/", **auth)
check("trend computed", r.status_code == 200 and r.json()["data"]["trend"]["visits"] == 2)

# --- chat: emergency path (LLM must be bypassed) ---
r = c.post("/api/chat/sessions/", {"title": "smoke"}, content_type="application/json", **auth)
session_id = J(r)["session"]["id"]
check("chat session created", r.status_code == 201)

r = c.post(f"/api/chat/sessions/{session_id}/send/", {"message": "I have severe vaginal bleeding and feel faint"},
           content_type="application/json", **auth)
reply = J(r)["reply"]
check("chat emergency escalation", reply["escalation"].get("escalate") is True, json.dumps(reply)[:200])
check("chat escalation mode set", reply["generation_mode"] == "escalation")

r = c.post(f"/api/chat/sessions/{session_id}/send/", {"message": "What foods help with morning sickness?"},
           content_type="application/json", **auth)
reply2 = J(r)["reply"]
check("chat normal path answers safely", r.status_code == 200 and "healthcare professional" in reply2["content"] + reply2.get("disclaimer", ""))

# --- knowledge base: admin upload + retrieval ---
from accounts.models import User

admin = User.objects.create_superuser(username="smoke_admin", email="admin@example.com", password="Adm1n!Test42", role="ADMIN")
r = c.post("/api/auth/login/", {"username": "smoke_admin", "password": "Adm1n!Test42"}, content_type="application/json")
admin_token = J(r)["access"]
admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {admin_token}"}

r = c.post("/api/rag/documents/", {
    "title": "Smoke Test Guidance",
    "content_text": (
        "Iron-deficiency anemia in pregnancy. Pregnant patients are commonly advised to eat "
        "iron-rich foods such as lentils, lean meat and leafy greens. Vitamin C helps iron "
        "absorption. Severe fatigue or breathlessness should be assessed by a clinician."
    ),
}, content_type="application/json", **admin_auth)
check("kb document indexed", r.status_code == 201 and J(r)["chunk_count"] >= 1, r.content[:300])

r = c.post("/api/rag/retrieve/", {"question": "What foods contain iron for pregnancy?"},
           content_type="application/json", **auth)
retrieved = J(r)
check("rag retrieval finds source", retrieved.get("retrieved") and len(retrieved.get("chunks", [])) > 0
      and retrieved["chunks"][0]["document_title"] == "Smoke Test Guidance")

# --- report PDF ---
r = c.post("/api/reports/", {"assessment": assessment_id}, content_type="application/json", **auth)
check("report generated", r.status_code == 201 and J(r)["report"]["id"], r.content[:300])
report_id = J(r)["report"]["id"]
r = c.get(f"/api/reports/{report_id}/download/", **auth)
pdf_bytes = b"".join(r.streaming_content) if hasattr(r, "streaming_content") else r.content
check("report PDF downloads", r.status_code == 200 and r["Content-Type"] == "application/pdf" and len(pdf_bytes) > 1000)

# --- models API ---
r = c.get("/api/models/compare/", **auth)
compare = J(r)
check("model comparison lists both", {m["model"] for m in compare["models"]} == {"RandomForest", "XGBoost"})
check("production is XGBoost", compare["production"] and compare["production"]["model"] == "XGBoost")

# --- audit log (admin only) ---
r = c.get("/api/audit/", **admin_auth)
check("audit log records events", r.status_code == 200 and J(r)["count"] >= 5)

r = c.get("/api/audit/", **auth)
check("audit log forbidden for patient", r.status_code == 403)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL SMOKE CHECKS PASSED")
