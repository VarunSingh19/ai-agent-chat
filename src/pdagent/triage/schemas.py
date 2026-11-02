"""Pydantic schemas for maintenance photo triage (Phase 9, Architecture.md §3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TriageCategory = Literal[
    "plumbing",
    "electrical",
    "hvac",
    "appliance",
    "structural",
    "pest",
    "locks_keys",
    "general",
]
TriageUrgency = Literal["routine", "urgent", "emergency"]


class PhotoDescriptor(BaseModel):
    """Metadata for an uploaded maintenance photo."""

    object_key: str = Field(min_length=3, max_length=256)
    content_type: str = Field(default="image/jpeg")
    size_bytes: int = Field(gt=0, le=5 * 1024 * 1024)
    width_px: int = Field(default=800, gt=0, le=4096)
    height_px: int = Field(default=600, gt=0, le=4096)


class TriageAssessment(BaseModel):
    """Schema-validated output of maintenance photo + description triage."""

    category: TriageCategory
    urgency: TriageUrgency
    summary: str = Field(min_length=5, max_length=1000)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=2)
