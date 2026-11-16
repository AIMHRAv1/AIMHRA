"""Deterministic symptom-keyword extraction for free-text callers.

The chat assistant deliberately does not invoke this mapping; assessment rules
use symptoms explicitly recorded with the assessment.
"""

KEYWORD_MAP = {
    "convulsions": ["convulsion", "seizure", "fit", "fits"],
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


def detect_symptoms(text):
    """Return sorted list of vocabulary symptoms mentioned in the text."""
    lowered = (text or "").lower()
    found = set()
    for symptom, phrases in KEYWORD_MAP.items():
        if any(p in lowered for p in phrases):
            found.add(symptom)
    return sorted(found)
