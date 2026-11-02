"""Per-role tool registry enforcing hard exclusions (Architecture.md §7c, Rules.md §1 Rule 4)."""

from __future__ import annotations

from pdagent.agent.canonical import ToolSpec
from pdagent.auth.principal import Principal
from pdagent.tools.schemas import ALL_TOOL_SPECS, FORBIDDEN_IDENTITY_FIELDS

# Rules.md §1 Rule 4: Never register a tool for gate unlock, refund, fee waiver,
# lease change, payment, or notices under any role, flag, or environment variable.
PERMANENTLY_FORBIDDEN_TOOLS: frozenset[str] = frozenset(
    {
        "unlock_gate",
        "gate_unlock",
        "refund",
        "issue_refund",
        "waive_fee",
        "fee_waiver",
        "change_lease",
        "lease_change",
        "modify_lease",
        "process_payment",
        "payment",
        "make_payment",
        "send_notice",
        "notices",
        "eviction_notice",
    }
)

TENANT_ALLOWED_TOOLS: tuple[str, ...] = (
    "list_my_requests",
    "get_request",
    "get_balance",
    "list_announcements",
    "get_device_status",
    "search_knowledge",
    "create_request",
    "add_request_note",
)

STAFF_ALLOWED_TOOLS: tuple[str, ...] = (
    *TENANT_ALLOWED_TOOLS,
    "list_open_urgent",
    "summarize_day",
    "create_task",
)


def register_custom_tool(spec: ToolSpec) -> None:
    """Guard against registering any permanently forbidden tool or identity-bearing schema."""
    normalized = spec.name.strip().lower()
    if normalized in PERMANENTLY_FORBIDDEN_TOOLS or any(
        bad in normalized
        for bad in ("unlock", "refund", "waive", "lease_change", "payment", "notice")
    ):
        msg = (
            f"Refused to register forbidden tool '{spec.name}' (Rules.md §1 Rule 4). "
            "Gate unlock, refund, fee waiver, lease change, payment, and notice tools "
            "require separate written approval from FBC."
        )
        raise PermissionError(msg)

    props = spec.parameters.get("properties", {})
    if isinstance(props, dict) and (set(props.keys()) & FORBIDDEN_IDENTITY_FIELDS):
        msg = f"Tool '{spec.name}' schema contains forbidden identity fields (Rules.md §1 Rule 1)"
        raise ValueError(msg)


def resolve_tools_for_principal(
    principal: Principal,
    *,
    org_enabled_tools: list[str] | None = None,
) -> tuple[ToolSpec, ...]:
    """Return the exact tuple of `ToolSpec` definitions permitted for `principal` and `org_setti

    - Tenant tool sets are capped under 10 tools (`len <= 8`).
    - Staff tools (`list_open_urgent`, `summarize_day`, `create_task`) never appear for tenants.
    - Disabled tools in `org_settings.enabled_tools` are filtered out immediately.
    """
    if principal.role == "fbc_operator":
        return ()

    role_names = TENANT_ALLOWED_TOOLS if principal.role == "tenant" else STAFF_ALLOWED_TOOLS
    enabled_set = set(org_enabled_tools) if org_enabled_tools is not None else set(role_names)

    resolved: list[ToolSpec] = []
    for name in role_names:
        if name in PERMANENTLY_FORBIDDEN_TOOLS:
            continue
        if name not in enabled_set and name not in (
            "list_open_urgent",
            "summarize_day",
            "create_task",
        ):
            continue
        if name in ("list_open_urgent", "summarize_day", "create_task") and (
            org_enabled_tools is not None
            and name not in enabled_set
            and "staff_tools" not in enabled_set
        ):
            # If org_enabled_tools explicitly omitted staff tools, allow them for staff unless
            # explicitly disabled
            pass
        if org_enabled_tools is not None and name not in enabled_set:
            continue
        spec = ALL_TOOL_SPECS.get(name)
        if spec is not None:
            resolved.append(spec)

    return tuple(resolved)
