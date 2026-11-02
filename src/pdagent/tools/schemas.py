"""Tool input schemas and canonical JSON argument hashing (Architecture.md §7c, Rules.md §1 Rule

No tool schema may ever include `org_id`, `user_id`, `role`, `property_ids`, or `unit_id`.
Identity always comes from the verified `Principal`.
"""

from __future__ import annotations

import hashlib
import json

from pdagent.agent.canonical import ToolSpec

FORBIDDEN_IDENTITY_FIELDS: frozenset[str] = frozenset(
    {"org_id", "user_id", "role", "property_ids", "unit_id", "tenant_id"}
)


def canonical_json_hash(arguments: dict[str, object]) -> str:
    """Compute deterministic SHA-256 hex digest over sorted-key canonical JSON (Rules.md §2 & §1
    Rule 3).
    """
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


ALL_TOOL_SPECS: dict[str, ToolSpec] = {
    "list_my_requests": ToolSpec(
        name="list_my_requests",
        description="List the signed-in user's maintenance requests.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "scheduled", "completed"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "get_request": ToolSpec(
        name="get_request",
        description="Get details for a specific maintenance request by work-order ID.",
        parameters={
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "minLength": 1, "maxLength": 64},
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "get_balance": ToolSpec(
        name="get_balance",
        description=(
            "Get current rent balance, due date, and payment instructions "
            "for the signed-in user's lease."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "list_announcements": ToolSpec(
        name="list_announcements",
        description="List recent community announcements for the signed-in user's property.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "get_device_status": ToolSpec(
        name="get_device_status",
        description=(
            "Read status of smart thermostat or leak sensor in the "
            "signed-in user's unit (read-only)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "device_type": {"type": "string", "enum": ["thermostat", "leak_sensor", "all"]},
            },
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "search_knowledge": ToolSpec(
        name="search_knowledge",
        description="Search property rules, FAQs, and community documents.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 256},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "create_request": ToolSpec(
        name="create_request",
        description=(
            "Prepare a new maintenance work order (requires user confirmation before execution)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "plumbing",
                        "electrical",
                        "hvac",
                        "appliance",
                        "structural",
                        "pest",
                        "locks_keys",
                        "general",
                    ],
                },
                "urgency": {"type": "string", "enum": ["routine", "urgent"]},
                "description": {"type": "string", "minLength": 5, "maxLength": 1000},
                "entry_permission": {"type": "boolean", "default": False},
            },
            "required": ["category", "urgency", "description"],
            "additionalProperties": False,
        },
        is_write=True,
    ),
    "add_request_note": ToolSpec(
        name="add_request_note",
        description=(
            "Prepare a comment/note on an existing maintenance work order (requires confirmation)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "note": {"type": "string", "minLength": 2, "maxLength": 500},
            },
            "required": ["request_id", "note"],
            "additionalProperties": False,
        },
        is_write=True,
    ),
    # Staff-only tools (Phase 10 — never exposed to tenants)
    "list_open_urgent": ToolSpec(
        name="list_open_urgent",
        description=(
            "List open urgent maintenance requests across staff member's assigned properties."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "summarize_day": ToolSpec(
        name="summarize_day",
        description="Summarize open work orders, device alerts, and waiting handoffs for staff.",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        is_write=False,
    ),
    "create_task": ToolSpec(
        name="create_task",
        description=(
            "Prepare an internal property management task (staff only, requires confirmation)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 3, "maxLength": 200},
                "priority": {"type": "string", "enum": ["normal", "high"]},
            },
            "required": ["title", "priority"],
            "additionalProperties": False,
        },
        is_write=True,
    ),
}
