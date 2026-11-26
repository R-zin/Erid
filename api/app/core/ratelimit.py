"""Rate limiting: shared limits for auth-sensitive routes, local ones for the rest.

Two limiters, picked per use:

* :class:`SharedLimiter` keeps fixed-window counters in Postgres (the
  ``rate_limits`` table) via an atomic upsert, so a limit holds across every
  API replica. It guards the endpoints an attacker would hammer: key->token
  login, workspace provisioning and claiming, OAuth, and repeated failed
  credentials from one client. Those are low-volume, so a database round trip
  per request is cheap.
* :class:`LocalLimiter` counts in process memory. It guards general API
  traffic per credential, where a database write per request would be the
  bottleneck. Each replica enforces it separately, so the cluster-wide ceiling
  is roughly ``replicas x limit``.

Limits are ``"<count>/<second|minute|hour>"`` strings from settings; a count
of 0 disables that limit. Over the limit, callers get 429 with ``Retry-After``.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import RATE_LIMITED
from app.core.settings import settings
from app.models.models import RateLimitCounter

_PERIODS = {"second": 1, "sec": 1, "s": 1, "minute": 60, "min": 60, "m": 60, "hour": 3600, "h": 3600}


@dataclass(frozen=True)
class Limit:
    count: int
    period: int  # seconds

    @classmethod
    def parse(cls, spec: str) -> Limit:
        """Parse ``"10/minute"``; ``"0/minute"`` (or empty) disables the limit."""
        spec = (spec or "").strip()
        if not spec:
            return cls(0, 60)
        count, _, unit = spec.partition("/")
        period = _PERIODS.get(unit.strip().lower())
        if period is None:
            raise ValueError(f"bad rate limit {spec!r}: expected '<count>/<second|minute|hour>'")
        return cls(int(count), period)

    @property
    def enabled(self) -> bool:
        return self.count > 0


def client_ip(request: Request | None) -> str:
    """The caller's address. Behind a proxy this is the forwarded client address,
    but only when uvicorn trusts the proxy (FORWARDED_ALLOW_IPS)."""
    if request is None or request.client is None:
        return "unknown"
    return request.client.host


def credential_fingerprint(*parts: str | None) -> str | None:
    """A short hash identifying a presented credential without storing it."""
    material = "|".join(p for p in parts if p)
    if not material:
        return None
    return hashlib.sha256(material.encode()).hexdigest()[:24]


def _too_many(scope: str, retry_after: int) -> HTTPException:
    RATE_LIMITED.labels(scope).inc()
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"rate limit exceeded ({scope}); retry in {retry_after}s",
        headers={"Retry-After": str(retry_after)},
    )


def _window(limit: Limit, now: float) -> tuple[int, int]:
    """(window start as epoch seconds, seconds until the next window)."""
    start = int(now // limit.period) * limit.period
    return start, max(1, start + limit.period - int(now))


class SharedLimiter:
    """Fixed-window counters in the database, shared by all replicas."""

    async def hit(self, db: AsyncSession, scope: str, key: str, limit: Limit, *, amount: int = 1) -> int:
        """Count ``amount`` against ``key``; return the window's new total."""
        start, _ = _window(limit, time.time())
        window = datetime.fromtimestamp(start, UTC)
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        stmt = insert(RateLimitCounter).values(key=f"{scope}:{key}"[:256], window_start=window, count=amount)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key", "window_start"],
            set_={"count": RateLimitCounter.count + stmt.excluded.count},
        ).returning(RateLimitCounter.count)
        total = (await db.execute(stmt)).scalar_one()
        await db.commit()
        return total

    async def peek(self, db: AsyncSession, scope: str, key: str, limit: Limit) -> int:
        start, _ = _window(limit, time.time())
        row = await db.get(RateLimitCounter, (f"{scope}:{key}"[:256], datetime.fromtimestamp(start, UTC)))
        return row.count if row else 0

    async def check(self, db: AsyncSession, scope: str, key: str, limit: Limit) -> None:
        """Count one request and raise 429 once the window's limit is exceeded."""
        if not limit.enabled:
            return
        total = await self.hit(db, scope, key, limit)
        if total > limit.count:
            raise _too_many(scope, _window(limit, time.time())[1])

    async def prune(self, db: AsyncSession, older_than: timedelta = timedelta(hours=2)) -> int:
        cutoff = datetime.now(UTC) - older_than
        result = await db.execute(delete(RateLimitCounter).where(RateLimitCounter.window_start < cutoff))
        await db.commit()
        return result.rowcount or 0


