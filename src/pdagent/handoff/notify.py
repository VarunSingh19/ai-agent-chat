"""Staff alert fan-out for emergencies and handoff events (Architecture.md §7d, Rules.md §1 Rule
6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pdagent.core.ids import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StaffAlertEvent:
    """Recorded staff alert notification (PII-free: IDs, reason, and timestamps only)."""

    org_id: UUID
    conversation_id: UUID
    reason: str
    is_emergency: bool
    matched_rule: str | None
    dispatched_at: datetime


class StaffAlertDispatcher:
    """Dispatches staff alerts without depending on Redis or LLM availability."""

    def __init__(self) -> None:
        self.events: list[StaffAlertEvent] = []

    async def notify_staff(
        self,
        *,
        org_id: UUID,
        conversation_id: UUID,
        reason: str,
        is_emergency: bool,
        matched_rule: str | None = None,
    ) -> StaffAlertEvent:
        """Record and fan out a staff alert event."""
        event = StaffAlertEvent(
            org_id=org_id,
            conversation_id=conversation_id,
            reason=reason,
            is_emergency=is_emergency,
            matched_rule=matched_rule,
            dispatched_at=utc_now(),
        )
        self.events.append(event)
        logger.info(
            "Staff alert dispatched",
            extra={
                "org_id": str(org_id),
                "conversation_id": str(conversation_id),
                "reason": reason,
                "is_emergency": is_emergency,
                "matched_rule": matched_rule,
            },
        )
        return event
