"""Spend guard with atomic pre-call reservations and post-call settlement (Architecture.md §7e)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_LUA_RESERVE_SPEND = """
local org_key = KEYS[1]
local user_key = KEYS[2]
local global_key = KEYS[3]

local reserve = tonumber(ARGV[1])
local org_cap = tonumber(ARGV[2])
local user_cap = tonumber(ARGV[3])
local global_cap = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local org_cur = tonumber(redis.call('GET', org_key) or '0')
local user_cur = tonumber(redis.call('GET', user_key) or '0')
local global_cur = tonumber(redis.call('GET', global_key) or '0')

if (org_cur + reserve > org_cap)
    or (user_cur + reserve > user_cap)
    or (global_cur + reserve > global_cap) then
    return {0, tostring(org_cur), tostring(user_cur), tostring(global_cur)}
end

local new_org = tonumber(redis.call('INCRBYFLOAT', org_key, reserve))
local new_user = tonumber(redis.call('INCRBYFLOAT', user_key, reserve))
local new_global = tonumber(redis.call('INCRBYFLOAT', global_key, reserve))

redis.call('EXPIRE', org_key, ttl)
redis.call('EXPIRE', user_key, ttl)
redis.call('EXPIRE', global_key, ttl)

return {1, tostring(new_org), tostring(new_user), tostring(new_global)}
"""


@dataclass(frozen=True, slots=True)
class SpendReservation:
    """Result of a pre-call spend reservation check."""

    allowed: bool
    degraded: bool
    reserved_usd: float
    org_id: UUID
    user_id: UUID
    day_bucket: str
    org_spent_usd: float
    reason: str = "ok"


class SpendGuard:
    """Atomic spend reservation and settlement guard (Architecture.md §7e, Phase 1).

    Reserves the maximum possible cost before each model call and settles to actual cost
    afterward so 100 parallel turns can never overshoot the cap.
    """

    def __init__(
        self,
        redis_client: Redis | None,
        *,
        default_org_daily_cap_usd: float = 25.0,
        default_user_daily_cap_usd: float = 2.50,
        global_daily_cap_usd: float = 250.0,
    ) -> None:
        self._redis = redis_client
        self.default_org_daily_cap_usd = default_org_daily_cap_usd
        self.default_user_daily_cap_usd = default_user_daily_cap_usd
        self.global_daily_cap_usd = global_daily_cap_usd
        self._local_lock = asyncio.Lock()
        self._local_totals: dict[str, float] = {}

    @staticmethod
    def current_day_bucket() -> str:
        """Return UTC YYYYMMDD bucket string."""
        return datetime.now(UTC).strftime("%Y%m%d")

    async def reserve(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        max_cost_usd: float,
        org_daily_cap_usd: float | None = None,
        user_daily_cap_usd: float | None = None,
    ) -> SpendReservation:
        """Atomically reserve `max_cost_usd` against org, user, and global daily caps."""
        day = self.current_day_bucket()
        org_cap = (
            org_daily_cap_usd if org_daily_cap_usd is not None else self.default_org_daily_cap_usd
        )
        user_cap = (
            user_daily_cap_usd
            if user_daily_cap_usd is not None
            else self.default_user_daily_cap_usd
        )
        global_cap = self.global_daily_cap_usd

        org_key = f"spend:{org_id}:{day}"
        user_key = f"spend:user:{org_id}:{user_id}:{day}"
        global_key = f"spend:global:{day}"

        if self._redis is not None:
            try:
                raw_res = await self._redis.eval(  # type: ignore[misc]
                    _LUA_RESERVE_SPEND,
                    3,
                    org_key,
                    user_key,
                    global_key,
                    str(max_cost_usd),
                    str(org_cap),
                    str(user_cap),
                    str(global_cap),
                    "172800",
                )
                allowed_flag = int(raw_res[0]) == 1
                org_spent = float(raw_res[1])
                degraded = (not allowed_flag) or (org_spent >= 0.8 * org_cap)
                return SpendReservation(
                    allowed=allowed_flag,
                    degraded=degraded,
                    reserved_usd=max_cost_usd if allowed_flag else 0.0,
                    org_id=org_id,
                    user_id=user_id,
                    day_bucket=day,
                    org_spent_usd=org_spent,
                    reason="ok" if allowed_flag else "cap_exceeded",
                )
            except Exception:
                logger.warning("Redis spend eval failed; falling back to in-memory spend lock")

        async with self._local_lock:
            org_cur = round(self._local_totals.get(org_key, 0.0), 6)
            user_cur = round(self._local_totals.get(user_key, 0.0), 6)
            global_cur = round(self._local_totals.get(global_key, 0.0), 6)
            if (
                round(org_cur + max_cost_usd, 6) > round(org_cap, 6)
                or round(user_cur + max_cost_usd, 6) > round(user_cap, 6)
                or round(global_cur + max_cost_usd, 6) > round(global_cap, 6)
            ):
                return SpendReservation(
                    allowed=False,
                    degraded=True,
                    reserved_usd=0.0,
                    org_id=org_id,
                    user_id=user_id,
                    day_bucket=day,
                    org_spent_usd=org_cur,
                    reason="cap_exceeded",
                )
            new_org = round(org_cur + max_cost_usd, 6)
            self._local_totals[org_key] = new_org
            self._local_totals[user_key] = round(user_cur + max_cost_usd, 6)
            self._local_totals[global_key] = round(global_cur + max_cost_usd, 6)
            return SpendReservation(
                allowed=True,
                degraded=new_org >= round(0.8 * org_cap, 6),
                reserved_usd=max_cost_usd,
                org_id=org_id,
                user_id=user_id,
                day_bucket=day,
                org_spent_usd=new_org,
                reason="ok",
            )

    async def settle(self, reservation: SpendReservation, actual_cost_usd: float) -> float:
        """Adjust reserved spend to `actual_cost_usd` after the model call finishes."""
        if not reservation.allowed or reservation.reserved_usd <= 0.0:
            return 0.0
        delta = round(actual_cost_usd - reservation.reserved_usd, 8)
        if abs(delta) < 1e-9:
            return reservation.org_spent_usd

        org_key = f"spend:{reservation.org_id}:{reservation.day_bucket}"
        user_key = f"spend:user:{reservation.org_id}:{reservation.user_id}:{reservation.day_bucket}"
        global_key = f"spend:global:{reservation.day_bucket}"

        if self._redis is not None:
            try:
                pipe = self._redis.pipeline(transaction=True)
                pipe.incrbyfloat(org_key, delta)
                pipe.incrbyfloat(user_key, delta)
                pipe.incrbyfloat(global_key, delta)
                res = await pipe.execute()
                return float(res[0])
            except Exception:
                logger.warning("Redis spend settle failed; updating local fallback")

        async with self._local_lock:
            self._local_totals[org_key] = max(0.0, self._local_totals.get(org_key, 0.0) + delta)
            self._local_totals[user_key] = max(0.0, self._local_totals.get(user_key, 0.0) + delta)
            self._local_totals[global_key] = max(
                0.0, self._local_totals.get(global_key, 0.0) + delta
            )
            return self._local_totals[org_key]

    async def get_org_spend_today(self, org_id: UUID) -> float:
        """Return current daily USD spend for `org_id`."""
        day = self.current_day_bucket()
        org_key = f"spend:{org_id}:{day}"
        if self._redis is not None:
            try:
                val = await self._redis.get(org_key)
                if val is not None:
                    return float(val)
            except Exception:
                logger.debug("Fallback to in-memory spend read")
        return self._local_totals.get(org_key, 0.0)
