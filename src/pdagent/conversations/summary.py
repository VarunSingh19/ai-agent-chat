"""Rolling conversation summary generator (Rules.md §5 LLM05)."""

from __future__ import annotations

from pdagent.conversations.repo import MessageRow


def build_rolling_summary(messages: list[MessageRow], *, max_chars: int = 600) -> str:
    """Regenerate the rolling summary strictly from user and assistant messages (never tool outp

    Rules.md §5 LLM05: "rolling summary is regenerated from messages, never from tool output alone."
    """
    dialogue_lines: list[str] = []
    for m in messages[-8:]:
        if m.sender_role not in ("user", "assistant", "staff"):
            continue
        snippet = " ".join(m.content.strip().split())[:120]
        dialogue_lines.append(f"{m.sender_role}: {snippet}")

    combined = " | ".join(dialogue_lines)
    return combined[:max_chars]
