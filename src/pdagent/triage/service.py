"""Maintenance photo triage service and staff draft approval workflow (Phase 9)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pdagent.audit.service import AuditService
from pdagent.auth.principal import Principal
from pdagent.core.db import Base
from pdagent.core.errors import AppError, ErrorCode
from pdagent.core.ids import new_id, utc_now
from pdagent.core.rls import verify_rls_context
from pdagent.handoff.emergency import check_emergency_message
from pdagent.handoff.notify import StaffAlertDispatcher
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient
from pdagent.triage.photos import (
    build_signed_photo_url,
    estimate_image_tokens_and_cost,
    validate_photos,
)
from pdagent.triage.schemas import (
    PhotoDescriptor,
    TriageAssessment,
    TriageCategory,
    TriageUrgency,
)


class TriageDraftRow(Base):
    """Staff-reviewable maintenance draft created from photos + description (`triage_drafts` with
    RLS).
    """

    __tablename__ = "triage_drafts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    property_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    unit_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    urgency: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_questions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    photo_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    image_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_staff")
    work_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


def classify_triage_description(description: str) -> TriageAssessment:
    """Deterministic schema-validated triage classifier with at most 2 follow-up questions."""
    lower = description.lower()
    category: TriageCategory = "general"
    urgency: TriageUrgency = "routine"
    questions: list[str] = []

    if any(w in lower for w in ("leak", "pipe", "sink", "faucet", "toilet", "water", "drain")):
        category = "plumbing"
        urgency = (
            "urgent" if ("active" in lower or "floor" in lower or "ceiling" in lower) else "routine"
        )
        questions = [
            "Have you been able to turn off the local water shutoff valve under the fixture?",
            "Is water actively pooling on the floor right now?",
        ]
    elif any(w in lower for w in ("outlet", "breaker", "light", "switch", "power", "electrical")):
        category = "electrical"
        urgency = "urgent"
        questions = [
            "Has the circuit breaker in your unit panel tripped?",
            "Which room or wall outlet is affected?",
        ]
    elif any(
        w in lower for w in ("ac", "heater", "furnace", "thermostat", "hvac", "cooling", "heat")
    ):
        category = "hvac"
        urgency = "urgent" if ("below 50" in lower or "above 85" in lower) else "routine"
        questions = [
            "What temperature is currently displayed on your unit thermostat?",
            "Is the fan running when the system is set to Auto?",
        ]
    elif any(
        w in lower
        for w in ("fridge", "refrigerator", "dishwasher", "oven", "stove", "washer", "dryer")
    ):
        category = "appliance"
        urgency = "urgent" if "fridge" in lower or "refrigerator" in lower else "routine"
        questions = [
            "What is the brand or model number listed inside the appliance door?",
            "Are any error codes flashing on the display?",
        ]
    elif any(w in lower for w in ("lock", "deadbolt", "key", "door")):
        category = "locks_keys"
        urgency = "urgent"
        questions = ["Does the door still latch securely from the inside?"]
    else:
        questions = [
            "Where in the unit or building is the issue located?",
            "When did you first notice the issue?",
        ]

    return TriageAssessment(
        category=category,
        urgency=urgency,
        summary=f"Triage ({category}/{urgency}): {description.strip()[:240]}",
        follow_up_questions=questions[:2],
    )


class TriageService:
    """Creates photo triage drafts (after emergency check) and handles staff approval."""

    @staticmethod
    async def create_triage_draft(
        session: AsyncSession,
        *,
        principal: Principal,
        description: str,
        photos: list[PhotoDescriptor],
        notifier: StaffAlertDispatcher | None = None,
    ) -> dict[str, object]:
        """Run emergency rules first, validate photos, and store a `pending_staff` draft."""
        await verify_rls_context(session)
        validate_photos(photos)

        # Rules.md §1 Rule 6 & Phases.md Phase 9: Emergency-looking photo description
        # MUST go through the emergency rules first before any model/triage processing.
        emg = check_emergency_message(description)
        if emg.matched:
            if notifier is not None:
                await notifier.notify_staff(
                    org_id=principal.org_id,
                    conversation_id=new_id(),
                    reason="triage_emergency",
                    is_emergency=True,
                    matched_rule=emg.rule_id,
                )
            return {
                "status": "emergency_bypassed",
                "is_emergency": True,
                "matched_rule": emg.rule_id,
                "safety_reply": emg.safety_reply,
                "draft_id": None,
            }

        assessment = classify_triage_description(description)
        image_tokens, image_cost = estimate_image_tokens_and_cost(photos)
        prop_id = principal.property_ids[0] if principal.property_ids else None

        draft = TriageDraftRow(
            id=new_id(),
            org_id=principal.org_id,
            user_id=principal.user_id,
            property_id=prop_id,
            unit_id=principal.unit_id,
            category=assessment.category,
            urgency=assessment.urgency,
            summary=assessment.summary,
            follow_up_questions=assessment.follow_up_questions,
            photo_keys=[p.object_key for p in photos],
            image_cost_usd=image_cost,
            status="pending_staff",
            created_at=utc_now(),
        )
        session.add(draft)
        await session.flush()

        signed_urls = [
            build_signed_photo_url(org_id=principal.org_id, object_key=p.object_key) for p in photos
        ]
        return {
            "status": "pending_staff",
            "is_emergency": False,
            "draft_id": str(draft.id),
            "category": draft.category,
            "urgency": draft.urgency,
            "summary": draft.summary,
            "follow_up_questions": draft.follow_up_questions,
            "signed_photo_urls": signed_urls,
            "image_tokens": image_tokens,
            "image_cost_usd": image_cost,
        }

    @staticmethod
    async def approve_draft(
        session: AsyncSession,
        *,
        principal: Principal,
        draft_id: UUID,
        pdapi: PropertyDekApiClient,
    ) -> dict[str, object]:
        """Staff approval creates at most one work order in PropertyDek."""
        await verify_rls_context(session)
        if principal.role not in ("pm_member", "org_admin"):
            raise AppError(
                code=ErrorCode.AUTH_FORBIDDEN,
                title="Staff Role Required",
                detail="Only staff members may approve a maintenance triage draft.",
                status_code=403,
            )

        stmt = select(TriageDraftRow).where(
            TriageDraftRow.id == draft_id,
            TriageDraftRow.org_id == principal.org_id,
        )
        draft = (await session.execute(stmt)).scalar_one_or_none()
        if draft is None or not principal.can_access_property(draft.property_id):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Triage Draft Not Found",
                detail="The requested triage draft was not found.",
                status_code=404,
            )

        if draft.status == "approved" and draft.work_order_id:
            return {
                "draft_id": str(draft.id),
                "status": "approved",
                "work_order_id": draft.work_order_id,
                "idempotent_replay": True,
            }

        wo_res = await pdapi.create_request(
            principal,
            category=draft.category,
            urgency=draft.urgency if draft.urgency in ("routine", "urgent") else "urgent",
            description=draft.summary,
            idempotency_key=f"triage-draft:{draft.id}",
        )
        wo_id = str(wo_res["request_id"])
        draft.status = "approved"
        draft.work_order_id = wo_id
        await session.flush()

        await AuditService.record(
            session,
            principal=principal,
            action="triage.approved",
            target_type="triage_draft",
            target_id=str(draft.id),
            outcome="approved",
            metadata={"work_order_id": wo_id},
        )
        return {
            "draft_id": str(draft.id),
            "status": "approved",
            "work_order_id": wo_id,
            "idempotent_replay": False,
        }
