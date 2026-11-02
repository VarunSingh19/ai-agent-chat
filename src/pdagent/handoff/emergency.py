"""Deterministic pre-LLM emergency matcher (Architecture.md §7d, Rules.md §1 Rule 6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class EmergencyMatch:
    """Result of evaluating a user message against `config/emergency_rules.yaml`."""

    matched: bool
    rule_id: str | None = None
    category: str | None = None
    safety_reply: str = ""


@dataclass(frozen=True, slots=True)
class EmergencyRule:
    """A single phrase-based emergency rule."""

    rule_id: str
    category: str
    phrases: tuple[str, ...]


class EmergencyRuleCatalog:
    """Loaded emergency rules and safety reply template (`config/emergency_rules.yaml`)."""

    def __init__(self, raw: dict[str, object]) -> None:
        self.version = str(raw.get("version", "1"))
        self.safety_reply_template = str(
            raw.get(
                "safety_reply_template",
                "CRITICAL SAFETY NOTICE: If you are in immediate danger, call 911 immediately "
                "and contact property emergency dispatch at {emergency_phone}.",
            )
        )
        rules_list: list[EmergencyRule] = []
        raw_rules = raw.get("rules", [])
        if isinstance(raw_rules, list):
            for item in raw_rules:
                if isinstance(item, dict):
                    phrases_raw = item.get("phrases", [])
                    phrases = (
                        tuple(_normalize_text(str(p)) for p in phrases_raw)
                        if isinstance(phrases_raw, list)
                        else ()
                    )
                    rules_list.append(
                        EmergencyRule(
                            rule_id=str(item.get("id", "emg-unknown")),
                            category=str(item.get("category", "emergency")),
                            phrases=phrases,
                        )
                    )
        self.rules = tuple(rules_list)


_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    stripped = _NON_ALNUM_RE.sub(" ", lowered)
    return " ".join(stripped.split())


@lru_cache(maxsize=1)
def load_emergency_catalog(
    config_path: str = "config/emergency_rules.yaml",
) -> EmergencyRuleCatalog:
    """Load and parse `config/emergency_rules.yaml`."""
    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).resolve().parents[3] / "config" / "emergency_rules.yaml"
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        msg = "config/emergency_rules.yaml must contain a top-level mapping"
        raise ValueError(msg)
    return EmergencyRuleCatalog(data)


def check_emergency_message(
    user_message: str,
    *,
    emergency_phone: str = "1-800-555-0199",
    catalog: EmergencyRuleCatalog | None = None,
) -> EmergencyMatch:
    """Evaluate `user_message` deterministically before any LLM or
    Redis call (Rules.md §1 Rule 6)."""
    cat = catalog or load_emergency_catalog()
    normalized = _normalize_text(user_message)
    if not normalized:
        return EmergencyMatch(matched=False)

    for rule in cat.rules:
        for phrase in rule.phrases:
            if phrase and phrase in normalized:
                reply = cat.safety_reply_template.format(emergency_phone=emergency_phone)
                return EmergencyMatch(
                    matched=True,
                    rule_id=rule.rule_id,
                    category=rule.category,
                    safety_reply=reply,
                )

    return EmergencyMatch(matched=False)
