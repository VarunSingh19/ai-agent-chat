"""Verified Principal identity model (Architecture.md §6, Rules.md §1 Rule 1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Role = Literal["tenant", "pm_member", "org_admin", "fbc_operator"]


@dataclass(frozen=True, slots=True)
class Principal:
    """Immutable authenticated caller identity derived strictly from a verified JWT.

    Rules.md §1 Rule 1: Never read org_id, user_id, role, property_ids or unit_id
    from a request body, query string, unverified header, or model output.
    """

    org_id: UUID
    user_id: UUID
    role: Role
    property_ids: tuple[UUID, ...]
    unit_id: UUID | None
    jti: str
    raw_token: str

    def can_access_property(self, property_id: UUID | None) -> bool:
        """Check whether this principal is permitted to access a specific property."""
        if property_id is None:
            return True
        if self.role == "org_admin":
            return True
        return property_id in self.property_ids
