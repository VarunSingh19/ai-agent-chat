"""Phase 2 tests: 3-provider gateway (Anthropic, OpenAI, Google Gemini), failover, mid-stream
abort, and cache prefix.
"""

from __future__ import annotations

import pytest

from pdagent.agent.canonical import CanonicalMessage, TurnConfig
from pdagent.agent.context import CACHE_BREAKPOINT_MARKER, RetrievedChunkItem, build_prompt_bundle
from pdagent.agent.providers.base import (
    MidStreamProviderError,
    ProviderGateway,
    load_model_catalog,
)
from pdagent.agent.providers.fake import FakeLLMProvider
from pdagent.tools.schemas import ALL_TOOL_SPECS


async def test_three_provider_failover_anthropic_to_openai_to_gemini() -> None:
    """Architecture.md §7f & D-020: Failover across Anthropic ▸
    OpenAI ▸ Gemini before first token."""
    catalog = load_model_catalog()
    fake_anthropic = FakeLLMProvider(provider_name="anthropic", fail_before_first_token=True)
    fake_openai = FakeLLMProvider(provider_name="openai", fail_before_first_token=True)
    fake_gemini = FakeLLMProvider(
        provider_name="gemini",
        fail_before_first_token=False,
        canned_text="Answered cleanly by Google Gemini fallback.",
    )

    gateway = ProviderGateway(
        providers={
            "anthropic": fake_anthropic,
            "openai": fake_openai,
            "gemini": fake_gemini,
        },
        catalog=catalog,
    )
    prompt = build_prompt_bundle(
        tools=(ALL_TOOL_SPECS["get_balance"],),
        tone="professional",
        enabled_tools=["get_balance"],
        rolling_summary="",
        retrieved_chunks=[],
        user_message="What is my balance?",
    )
    tokens: list[str] = []
    final_provider = ""
    failover_flag = False

    async for evt in gateway.stream_with_failover(
        prompt,
        [CanonicalMessage(role="user", content="What is my balance?")],
        TurnConfig(route="small"),
    ):
        if evt.kind == "token":
            tokens.append(evt.text)
        elif evt.kind == "usage" and evt.usage is not None:
            final_provider = evt.usage.provider
            failover_flag = evt.usage.failover
            assert evt.usage.model == "gemini-3.8-flash"
            assert evt.usage.cost_usd > 0.0

    assert "".join(tokens) == "Answered cleanly by Google Gemini fallback."
    assert final_provider == "gemini"
    assert failover_flag is True
    # Each failing provider retried once (2 attempts each), then Gemini succeeded on attempt 1
    assert fake_anthropic.call_count == 2
    assert fake_openai.call_count == 2
    assert fake_gemini.call_count == 1


async def test_mid_stream_provider_failure_never_splices_from_fallback() -> None:
    """Architecture.md §7f: Failure after the first token raises MidStreamProviderError and never
    splices.
    """
    catalog = load_model_catalog()
    fake_anthropic = FakeLLMProvider(
        provider_name="anthropic",
        fail_after_first_token=True,
        canned_text="FirstSecondThird",
    )
    fake_openai = FakeLLMProvider(
        provider_name="openai",
        canned_text="Should never be called",
    )
    gateway = ProviderGateway(
        providers={"anthropic": fake_anthropic, "openai": fake_openai},
        catalog=catalog,
    )
    prompt = build_prompt_bundle(
        tools=(),
        tone="professional",
        enabled_tools=[],
        rolling_summary="",
        retrieved_chunks=[],
        user_message="Hello",
    )

    with pytest.raises(MidStreamProviderError):
        async for _evt in gateway.stream_with_failover(
            prompt,
            [CanonicalMessage(role="user", content="Hello")],
            TurnConfig(route="small"),
        ):
            pass

    assert fake_openai.call_count == 0


def test_prompt_cache_breakpoint_forbids_per_request_values_in_static_prefix() -> None:
    """Rules.md §1 Rule 5: No per-request value (org_id, user_id, chunks, user message) appears
    before breakpoint.
    """
    chunk = RetrievedChunkItem(
        document_id="doc-999",
        title="Pool Rules",
        heading_path="Hours",
        content="Pool closes at 9 PM.",
    )
    bundle = build_prompt_bundle(
        tools=(ALL_TOOL_SPECS["search_knowledge"],),
        tone="friendly",
        enabled_tools=["search_knowledge"],
        rolling_summary="User asked about pool.",
        retrieved_chunks=[chunk],
        user_message="Can I swim at 10 PM?",
        forbidden_before_breakpoint=("doc-999", "Can I swim at 10 PM?", "org-secret-123"),
    )
    assert bundle.static_prefix.endswith(CACHE_BREAKPOINT_MARKER)
    assert "doc-999" not in bundle.static_prefix
    assert "Can I swim at 10 PM?" not in bundle.static_prefix
    assert '<retrieved_chunk document_id="doc-999"' in bundle.dynamic_suffix
    assert '<user_message trust="data">Can I swim at 10 PM?</user_message>' in bundle.dynamic_suffix
