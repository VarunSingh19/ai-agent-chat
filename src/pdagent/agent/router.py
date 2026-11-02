"""Deterministic rule-first turn router and intent classifier (Architecture.md §7a, §7e)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pdagent.agent.canonical import RouteSlot

IntentLabel = Literal[
    "faq",
    "status_lookup",
    "create_request",
    "handoff_request",
    "legal_or_fair_housing",
    "forbidden_capability",
    "complex_agent",
]


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Result of classifying a user message before invoking the turn loop."""

    intent: IntentLabel
    route: RouteSlot
    immediate_handoff_reason: str | None = None
    canned_response: str | None = None


_HANDOFF_PHRASES: tuple[str, ...] = (
    "talk to a human",
    "speak to a human",
    "speak with a real person",
    "connect me with the property manager",
    "connect me with staff",
    "transfer me to a person",
    "live agent",
    "human representative",
    "escalate this",
)

_LEGAL_OR_FAIR_HOUSING_PHRASES: tuple[str, ...] = (
    "housing authority",
    "my lawyer",
    "attorney",
    "sue the landlord",
    "legal action",
    "fair housing",
    "emotional support animal",
    "service animal",
    "disability accommodation",
    "credit score requirement",
    "criminal background check",
    "eviction notice",
)

_FORBIDDEN_CAPABILITY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("unlock the front gate", "buzz me in", "open the gate remotely", "unlock the main gate"),
        "For building security, the assistant cannot unlock gates or doors remotely. "
        "Please use your PropertyDek mobile key or contact on-site staff.",
    ),
    (
        ("waive my", "late fee waiver", "remove the late fee", "refund my", "issue a refund"),
        "The assistant cannot waive fees or issue refunds. You can view your ledger in "
        "the Payments screen or speak with your property manager.",
    ),
    (
        (
            "remove my roommate from the lease",
            "change my lease",
            "modify my lease",
            "extend my lease",
        ),
        "Lease changes require formal review and signature by all parties. I can "
        "connect you with your property manager to start a lease modification.",
    ),
)

_CREATE_WRITE_PHRASES: tuple[str, ...] = (
    "submit a maintenance",
    "create a maintenance",
    "open a maintenance",
    "file a maintenance",
    "new maintenance request",
    "add a comment to work order",
    "add a note to my maintenance",
    "schedule a viewing",
    "book a tour",
)

_STATUS_LOOKUP_PHRASES: tuple[str, ...] = (
    "status of my maintenance",
    "open maintenance requests",
    "when is the plumber",
    "rent balance",
    "current balance",
    "how much rent",
    "when does my lease expire",
    "lease end date",
    "smart thermostat",
    "announcements",
)


def classify_and_route(user_message: str, *, has_photos: bool = False) -> RouteDecision:
    """Classify `user_message` using deterministic rules first (Haiku/small-first routing)."""
    normalized = " ".join(user_message.lower().strip().split())

    if has_photos:
        return RouteDecision(intent="create_request", route="triage")

    for phrases, canned in _FORBIDDEN_CAPABILITY_RULES:
        if any(p in normalized for p in phrases):
            return RouteDecision(
                intent="forbidden_capability",
                route="small",
                canned_response=canned,
            )

    if any(p in normalized for p in _LEGAL_OR_FAIR_HOUSING_PHRASES):
        return RouteDecision(
            intent="legal_or_fair_housing",
            route="small",
            immediate_handoff_reason="legal_or_fair_housing",
            canned_response=(
                "Questions involving legal notices, fair housing, or leasing eligibility are "
                "handled directly by our property management staff. I have queued your "
                "conversation "
                "for a team member."
            ),
        )

    if any(p in normalized for p in _HANDOFF_PHRASES):
        return RouteDecision(
            intent="handoff_request",
            route="small",
            immediate_handoff_reason="user_requested_human",
            canned_response=(
                "I have transferred this conversation to your property management team. "
                "A staff member will reply here shortly."
            ),
        )

    if any(p in normalized for p in _CREATE_WRITE_PHRASES):
        return RouteDecision(intent="create_request", route="large")

    if any(p in normalized for p in _STATUS_LOOKUP_PHRASES):
        return RouteDecision(intent="status_lookup", route="small")

    return RouteDecision(intent="faq", route="small")
