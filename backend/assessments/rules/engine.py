"""Deterministic, versioned emergency rule engine.

Properties required by the project:
 - Explicit: every rule is a row in rules.json, inspectable by clinicians.
 - Versioned: the ruleset version is stamped on every outcome/alert.
 - Testable: pure function of (vitals, symptoms) — no I/O, no randomness.
 - Explainable: each trigger returns its rule id and description.

Priority order (SAFETY.md): Emergency rules outrank the ML model, RAG and
the LLM. Nothing downstream may soften or hide an emergency outcome.
"""
import json
from pathlib import Path

RULES_FILE = Path(__file__).with_name("rules.json")

CATEGORY_RANK = {"NORMAL": 0, "ATTENTION": 1, "HIGH_CONCERN": 2, "EMERGENCY": 3}

_OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}

_cache = {"mtime": None, "rules": None}


def load_rules(force=False):
    mtime = RULES_FILE.stat().st_mtime
    if force or _cache["rules"] is None or _cache["mtime"] != mtime:
        _cache["rules"] = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        _cache["mtime"] = mtime
    return _cache["rules"]


def _matches(rule, vitals, symptoms):
    if rule["type"] == "symptom":
        return rule["match"] in symptoms
    if rule["type"] == "vital":
        value = vitals.get(rule["feature"])
        if value is None:
            return False
        return _OPS[rule["op"]](float(value), float(rule["value"]))
    return False


def evaluate(vitals, symptoms, force_reload=False):
    """Evaluate all rules; return the highest-priority outcome.

    vitals: dict of feature -> numeric value (may be partial)
    symptoms: list of vocabulary tokens (unknown tokens are ignored)
    """
    ruleset = load_rules(force=force_reload)
    vocabulary = set(ruleset.get("symptom_vocabulary", []))
    clean_symptoms = [s for s in (symptoms or []) if s in vocabulary]

    triggered = []
    for rule in ruleset["rules"]:
        if _matches(rule, vitals, clean_symptoms):
            triggered.append(rule)

    worst = max((r["category"] for r in triggered), key=lambda c: CATEGORY_RANK.get(c, 0), default="NORMAL")
    # Only keep triggers at the worst category (the escalation level), plus
    # lower ones for context; the response always surfaces the worst first.
    ordered = sorted(triggered, key=lambda r: -CATEGORY_RANK.get(r["category"], 0))
    message = ruleset["messages"].get(worst, ruleset["messages"]["NORMAL"])

    return {
        "category": worst,
        "escalate": worst in ("EMERGENCY", "HIGH_CONCERN"),
        "rules_version": ruleset["version"],
        "message": message,
        "triggered": [
            {"id": r["id"], "category": r["category"], "description": r["description"]} for r in ordered
        ],
    }
