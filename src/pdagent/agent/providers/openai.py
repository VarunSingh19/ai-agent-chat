"""OpenAI Responses API adapter (`openai >=3,<4`, Architecture.md §1, §7f)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from pdagent.agent.canonical import (
    CanonicalMessage,
    PromptBundle,
    StreamEvent,
    ToolCall,
    TurnConfig,
    UsageStats,
)
from pdagent.agent.providers.base import ModelPricingSpec


class OpenAIProvider:
    """Adapter for OpenAI `/v1/responses` API (`gpt-6-luna`, `gpt-6.1-sol`)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: AsyncOpenAI | None = AsyncOpenAI(api_key=api_key) if api_key else None

    @property
    def name(self) -> str:
        return "openai"

    async def stream(
        self,
        prompt: PromptBundle,
        messages: list[CanonicalMessage],
        config: TurnConfig,
        model_spec: ModelPricingSpec,
    ) -> AsyncIterator[StreamEvent]:
        """Invoke OpenAI `/v1/responses` with cache-stable instructions prefix."""
        if self._client is None:
            msg = "OpenAI API key is not configured"
            raise RuntimeError(msg)

        instructions = f"{prompt.static_prefix}\n\n{prompt.dynamic_suffix}"
        input_items: list[dict[str, Any]] = []
        for m in messages:
            role = "assistant" if m.role == "assistant" else "user"
            content = (
                f'<tool_result tool="{m.tool_name or "unknown"}" '
                f'trust="data">{m.content}</tool_result>'
                if m.role == "tool"
                else m.content
            )
            input_items.append({"role": role, "content": content})

        tools_payload: list[dict[str, Any]] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in prompt.tools
        ]

        kwargs: dict[str, Any] = {
            "model": model_spec.model_id,
            "instructions": instructions,
            "input": input_items,
            "max_output_tokens": config.max_output_tokens,
        }
        if tools_payload:
            kwargs["tools"] = tools_payload

        resp = await self._client.responses.create(**kwargs)
        output_text = getattr(resp, "output_text", "")
        if output_text:
            yield StreamEvent(kind="token", text=str(output_text))

        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "function_call":
                raw_args = getattr(item, "arguments", "{}")
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                yield StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(
                        call_id=str(getattr(item, "call_id", "call_1")),
                        name=str(getattr(item, "name", "")),
                        arguments=parsed_args,
                    ),
                )

        usage_obj = getattr(resp, "usage", None)
        in_tok = int(getattr(usage_obj, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage_obj, "output_tokens", 0) or 0)
        details = getattr(usage_obj, "input_tokens_details", None)
        cached_tok = int(getattr(details, "cached_tokens", 0) or 0)
        out_details = getattr(usage_obj, "output_tokens_details", None)
        reasoning_tok = int(getattr(out_details, "reasoning_tokens", 0) or 0)

        yield StreamEvent(
            kind="usage",
            usage=UsageStats(
                provider=self.name,
                model=model_spec.model_id,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cache_read_tokens=cached_tok,
                reasoning_tokens=reasoning_tok,
            ),
        )
