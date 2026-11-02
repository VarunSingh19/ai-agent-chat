"""Agent turn loop with hard code-enforced caps (Architecture.md §7a, Rules.md §1 Rules 3 & 9)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pdagent.agent.canonical import (
    CanonicalMessage,
    PromptBundle,
    RouteSlot,
    ToolCall,
    TurnConfig,
    UsageStats,
)
from pdagent.agent.providers.base import MidStreamProviderError, ProviderGateway

MAX_TOOL_CALLS_PER_TURN = 6
MAX_RETRIEVAL_CALLS_PER_TURN = 2
MAX_OUTPUT_TOKENS_PER_CALL = 400
MAX_WALL_CLOCK_SECONDS = 45.0

ReadToolExecutor = Callable[[str, dict[str, object]], Awaitable[dict[str, object]]]
WriteConfirmationCreator = Callable[[ToolCall], Awaitable[dict[str, object]]]


@dataclass(slots=True)
class TurnLoopResult:
    """Aggregated result of running the bounded agent turn loop."""

    assistant_text: str = ""
    tokens_emitted: list[str] = field(default_factory=list)
    tool_names_called: list[str] = field(default_factory=list)
    confirmation_card: dict[str, object] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    provider: str = "anthropic"
    model: str = "claude-haiku-5-5"
    route: RouteSlot = "small"
    failover: bool = False
    error_code: str | None = None
    latency_ms: int = 0


async def run_agent_turn_loop(
    *,
    gateway: ProviderGateway,
    prompt: PromptBundle,
    initial_messages: list[CanonicalMessage],
    route: RouteSlot,
    execute_read_tool: ReadToolExecutor,
    create_write_confirmation: WriteConfirmationCreator,
    max_tool_calls: int = MAX_TOOL_CALLS_PER_TURN,
    max_retrieval_calls: int = MAX_RETRIEVAL_CALLS_PER_TURN,
    max_output_tokens: int = MAX_OUTPUT_TOKENS_PER_CALL,
    wall_clock_seconds: float = MAX_WALL_CLOCK_SECONDS,
) -> TurnLoopResult:
    """Execute the bounded model -> tool -> model loop (Rules.md §1 Rules 3, 9, 10).

    Hard invariants:
    - Never exceeds `max_tool_calls` (≤ 6) or `max_retrieval_calls` (≤ 2).
    - Enforces `wall_clock_seconds` (45 s) timeout across the entire turn.
    - Never executes a write tool directly: any tool with `is_write=True` creates a
      pending confirmation card and immediately terminates the loop.
    """
    started = time.monotonic()
    result = TurnLoopResult(route=route)
    messages = list(initial_messages)
    write_tool_names = {t.name for t in prompt.tools if t.is_write}
    allowed_tool_names = {t.name for t in prompt.tools}

    tool_calls_count = 0
    retrieval_calls_count = 0

    try:
        async with asyncio.timeout(wall_clock_seconds):
            while True:
                turn_cfg = TurnConfig(
                    route=route,
                    max_output_tokens=min(max_output_tokens, MAX_OUTPUT_TOKENS_PER_CALL),
                )
                pending_tool_calls: list[ToolCall] = []

                async for event in gateway.stream_with_failover(prompt, messages, turn_cfg):
                    if event.kind == "token" and event.text:
                        result.tokens_emitted.append(event.text)
                    elif event.kind == "tool_call" and event.tool_call is not None:
                        pending_tool_calls.append(event.tool_call)
                    elif event.kind == "usage" and event.usage is not None:
                        _accumulate_usage(result, event.usage)

                if not pending_tool_calls:
                    break

                for tc in pending_tool_calls:
                    if tc.name not in allowed_tool_names:
                        messages.append(
                            CanonicalMessage(
                                role="tool",
                                tool_call_id=tc.call_id,
                                tool_name=tc.name,
                                content=json.dumps({"status": "forbidden_tool"}),
                            )
                        )
                        continue

                    if tc.name in write_tool_names:
                        # Rules.md §1 Rule 3: Write tools NEVER execute inside the agent loop.
                        card = await create_write_confirmation(tc)
                        result.confirmation_card = card
                        result.tool_names_called.append(tc.name)
                        if not result.tokens_emitted:
                            summary_str = str(card.get("summary", "Please confirm this request."))
                            msg_txt = f"Please review and confirm your request: {summary_str}"
                            result.tokens_emitted.append(msg_txt)
                        result.assistant_text = "".join(result.tokens_emitted)
                        result.latency_ms = int((time.monotonic() - started) * 1000)
                        return result

                    if tool_calls_count >= max_tool_calls:
                        break
                    if (
                        tc.name == "search_knowledge"
                        and retrieval_calls_count >= max_retrieval_calls
                    ):
                        messages.append(
                            CanonicalMessage(
                                role="tool",
                                tool_call_id=tc.call_id,
                                tool_name=tc.name,
                                content=json.dumps({"status": "retrieval_cap_reached"}),
                            )
                        )
                        continue

                    tool_calls_count += 1
                    if tc.name == "search_knowledge":
                        retrieval_calls_count += 1

                    result.tool_names_called.append(tc.name)
                    tool_output = await execute_read_tool(tc.name, tc.arguments)
                    messages.append(
                        CanonicalMessage(
                            role="tool",
                            tool_call_id=tc.call_id,
                            tool_name=tc.name,
                            content=json.dumps(tool_output, sort_keys=True),
                        )
                    )

                if tool_calls_count >= max_tool_calls:
                    if not result.tokens_emitted:
                        result.tokens_emitted.append(
                            "I reached the tool lookup limit for this turn. "
                            "Would you like me to connect you with property management staff?"
                        )
                    break

    except MidStreamProviderError:
        result.error_code = "PROVIDER_STREAM_INTERRUPTED"
    except TimeoutError:
        result.error_code = "TURN_TIMEOUT"
        if not result.tokens_emitted:
            result.tokens_emitted.append(
                "The request timed out before completion. Please retry or contact staff."
            )

    result.assistant_text = "".join(result.tokens_emitted)
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


def _accumulate_usage(target: TurnLoopResult, usage: UsageStats) -> None:
    target.provider = usage.provider
    target.model = usage.model
    target.input_tokens += usage.input_tokens
    target.output_tokens += usage.output_tokens
    target.cache_read_tokens += usage.cache_read_tokens
    target.reasoning_tokens += usage.reasoning_tokens
    target.cost_usd = round(target.cost_usd + usage.cost_usd, 8)
    target.failover = target.failover or usage.failover
