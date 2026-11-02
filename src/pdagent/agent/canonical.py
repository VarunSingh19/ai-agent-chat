"""Provider-neutral message, tool, usage, and stream event types (Architecture.md §3, §7f)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RouteSlot = Literal["small", "large", "triage"]
ProviderName = Literal["anthropic", "openai", "gemini", "fake"]
EventType = Literal["token", "tool_call", "usage", "error"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Provider-neutral tool schema exposed to a model."""

    name: str
    description: str
    parameters: dict[str, object]
    is_write: bool = False


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool invocation requested by the model."""

    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    """Provider-neutral conversation turn or tool result."""

    role: Literal["user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class PromptBundle:
    """Assembled prompt split strictly at the prompt-cache breakpoint (Rules.md §1 Rule 5)."""

    static_prefix: str
    dynamic_suffix: str
    tools: tuple[ToolSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class TurnConfig:
    """Configuration for a single model invocation."""

    route: RouteSlot
    max_output_tokens: int = 400
    effort: Literal["low", "medium", "high"] = "medium"


@dataclass(frozen=True, slots=True)
class UsageStats:
    """Token counts and calculated cost for a model call."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    failover: bool = False


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """Canonical event yielded by `LLMProvider.stream()`."""

    kind: EventType
    text: str = ""
    tool_call: ToolCall | None = None
    usage: UsageStats | None = None
    error_code: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
