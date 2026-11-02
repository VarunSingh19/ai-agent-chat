"""Google Gemini API adapter (`google-genai >=2,<3`, Architecture.md §1, §7f, Decision D-020)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types

from pdagent.agent.canonical import (
    CanonicalMessage,
    PromptBundle,
    StreamEvent,
    ToolCall,
    TurnConfig,
    UsageStats,
)
from pdagent.agent.providers.base import ModelPricingSpec


class GeminiProvider:
    """Adapter for Google Gemini models (`gemini-3.8-flash` small, `gemini-4-argon` large)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: genai.Client | None = genai.Client(api_key=api_key) if api_key else None

    @property
    def name(self) -> str:
        return "gemini"

    async def stream(
        self,
        prompt: PromptBundle,
        messages: list[CanonicalMessage],
        config: TurnConfig,
        model_spec: ModelPricingSpec,
    ) -> AsyncIterator[StreamEvent]:
        """Stream tokens and function calls from Google Gemini via `google-genai` SDK."""
        if self._client is None:
            msg = "Google Gemini API key is not configured"
            raise RuntimeError(msg)

        system_instruction = f"{prompt.static_prefix}\n\n{prompt.dynamic_suffix}"
        contents: list[types.Content] = []
        for m in messages:
            role = "model" if m.role == "assistant" else "user"
            text_body = (
                f'<tool_result tool="{m.tool_name or "unknown"}" '
                f'trust="data">{m.content}</tool_result>'
                if m.role == "tool"
                else m.content
            )
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=text_body)],
                )
            )

        func_decls: list[types.FunctionDeclaration] = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.parameters,
            )
            for t in prompt.tools
        ]
        gemini_tools: list[Any] | None = (
            [types.Tool(function_declarations=func_decls)] if func_decls else None
        )

        gen_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=config.max_output_tokens,
            tools=gemini_tools,
        )

        response = await self._client.aio.models.generate_content(
            model=model_spec.model_id,
            contents=contents,
            config=gen_config,
        )

        if response.text:
            yield StreamEvent(kind="token", text=str(response.text))

        if response.function_calls:
            for idx, fc in enumerate(response.function_calls):
                args_dict = dict(fc.args) if fc.args else {}
                yield StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(
                        call_id=f"gemini_call_{idx + 1}",
                        name=str(fc.name or ""),
                        arguments=args_dict,
                    ),
                )

        usage_meta = response.usage_metadata
        in_tok = int(getattr(usage_meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(usage_meta, "candidates_token_count", 0) or 0)
        cached_tok = int(getattr(usage_meta, "cached_content_token_count", 0) or 0)
        thoughts_tok = int(getattr(usage_meta, "thoughts_token_count", 0) or 0)

        yield StreamEvent(
            kind="usage",
            usage=UsageStats(
                provider=self.name,
                model=model_spec.model_id,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cache_read_tokens=cached_tok,
                reasoning_tokens=thoughts_tok,
            ),
        )
