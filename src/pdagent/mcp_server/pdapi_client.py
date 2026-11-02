"""PropertyDek API client using RFC 8693 audience-bound user tokens (Architecture.md §6.6, §7c)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import jwt

from pdagent.auth.exchange import exchange_token_for_pdapi
from pdagent.auth.principal import Principal
from pdagent.auth.token import TEST_PUBLIC_KEY_PEM
from pdagent.core.ids import new_id, utc_now


@dataclass(slots=True)
class WorkOrderRecord:
    """In-memory representation of a PropertyDek work order for recorded contract testing."""

    request_id: str
    org_id: UUID
    user_id: UUID
    property_id: UUID | None
    category: str
    urgency: str
    description: str
    status: str = "open"
    scheduled_window: str = "Tomorrow 9:00 AM - 12:00 PM"
    notes: list[str] = field(default_factory=list)
    idempotency_key: str | None = None


class PropertyDekApiClient:
    """Client calling PropertyDek on behalf of the signed-in user (Zone B -> Zone C).

    Invariants (Architecture.md §2, §6.6, §7c):
    - Never holds a service-wide credential; every request exchanges `principal` for an
      `aud="pdapi"` token and verifies user/org/property visibility.
    - Returns `{"status": "not_visible"}` when a record is missing or belongs to another
      user/org/property (never 403, so existence is never leaked).
    """

    def __init__(self) -> None:
        self._work_orders: dict[str, WorkOrderRecord] = {}
        self._tasks: list[dict[str, object]] = []
        self._idempotency_index: dict[str, str] = {}
        self.simulate_5xx: bool = False

    def seed_work_order(self, record: WorkOrderRecord) -> None:
        """Seed a work order for integration/isolation/injection tests."""
        self._work_orders[record.request_id] = record

    def _verify_pdapi_token(self, exchanged_token: str) -> dict[str, Any]:
        decoded: dict[str, Any] = jwt.decode(
            exchanged_token,
            TEST_PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience="pdapi",
        )
        return decoded

    async def list_my_requests(
        self,
        principal: Principal,
        *,
        status: str | None = None,
        limit: int = 5,
    ) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        claims = self._verify_pdapi_token(exchanged)
        if self.simulate_5xx:
            return {"status": "unavailable"}

        caller_org = UUID(str(claims["org_id"]))
        caller_user = UUID(str(claims["sub"]))
        items: list[dict[str, object]] = []
        for wo in self._work_orders.values():
            if wo.org_id != caller_org or wo.user_id != caller_user:
                continue
            if status and wo.status != status:
                continue
            items.append(
                {
                    "request_id": wo.request_id,
                    "category": wo.category,
                    "urgency": wo.urgency,
                    "status": wo.status,
                    "scheduled_window": wo.scheduled_window,
                    "description": wo.description,
                }
            )
        return {"status": "ok", "items": items[: min(limit, 20)]}

    async def get_request(self, principal: Principal, *, request_id: str) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        claims = self._verify_pdapi_token(exchanged)
        if self.simulate_5xx:
            return {"status": "unavailable"}

        caller_org = UUID(str(claims["org_id"]))
        caller_user = UUID(str(claims["sub"]))
        caller_role = str(claims["role"])

        wo = self._work_orders.get(request_id)
        if wo is None or wo.org_id != caller_org:
            return {"status": "not_visible"}
        if caller_role == "tenant" and wo.user_id != caller_user:
            return {"status": "not_visible"}
        if caller_role == "pm_member" and not principal.can_access_property(wo.property_id):
            return {"status": "not_visible"}

        return {
            "status": "ok",
            "request_id": wo.request_id,
            "category": wo.category,
            "urgency": wo.urgency,
            "work_order_status": wo.status,
            "scheduled_window": wo.scheduled_window,
            "description": wo.description,
            "notes": list(wo.notes),
        }

    async def get_balance(self, principal: Principal) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        self._verify_pdapi_token(exchanged)
        if self.simulate_5xx:
            return {"status": "unavailable"}
        return {
            "status": "ok",
            "current_balance_usd": 1450.00,
            "next_due_date": "2026-11-01",
            "payment_instructions": "Pay via ACH or card in the PropertyDek Resident "
            "Portal > Payments tab.",
        }

    async def list_announcements(
        self, principal: Principal, *, limit: int = 5
    ) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        self._verify_pdapi_token(exchanged)
        if self.simulate_5xx:
            return {"status": "unavailable"}
        return {
            "status": "ok",
            "items": [
                {
                    "id": "ann-1",
                    "title": "Seasonal HVAC Filter Inspection",
                    "published_at": "2026-10-28T12:00:00Z",
                    "summary": "Maintenance staff will replace hallway HVAC filters this Thursday.",
                }
            ][:limit],
        }

    async def get_device_status(
        self, principal: Principal, *, device_type: str = "all"
    ) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        self._verify_pdapi_token(exchanged)
        if self.simulate_5xx:
            return {"status": "unavailable"}
        return {
            "status": "ok",
            "device_type": device_type,
            "thermostat": {
                "mode": "cool",
                "current_temp_f": 71,
                "target_temp_f": 70,
                "online": True,
            },
            "leak_sensor": {"state": "dry", "battery_pct": 94, "online": True},
        }

    async def list_open_urgent(self, principal: Principal, *, limit: int = 10) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        claims = self._verify_pdapi_token(exchanged)
        if str(claims["role"]) == "tenant":
            return {"status": "not_visible"}
        caller_org = UUID(str(claims["org_id"]))
        items = [
            {
                "request_id": wo.request_id,
                "category": wo.category,
                "urgency": wo.urgency,
                "description": wo.description,
            }
            for wo in self._work_orders.values()
            if wo.org_id == caller_org
            and wo.urgency == "urgent"
            and principal.can_access_property(wo.property_id)
        ]
        return {"status": "ok", "items": items[:limit]}

    async def summarize_day(self, principal: Principal) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        claims = self._verify_pdapi_token(exchanged)
        if str(claims["role"]) == "tenant":
            return {"status": "not_visible"}
        caller_org = UUID(str(claims["org_id"]))
        org_orders = [
            wo
            for wo in self._work_orders.values()
            if wo.org_id == caller_org and principal.can_access_property(wo.property_id)
        ]
        return {
            "status": "ok",
            "open_work_orders_count": len(org_orders),
            "urgent_count": sum(1 for wo in org_orders if wo.urgency == "urgent"),
            "generated_at": utc_now().isoformat(),
        }

    async def create_request(
        self,
        principal: Principal,
        *,
        category: str,
        urgency: str,
        description: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        self._verify_pdapi_token(exchanged)
        if self.simulate_5xx:
            msg = "PropertyDek API 503 Unavailable"
            raise RuntimeError(msg)

        idem_scope = f"{principal.org_id}:{principal.user_id}:{idempotency_key}"
        existing_id = self._idempotency_index.get(idem_scope)
        if existing_id and existing_id in self._work_orders:
            wo = self._work_orders[existing_id]
            return {"status": "created", "request_id": wo.request_id, "idempotent_replay": True}

        req_id = f"WO-{str(new_id())[:8].upper()}"
        prop_id = principal.property_ids[0] if principal.property_ids else None
        record = WorkOrderRecord(
            request_id=req_id,
            org_id=principal.org_id,
            user_id=principal.user_id,
            property_id=prop_id,
            category=category,
            urgency=urgency,
            description=description,
            idempotency_key=idempotency_key,
        )
        self._work_orders[req_id] = record
        self._idempotency_index[idem_scope] = req_id
        return {"status": "created", "request_id": req_id, "idempotent_replay": False}

    async def add_request_note(
        self,
        principal: Principal,
        *,
        request_id: str,
        note: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        self._verify_pdapi_token(exchanged)
        wo = self._work_orders.get(request_id)
        if wo is None or wo.org_id != principal.org_id:
            return {"status": "not_visible"}
        if principal.role == "tenant" and wo.user_id != principal.user_id:
            return {"status": "not_visible"}
        if note not in wo.notes:
            wo.notes.append(note)
        return {"status": "updated", "request_id": wo.request_id, "notes_count": len(wo.notes)}

    async def create_task(
        self,
        principal: Principal,
        *,
        title: str,
        priority: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        exchanged = exchange_token_for_pdapi(principal)
        self._verify_pdapi_token(exchanged)
        if principal.role == "tenant":
            return {"status": "not_visible"}
        task_id = f"TASK-{str(new_id())[:8].upper()}"
        self._tasks.append(
            {
                "task_id": task_id,
                "org_id": str(principal.org_id),
                "title": title,
                "priority": priority,
                "idempotency_key": idempotency_key,
            }
        )
        return {"status": "created", "task_id": task_id}
