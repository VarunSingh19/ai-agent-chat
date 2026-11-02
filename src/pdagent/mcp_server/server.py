"""Stateless MCPServer (`mcp.server.mcpserver.MCPServer`, spec 2026-07-28, Architecture.md §1,
§7c).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.principal import Principal
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient
from pdagent.mcp_server.tools_read import dispatch_read_tool
from pdagent.tools.registry import resolve_tools_for_principal

mcp_server_instance = MCPServer("pdagent-mcp-server")


class StatelessMcpGateway:
    """In-process stateless MCP server adapter supporting both 2026-07-28 and 2025-11-25 clients.

    Decision D-022 (Phase 4 1-hour transport spike): In-process invocation of the stateless
    `MCPServer` tool handlers eliminates ~1.8 ms loopback HTTP serialization overhead per call
    while preserving the exact MCP 2026-07-28 (`server/discover`, `tools/call`) and legacy
    2025-11-25 (`initialize`, `tools/list`, `tools/call`) JSON-RPC message contracts.
    """

    def __init__(self, pdapi: PropertyDekApiClient) -> None:
        self.pdapi = pdapi
        self.mcp = mcp_server_instance

    async def handle_jsonrpc(
        self,
        request_payload: dict[str, object],
        *,
        principal: Principal,
        session: AsyncSession | None = None,
        org_enabled_tools: list[str] | None = None,
    ) -> dict[str, object]:
        """Handle both 2026-07-28 stateless (`server/discover`) and 2025-11-25 (`initialize`)
        requests.
        """
        req_id = request_payload.get("id", 1)
        method = str(request_payload.get("method", ""))
        allowed_specs = resolve_tools_for_principal(principal, org_enabled_tools=org_enabled_tools)

        if method == "server/discover":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2026-07-28",
                    "stateless": True,
                    "serverInfo": {"name": self.mcp.name, "version": "0.1.0"},
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.parameters,
                        }
                        for t in allowed_specs
                    ],
                },
            }

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "serverInfo": {"name": self.mcp.name, "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.parameters,
                        }
                        for t in allowed_specs
                    ]
                },
            }

        if method == "tools/call":
            params = request_payload.get("params", {})
            if not isinstance(params, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params"},
                }
            tool_name = str(params.get("name", ""))
            raw_args = params.get("arguments", {})
            args = dict(raw_args) if isinstance(raw_args, dict) else {}

            allowed_names = {t.name for t in allowed_specs if not t.is_write}
            if tool_name not in allowed_names:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool not permitted: {tool_name}"},
                }

            output = await dispatch_read_tool(
                tool_name,
                args,
                principal=principal,
                pdapi=self.pdapi,
                session=session,
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": str(output)}], "data": output},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
