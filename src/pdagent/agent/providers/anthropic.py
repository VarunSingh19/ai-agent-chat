"""Anthropic Messages API adapter (`anthropic >=1,<2`, Architecture.md §1, §7f).

Rules.md §2: Never pass `temperature`, `top_p`, or `top_k` to Anthropic SDK 1.x (raises TypeError).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from pdagent.agent.canonical import (
    CanonicalMessage,
    PromptBundle,
    StreamEvent,
    ToolCall,
    TurnConfig,
    UsageStats,
)
from pdagent.agent.providers.base import ModelPricingSpec


class AnthropicProvider:
    """Adapter for Anthropic Claude 5.5 models (`claude-haiku-5-5`, `claude-sonnet-5-5`)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: AsyncAnthropic | None = AsyncAnthropic(api_key=api_key) if api_key else None

    @property
    def name(self) -> str:
        return "anthropic"

    async def stream(
        self,
        prompt: PromptBundle,
        messages: list[CanonicalMessage],
        config: TurnConfig,
        model_spec: ModelPricingSpec,
    ) -> AsyncIterator[StreamEvent]:
        """Call Anthropic Messages API with ephemeral prompt-cache breakpoint."""
        if self._client is None:
            msg = "Anthropic API key is not configured"
            raise RuntimeError(msg)

        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": prompt.static_prefix,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": prompt.dynamic_suffix,
            },
        ]

        formatted_msgs: list[dict[str, Any]] = []
        for m in messages:
            role = "assistant" if m.role == "assistant" else "user"
            content = (
                f'<tool_result tool="{m.tool_name or "unknown"}" '
                f'trust="data">{m.content}</tool_result>'
                if m.role == "tool"
                else m.content
            )
            formatted_msgs.append({"role": role, "content": content})

        tools_payload: list[dict[str, Any]] = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in prompt.tools
        ]

        kwargs: dict[str, Any] = {
            "model": model_spec.model_id,
            "max_tokens": config.max_output_tokens,
            "system": system_blocks,
            "messages": formatted_msgs,
        }
        if tools_payload:
            kwargs["tools"] = tools_payload

        resp = await self._client.messages.create(**kwargs)
        for block in getattr(resp, "content", []):
            b_type = getattr(block, "type", "")
            if b_type == "text":
                text_val = str(getattr(block, "text", ""))
                if text_val:
                    yield StreamEvent(kind="token", text=text_val)
            elif b_type == "tool_use":
                raw_input = getattr(block, "input", {})
                args = raw_input if isinstance(raw_input, dict) else json.loads(str(raw_input))
                yield StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(
                        call_id=str(getattr(block, "id", "")),
                        name=str(getattr(block, "name", "")),
                        arguments=args,
                    ),
                )

        usage_obj = getattr(resp, "usage", None)
        in_tok = int(getattr(usage_obj, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage_obj, "output_tokens", 0) or 0)
        cache_read = int(getattr(usage_obj, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage_obj, "cache_creation_input_tokens", 0) or 0)
        yield StreamEvent(
            kind="usage",
            usage=UsageStats(
                provider=self.name,
                model=model_spec.model_id,
                input_tokens=in_tok + cache_read + cache_write,
                output_tokens=out_tok,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            ),
        )
