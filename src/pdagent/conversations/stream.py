"""SSE event formatting for `/v1/conversations/{id}/messages` (Architecture.md §8)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator


def format_sse_frame(event: str, data: dict[str, object], *, event_id: str | None = None) -> str:
    """Format a standards-compliant Server-Sent Event frame."""
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    lines.append("")
    return "\n".join(lines) + "\n"


async def render_sse_stream(
    events: list[tuple[str, dict[str, object], str | None]],
) -> AsyncIterator[str]:
    """Yield formatted SSE frames for a completed or replayed turn."""
    for event_name, payload, evt_id in events:
        yield format_sse_frame(event_name, payload, event_id=evt_id)
