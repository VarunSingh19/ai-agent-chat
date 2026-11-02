"""Redis sliding-window rate limiter (Architecture.md §7e, Rules.md §3)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from uuid import UUID

from pdagent.core.errors import AppError, ErrorCode
from pdagent.core.ids import new_id

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Default limits (Architecture.md §7e):
    - Per user: 20 messages / 300 seconds
    - Per org: 600 messages / 300 seconds
    - Per IP (unauthenticated webhooks): 30 requests / 60 seconds
    """

    def __init__(
        self,
        redis_client: Redis | None,
        *,
        user_limit: int = 20,
        user_window_s: int = 300,
        org_limit: int = 600,
        org_window_s: int = 300,
    ) -> None:
        self._redis = redis_client
        self.user_limit = user_limit
        self.user_window_s = user_window_s
        self.org_limit = org_limit
        self.org_window_s = org_window_s

    async def check_user_and_org(self, org_id: UUID, user_id: UUID) -> None:
        """Enforce both per-user and per-org sliding-window message limits."""
        if self._redis is None:
            return
        await self._check_bucket(
            key=f"rl:user:{org_id}:{user_id}",
            limit=self.user_limit,
            window_s=self.user_window_s,
        )
        await self._check_bucket(
            key=f"rl:org:{org_id}",
            limit=self.org_limit,
            window_s=self.org_window_s,
        )

    async def check_ip(self, ip_hash: str, limit: int = 30, window_s: int = 60) -> None:
        """Enforce sliding-window limit for unauthenticated webhook IP hash."""
        if self._redis is None:
            return
        await self._check_bucket(key=f"rl:ip:{ip_hash}", limit=limit, window_s=window_s)

    async def _check_bucket(self, *, key: str, limit: int, window_s: int) -> None:
        if self._redis is None:
            return
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - (window_s * 1000)
        member = f"{now_ms}:{new_id()}"
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.zremrangebyscore(key, 0, cutoff_ms)
            pipe.zcard(key)
            pipe.zadd(key, {member: float(now_ms)})
            pipe.expire(key, window_s + 5)
            results = await pipe.execute()
            current_count = int(results[1])
        except Exception:
            logger.warning("Rate limiter Redis check failed; failing open to preserve availability")
            return

        if current_count >= limit:
            try:
                await self._redis.zrem(key, member)
            except Exception:
                logger.debug("Rate limiter rollback zrem skipped")
            raise AppError(
                code=ErrorCode.RATE_LIMITED,
                title="Rate Limit Exceeded",
                detail=f"Rate limit exceeded. Try again in {window_s} seconds.",
                status_code=429,
                headers={"Retry-After": str(window_s)},
            )
