"""MCP write tool execution invoked ONLY after atomic confirmation consumption (Rules.md §1 Rule
3).
"""

from __future__ import annotations

from pdagent.auth.principal import Principal
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient


async def execute_confirmed_write_tool(
    tool_name: str,
    arguments: dict[str, object],
    *,
    principal: Principal,
    pdapi: PropertyDekApiClient,
    idempotency_key: str,
) -> dict[str, object]:
    """Execute a confirmed write tool against PropertyDek with an idempotency key."""
    if tool_name == "create_request":
        return await pdapi.create_request(
            principal,
            category=str(arguments.get("category", "general")),
            urgency=str(arguments.get("urgency", "routine")),
            description=str(arguments.get("description", "")),
            idempotency_key=idempotency_key,
        )

    if tool_name == "add_request_note":
        return await pdapi.add_request_note(
            principal,
            request_id=str(arguments.get("request_id", "")),
            note=str(arguments.get("note", "")),
            idempotency_key=idempotency_key,
        )

    if tool_name == "create_task":
        return await pdapi.create_task(
            principal,
            title=str(arguments.get("title", "")),
            priority=str(arguments.get("priority", "normal")),
            idempotency_key=idempotency_key,
        )

    msg = f"Unsupported write tool: {tool_name}"
    raise ValueError(msg)
