"""Deterministic symptom-keyword detection for free-text chat messages.

Part of the rule engine (v1): maps phrases to the fixed symptom vocabulary so
the emergency rule engine can evaluate chat input the same way it evaluates
assessments. Purely lexical — no LLM involvement.
"""

import re


KEYWORD_MAP = {
    "convulsions": [
        "convulsion", "convulsions", "seizure", "seizures", "fit", "fits", "eclampsia"
    ],
    "vaginal_bleeding": ["vaginal bleeding", "bleeding", "blood loss", "hemorrhage", "haemorrhage"],
    "difficulty_breathing": ["difficulty breathing", "can't breathe", "cant breathe", "shortness of breath", "breathless", "struggling to breathe"],
    "severe_headache": ["severe headache", "bad headache", "worst headache", "terrible headache", "migraine"],
    "blurred_vision": ["blurred vision", "blurry vision", "vision problem", "can't see", "double vision", "flashing lights"],
    "severe_abdominal_pain": ["severe abdominal pain", "severe stomach pain", "bad stomach pain", "intense abdominal pain"],
    "decreased_fetal_movement": ["baby not moving", "decreased fetal movement", "less fetal movement", "baby isn't moving", "reduced movement"],
    "swelling_face_hands": ["swelling in my face", "swollen face", "swollen hands", "swelling of face", "puffy face"],
    "persistent_vomiting": ["persistent vomiting", "can't stop vomiting", "cant stop vomiting", "constant vomiting", "throwing up everything"],
    "dizziness_fainting": ["dizzy", "dizziness", "faint", "fainted", "passing out", "lightheaded"],
    "fever": ["fever", "feverish", "high temperature", "burning up"],
}

_INFORMATIONAL_QUESTION_RE = re.compile(
    r"^\s*(?:what|who|when|where|why|how|can you explain|could you explain|"
    r"tell me about|define|meaning of)\b",
    re.IGNORECASE,
)
_REPORTED_SYMPTOM_RE = re.compile(
    r"\b(?:i|we|my|our|she|he|they|the patient)\b.{0,60}\b"
    r"(?:have|has|had|am|is|are|was|were|experienc\w*|suffer\w*|"
    r"report\w*|notice\w*)\b|\b(?:i'm|we're|she's|he's|they're)\s+"
    r"(?:currently\s+)?(?:having|experiencing|suffering)\b",
    re.IGNORECASE,
)


def detect_symptoms(text):
    """Return symptom vocabulary tokens reported in a message.

    Informational questions alone are not symptom reports. Explicit reports in
    a question (for example, "What should I do? I am bleeding") still trigger.
    """
    message = text or ""
    lowered = message.lower()
    found = set()
    for symptom, phrases in KEYWORD_MAP.items():
        if any(
            re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lowered)
            for phrase in phrases
        ):
            found.add(symptom)
    if (
        found
        and _INFORMATIONAL_QUESTION_RE.search(message)
        and not _REPORTED_SYMPTOM_RE.search(message)
    ):
        return []
    return sorted(found)
