"""Deterministic, versioned MEASUREMENT-TREND rule engine.

Separate from the point-of-assessment emergency engine (rules/engine.py):
this module evaluates CHANGES between stored visits (deltas computed by
assessments.trends.compare_measurements). Properties mirror the main engine:

 - Explicit: every rule is a row in trend_rules.json, inspectable.
 - Versioned + review-gated: the ruleset carries review_status; while it is
   not 'CLINICALLY_REVIEWED' the engine returns a neutral "disabled" result
   and NO alert can ever be produced. Threshold fields ship empty.
 - Deterministic: pure function of (comparisons) — no I/O beyond the JSON
   load, no randomness.
 - Not ML: arithmetic threshold checks on stored measurements only.
"""
import json
from pathlib import Path

TREND_RULES_FILE = Path(__file__).with_name("trend_rules.json")

CATEGORY_RANK = {"NORMAL": 0, "ATTENTION": 1, "HIGH_CONCERN": 2}

_OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}

_cache = {"mtime": None, "ruleset": None}


def load_trend_rules(force=False):
    mtime = TREND_RULES_FILE.stat().st_mtime
    if force or _cache["ruleset"] is None or _cache["mtime"] != mtime:
        _cache["ruleset"] = json.loads(TREND_RULES_FILE.read_text(encoding="utf-8"))
        _cache["mtime"] = mtime
    return _cache["ruleset"]


def trend_rules_active():
    """True only when a clinically reviewed ruleset with at least one rule
    exists. Until then, trend evaluation can never fire an alert."""
    ruleset = load_trend_rules()
    return (
        ruleset.get("review_status") == "CLINICALLY_REVIEWED"
        and bool(ruleset.get("rules"))
    )


def _match(rule, comparison):
    if comparison["feature"] != rule.get("feature"):
        return False
    direction = rule.get("direction")
    if direction and comparison.get("direction") != direction:
        return False
    for field, key in (("delta", "delta"), ("percent_delta", "percent_change")):
        if field in rule:
            threshold = rule.get(field)
            if threshold is None:
                return False  # unfilled threshold during review: never fires
            value = comparison.get(key)
            if value is None:
                return False
            if not _OPS[rule.get("op", ">=")](float(value), float(threshold)):
                return False
    return True


def evaluate_trends(comparisons, force_reload=False):
    """Evaluate measurement-change rules against previous-vs-latest
    comparisons. Returns the same shape as the main rule engine, plus
    `active` (False = rules not clinically reviewed). While inactive, the
    outcome is always NORMAL with no triggered rules."""
    ruleset = load_trend_rules(force=force_reload)
    active = trend_rules_active()
    if not active:
        return {
            "active": False,
            "category": "NORMAL",
            "escalate": False,
            "rules_version": ruleset.get("version", "trend-unreviewed"),
            "message": "Measurement-change rules are configured but not yet clinically reviewed; trend monitoring alerts are disabled.",
            "triggered": [],
        }

    triggered = []
    for rule in ruleset["rules"]:
        for comparison in comparisons or []:
            if _match(rule, comparison):
                triggered.append({
                    "id": rule["id"],
                    "category": rule["category"],
                    "description": rule["description"],
                    "feature": comparison["feature"],
                    "delta": comparison["delta"],
                    "percent_change": comparison["percent_change"],
                })

    worst = max((t["category"] for t in triggered), key=lambda c: CATEGORY_RANK.get(c, 0), default="NORMAL")
    ordered = sorted(triggered, key=lambda t: -CATEGORY_RANK.get(t["category"], 0))
    messages = ruleset.get("messages", {})
    return {
        "active": True,
        "category": worst,
        "escalate": worst in ("HIGH_CONCERN",),
        "rules_version": ruleset["version"],
        "message": messages.get(worst) or messages.get("NORMAL") or "",
        "triggered": ordered,
    }
