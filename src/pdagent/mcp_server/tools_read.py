"""MCP read tool implementations with 1-retry and `not_visible` handling (Architecture.md §7c)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.principal import Principal
from pdagent.knowledge.retrieve import retrieve_knowledge_chunks
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient


async def dispatch_read_tool(
    name: str,
    arguments: dict[str, object],
    *,
    principal: Principal,
    pdapi: PropertyDekApiClient,
    session: AsyncSession | None = None,
) -> dict[str, object]:
    """Execute a read-only tool as `principal`, retrying once on transient error."""
    for attempt in range(2):
        try:
            if name == "list_my_requests":
                status_filter = str(arguments["status"]) if "status" in arguments else None
                limit = int(str(arguments.get("limit", 5)))
                return await pdapi.list_my_requests(principal, status=status_filter, limit=limit)

            if name == "get_request":
                req_id = str(arguments.get("request_id", ""))
                return await pdapi.get_request(principal, request_id=req_id)

            if name == "get_balance":
                return await pdapi.get_balance(principal)

            if name == "list_announcements":
                limit = int(str(arguments.get("limit", 5)))
                return await pdapi.list_announcements(principal, limit=limit)

            if name == "get_device_status":
                dev_type = str(arguments.get("device_type", "all"))
                return await pdapi.get_device_status(principal, device_type=dev_type)

            if name == "list_open_urgent":
                limit = int(str(arguments.get("limit", 10)))
                return await pdapi.list_open_urgent(principal, limit=limit)

            if name == "summarize_day":
                return await pdapi.summarize_day(principal)

            if name == "search_knowledge":
                if session is None:
                    return {"status": "ok", "chunks": []}
                query = str(arguments.get("query", ""))
                outcome = await retrieve_knowledge_chunks(
                    session, principal=principal, query=query, top_k=5
                )
                return {
                    "status": "ok",
                    "degraded_retrieval": outcome.degraded_retrieval,
                    "chunks": [
                        {
                            "document_id": c.document_id,
                            "title": c.title,
                            "section": c.heading_path,
                            "content": c.content,
                        }
                        for c in outcome.chunks
                    ],
                }
        except Exception:
            if attempt >= 1:
                break

    return {"status": "unavailable"}
