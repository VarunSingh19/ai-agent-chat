"""Per-provider circuit breaker (Architecture.md §7f)."""

from __future__ import annotations

import time
from collections import deque
from typing import Literal

BreakerState = Literal["closed", "open", "half_open"]


class ProviderCircuitBreaker:
    """Circuit breaker opening after 5 failures in 60 s and half-opening after 30 s."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        window_seconds: float = 60.0,
        recovery_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.recovery_seconds = recovery_seconds
        self._failures: dict[str, deque[float]] = {}
        self._opened_at: dict[str, float] = {}

    def state(self, provider: str, now: float | None = None) -> BreakerState:
        """Return current state (`closed`, `open`, or `half_open`) for `provider`."""
        ts = now if now is not None else time.monotonic()
        opened_at = self._opened_at.get(provider)
        if opened_at is not None:
            if ts - opened_at >= self.recovery_seconds:
                return "half_open"
            return "open"
        return "closed"

    def allow_request(self, provider: str, now: float | None = None) -> bool:
        """Return True if a call to `provider` is permitted right now."""
        return self.state(provider, now=now) in ("closed", "half_open")

    def record_success(self, provider: str) -> None:
        """Reset failure history and close the breaker for `provider`."""
        self._failures.pop(provider, None)
        self._opened_at.pop(provider, None)

    def record_failure(self, provider: str, now: float | None = None) -> BreakerState:
        """Record a provider failure and open the breaker if threshold is reached."""
        ts = now if now is not None else time.monotonic()
        if self.state(provider, now=ts) == "half_open":
            self._opened_at[provider] = ts
            return "open"

        q = self._failures.setdefault(provider, deque())
        cutoff = ts - self.window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        q.append(ts)

        if len(q) >= self.failure_threshold:
            self._opened_at[provider] = ts
            return "open"
        return "closed"