class LocalLimiter:
    """Fixed-window counters in process memory (per replica)."""

    def __init__(self, max_keys: int = 100_000) -> None:
        self._counts: dict[str, tuple[int, int]] = {}
        self._max_keys = max_keys

    def check(self, scope: str, key: str, limit: Limit) -> None:
        if not limit.enabled:
            return
        start, retry_after = _window(limit, time.time())
        full_key = f"{scope}:{key}"
        window, count = self._counts.get(full_key, (start, 0))
        if window != start:
            window, count = start, 0
        count += 1
        if len(self._counts) >= self._max_keys and full_key not in self._counts:
            self._evict(start)
        self._counts[full_key] = (window, count)
        if count > limit.count:
            raise _too_many(scope, retry_after)

    def _evict(self, current_window: int) -> None:
        """Drop counters from past windows; if still full, start over (fail open)."""
        self._counts = {k: v for k, v in self._counts.items() if v[0] == current_window}
        if len(self._counts) >= self._max_keys:
            self._counts.clear()

    def reset(self) -> None:
        self._counts.clear()


shared = SharedLimiter()
local = LocalLimiter()


def limits() -> dict[str, Limit]:
    """The configured limits, parsed (settings can change in tests)."""
    return {
        "auth": Limit.parse(settings.rate_limit_auth),
        "auth_failures": Limit.parse(settings.rate_limit_auth_failures),
        "api": Limit.parse(settings.rate_limit_api),
    }


async def enforce_auth_limit(db: AsyncSession, request: Request) -> None:
    """Shared per-client-IP limit for login, provisioning, claiming and OAuth."""
    if settings.rate_limits_enabled:
        await shared.check(db, "auth", client_ip(request), limits()["auth"])


# Clients locked out for failing authentication, per replica: ip -> unblock time.
# Failures are counted in the shared table (only failures pay a database
# write); a client over the limit is then refused here without touching the
# database. Other replicas learn on that client's next failure there, so the
# cluster-wide ceiling is the limit plus one attempt per replica.
_blocked: dict[str, float] = {}


def reject_if_locked_out(ip: str) -> None:
    """429 for a client that recently failed authentication too often."""
    until = _blocked.get(ip)
    if until is None:
        return
    remaining = until - time.time()
    if remaining <= 0:
        _blocked.pop(ip, None)
        return
    raise _too_many("auth_failures", max(1, int(remaining)))


async def record_auth_failure(db: AsyncSession, ip: str) -> None:
    """Count a rejected credential; lock the client out once over the limit."""
    from app.core.observability import AUTH_FAILURES

    AUTH_FAILURES.inc()
    limit = limits()["auth_failures"]
    if not (settings.rate_limits_enabled and limit.enabled):
        return
    total = await shared.hit(db, "auth_failures", ip, limit)
    if total >= limit.count:
        start, retry_after = _window(limit, time.time())
        _blocked[ip] = start + limit.period
        if len(_blocked) > 100_000:  # bound memory under a distributed attack
            now = time.time()
            for k in [k for k, v in _blocked.items() if v <= now]:
                _blocked.pop(k, None)


def reset_local_state() -> None:
    """Forget per-replica counters and lockouts (tests)."""
    local.reset()
    _blocked.clear()


def enforce_api_limit(slug: str, caller: str) -> None:
    """Per-replica limit on general API traffic, per workspace + caller."""
    if settings.rate_limits_enabled:
        local.check("api", f"{slug}:{caller}", limits()["api"])


async def auth_rate_limit(request: Request) -> None:
    """Route dependency: the shared per-IP limit for auth-sensitive endpoints.

    Uses its own short session so its commit can't interfere with the route's.
    """
    if not settings.rate_limits_enabled:
        return
    from app.db.session import get_db

    factory = request.app.dependency_overrides.get(get_db, get_db)
    gen = factory()
    db = await anext(gen)
    try:
        await enforce_auth_limit(db, request)
    finally:
        await gen.aclose()
