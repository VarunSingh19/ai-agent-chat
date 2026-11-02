"""Deterministic in-memory FakeLLMProvider for tests and evals (Rules.md §1 Rule 8)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from pdagent.agent.canonical import (
    CanonicalMessage,
    PromptBundle,
    StreamEvent,
    ToolCall,
    TurnConfig,
    UsageStats,
)
from pdagent.agent.providers.base import ModelPricingSpec


class FakeLLMProvider:
    """Configurable provider double at the `LLMProvider` boundary (never mock HTTP SDKs)."""

    def __init__(
        self,
        *,
        provider_name: str = "anthropic",
        fail_before_first_token: bool = False,
        fail_after_first_token: bool = False,
        canned_text: str | None = None,
        canned_tool_call: ToolCall | None = None,
    ) -> None:
        self._name = provider_name
        self.fail_before_first_token = fail_before_first_token
        self.fail_after_first_token = fail_after_first_token
        self.canned_text = canned_text
        self.canned_tool_call = canned_tool_call
        self.call_count = 0
        self.seen_prompts: list[PromptBundle] = []

    @property
    def name(self) -> str:
        return self._name

    async def stream(
        self,
        prompt: PromptBundle,
        messages: list[CanonicalMessage],
        config: TurnConfig,
        model_spec: ModelPricingSpec,
    ) -> AsyncIterator[StreamEvent]:
        """Yield deterministic tokens or tool calls based on the conversation state."""
        self.call_count += 1
        self.seen_prompts.append(prompt)

        if self.fail_before_first_token:
            msg = f"Simulated {self._name} provider outage before first token"
            raise RuntimeError(msg)

        has_tool_result = any(m.role == "tool" for m in messages)
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        lower_user = last_user.lower()

        if self.canned_tool_call is not None and not has_tool_result:
            yield StreamEvent(kind="tool_call", tool_call=self.canned_tool_call)
            yield StreamEvent(
                kind="usage",
                usage=UsageStats(
                    provider=self._name,
                    model=model_spec.model_id,
                    input_tokens=640,
                    output_tokens=45,
                    cache_read_tokens=512 if self.call_count > 1 else 0,
                    cache_write_tokens=512 if self.call_count == 1 else 0,
                ),
            )
            return

        if not has_tool_result and self.canned_text is None:
            tool_names = {t.name for t in prompt.tools}
            if ("create" in lower_user or "submit" in lower_user or "leaking" in lower_user) and (
                "create_request" in tool_names
            ):
                yield StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(
                        call_id="call_create_req_1",
                        name="create_request",
                        arguments={
                            "category": "plumbing",
                            "urgency": "routine",
                            "description": last_user[:200],
                        },
                    ),
                )
                yield StreamEvent(
                    kind="usage",
                    usage=UsageStats(
                        provider=self._name,
                        model=model_spec.model_id,
                        input_tokens=600,
                        output_tokens=40,
                        cache_read_tokens=512,
                    ),
                )
                return

            if ("status" in lower_user or "work order" in lower_user) and (
                "list_my_requests" in tool_names
            ):
                yield StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(
                        call_id="call_list_req_1",
                        name="list_my_requests",
                        arguments={"limit": 5},
                    ),
                )
                yield StreamEvent(
                    kind="usage",
                    usage=UsageStats(
                        provider=self._name,
                        model=model_spec.model_id,
                        input_tokens=580,
                        output_tokens=30,
                        cache_read_tokens=512,
                    ),
                )
                return

            if ("balance" in lower_user or "rent" in lower_user) and ("get_balance" in tool_names):
                yield StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(
                        call_id="call_balance_1",
                        name="get_balance",
                        arguments={},
                    ),
                )
                yield StreamEvent(
                    kind="usage",
                    usage=UsageStats(
                        provider=self._name,
                        model=model_spec.model_id,
                        input_tokens=580,
                        output_tokens=28,
                        cache_read_tokens=512,
                    ),
                )
                return

        if has_tool_result:
            last_tool = next(m for m in reversed(messages) if m.role == "tool")
            if '"not_visible"' in last_tool.content:
                reply = (
                    "I cannot see or access that record under your account permissions. "
                    "Would you like me to connect you with property management staff?"
                )
            else:
                reply = f"Based on your PropertyDek account records: {last_tool.content}"
        elif self.canned_text is not None:
            reply = self.canned_text
        elif "<retrieved_chunk" in prompt.dynamic_suffix:
            reply = (
                "According to the community handbook in your retrieved property documents, "
                "quiet hours run from 10:00 PM to 7:00 AM daily."
            )
        else:
            reply = (
                "I do not have a verified community document answering that specific question. "
                "Would you like me to connect you with property management staff?"
            )

        words = reply.split(" ")
        for idx, word in enumerate(words):
            piece = word if idx == 0 else f" {word}"
            yield StreamEvent(kind="token", text=piece)
            if idx == 0 and self.fail_after_first_token:
                msg = f"Simulated {self._name} mid-stream failure after first token"
                raise RuntimeError(msg)

        yield StreamEvent(
            kind="usage",
            usage=UsageStats(
                provider=self._name,
                model=model_spec.model_id,
                input_tokens=650,
                output_tokens=max(10, len(words)),
                cache_read_tokens=512 if self.call_count > 1 else 0,
                cache_write_tokens=512 if self.call_count == 1 else 0,
            ),
        )
