"""Cache-stable prompt assembly and data-delimiter sandboxing (Architecture.md §7a, Rules.md §1
Rules 5 & 10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jinja2 import Template

from pdagent.agent.canonical import PromptBundle, ToolSpec
from pdagent.core.ids import utc_now

CACHE_BREAKPOINT_MARKER = "<!-- PDAGENT_CACHE_BREAKPOINT -->"


@dataclass(frozen=True, slots=True)
class RetrievedChunkItem:
    """A retrieved knowledge base chunk to be wrapped in untrusted data delimiters."""

    document_id: str
    title: str
    heading_path: str
    content: str
    page_number: int | None = None


@lru_cache(maxsize=4)
def _load_prompt_file(filename: str) -> str:
    base_dir = Path("config/prompts")
    if not base_dir.exists():
        base_dir = Path(__file__).resolve().parents[3] / "config" / "prompts"
    target = base_dir / filename
    return target.read_text(encoding="utf-8").strip()


def build_prompt_bundle(
    *,
    tools: tuple[ToolSpec, ...],
    tone: str,
    enabled_tools: list[str],
    rolling_summary: str,
    retrieved_chunks: list[RetrievedChunkItem],
    user_message: str,
    current_time: datetime | None = None,
    forbidden_before_breakpoint: tuple[str, ...] = (),
) -> PromptBundle:
    """Assemble prompt strictly in cache-stable order (Rules.md §1 Rules 5 & 10).

    Before CACHE_BREAKPOINT:
      1. Canonical tool schemas (sorted deterministically)
      2. Fixed system rules (`config/prompts/system.md`)
      3. Organisation block (`config/prompts/org_block.md.j2`: tone & enabled tools only)

    After CACHE_BREAKPOINT:
      4. Rolling conversation summary
      5. Retrieved chunks delimited inside `<retrieved_chunk trust="data">...</retrieved_chunk>`
      6. UTC timestamp and user message inside `<user_message trust="data">...</user_message>`
    """
    tool_schemas_canonical = json.dumps(
        [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "is_write": t.is_write,
            }
            for t in sorted(tools, key=lambda item: item.name)
        ],
        sort_keys=True,
    )
    system_rules = _load_prompt_file("system.md")
    org_template_str = _load_prompt_file("org_block.md.j2")
    org_block = Template(org_template_str).render(
        tone=tone,
        enabled_tools=sorted(enabled_tools),
    )

    static_prefix = (
        f"## Available Tool Schemas\n{tool_schemas_canonical}\n\n"
        f"{system_rules}\n\n"
        f"{org_block}\n"
        f"{CACHE_BREAKPOINT_MARKER}"
    )

    for value in forbidden_before_breakpoint:
        if value and value in static_prefix:
            msg = "Per-request value leaked before the prompt-cache breakpoint (Rules.md §1 Rule 5)"
            raise ValueError(msg)

    now_iso = (current_time or utc_now()).isoformat()
    chunk_blocks: list[str] = []
    for ch in retrieved_chunks:
        escaped_body = ch.content.replace("</retrieved_chunk>", "[/retrieved_chunk]")
        page_attr = f' page="{ch.page_number}"' if ch.page_number is not None else ""
        chunk_blocks.append(
            f'<retrieved_chunk document_id="{ch.document_id}" '
            f'title="{ch.title}" section="{ch.heading_path}"{page_attr} trust="data">\n'
            f"{escaped_body}\n"
            f"</retrieved_chunk>"
        )

    chunks_section = "\n".join(chunk_blocks) if chunk_blocks else "<no_retrieved_chunks />"
    escaped_user = user_message.replace("</user_message>", "[/user_message]")
    summary_text = rolling_summary.strip() or "No prior summary."

    dynamic_suffix = (
        f"## Conversation Rolling Summary\n"
        f'<rolling_summary trust="data">{summary_text}</rolling_summary>\n\n'
        f"## Retrieved Knowledge Chunks (Untrusted Data)\n"
        f"{chunks_section}\n\n"
        f"## Current Turn Context\n"
        f"Current UTC Timestamp: {now_iso}\n"
        f'<user_message trust="data">{escaped_user}</user_message>'
    )

    return PromptBundle(
        static_prefix=static_prefix,
        dynamic_suffix=dynamic_suffix,
        tools=tools,
    )
