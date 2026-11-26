"""File claims: advisory leases agents take before editing paths.

An agent about to touch ``api/auth.py`` claims it; another agent (or a human)
that tries to claim an overlapping path is told who holds it, why, and until
when. Claims are advisory: they coordinate, they don't block writes. A
pre-commit hook can call ``check`` to warn before committing files someone
else has claimed.

Paths are repo-relative and may be globs: ``src/auth/login.py``, a directory
``src/auth/`` (covers everything under it), or patterns like ``src/**/*.py``.
Overlap detection is exact for files and directories and for a path against
a glob. Between two globs it is best-effort: it errs towards reporting a
conflict for patterns that share a directory and match each other.

Concurrent claims on Postgres are serialized per workspace with a
transaction-level advisory lock, so two agents can't both win the same path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase

from app.core.security import Principal
from app.models.models import FileClaim, Permission
from app.schemas.schemas import (
    ClaimCheck,
    ClaimCheckIn,
    ClaimConflict,
    ClaimIn,
    ClaimOut,
    ClaimResult,
    ReleaseIn,
    ReleaseResult,
)
from app.services import events
from app.services.context import _require_task_in_workspace, author, scrub
from app.services.errors import Forbidden, NotFound, Unprocessable
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

_GLOB_CHARS = "*?["


def normalize_path(raw: str) -> str:
    """Canonical repo-relative form; raise :class:`Unprocessable` if unusable."""
    path = (raw or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    while "//" in path:
        path = path.replace("//", "/")
    if not path or path in (".", "/"):
        raise Unprocessable("empty path")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise Unprocessable(f"path must be relative to the repository root: {raw!r}")
    if "\x00" in path or len(path) > 512:
        raise Unprocessable(f"invalid path: {raw[:80]!r}")
    if ".." in path.split("/"):
        raise Unprocessable(f"path may not contain '..': {raw!r}")
    if path.endswith("/"):
        path += "**"  # a directory claim covers everything under it
    return path


def _is_glob(path: str) -> bool:
    return any(c in path for c in _GLOB_CHARS)


def _literal_prefix(path: str) -> str:
    cut = min((path.index(c) for c in _GLOB_CHARS if c in path), default=len(path))
    return path[:cut]


def overlaps(a: str, b: str) -> bool:
    """Whether two normalized claim paths could name a common file."""
    if a == b:
        return True
    a_glob, b_glob = _is_glob(a), _is_glob(b)
    if not a_glob and not b_glob:
        # A plain path also covers what's under it if it's a directory.
        return b.startswith(a + "/") or a.startswith(b + "/")
    # fnmatch's "*" crosses "/", so "**" behaves like "*" here (deliberately broad).
    if fnmatchcase(a, b) or fnmatchcase(b, a):
        return True
    if not a_glob:
        return _literal_prefix(b).startswith(a + "/")
    if not b_glob:
        return _literal_prefix(a).startswith(b + "/")
    return False


def _unique(paths: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for p in paths:
        seen.setdefault(normalize_path(p), None)
    return list(seen)


async def _lock_workspace(db: AsyncSession, principal: Principal) -> None:
    """Serialize claim changes in one workspace (Postgres; SQLite serializes writes)."""
    if db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"erid-claims:{principal.workspace.id}"}
        )


async def _active(db: AsyncSession, principal: Principal, now: datetime) -> list[FileClaim]:
    stmt = (
        select(FileClaim)
        .where(
            FileClaim.workspace_id == principal.workspace.id,
            FileClaim.released_at.is_(None),
            FileClaim.expires_at > now,
        )
        .order_by(FileClaim.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


def _out(claims: list[FileClaim]) -> list[ClaimOut]:
    return [ClaimOut.model_validate(c) for c in claims]


async def claim(db: AsyncSession, principal: Principal, payload: ClaimIn) -> ClaimResult:
    """Grant every path that doesn't conflict; report the ones that do.

    A path conflicts when someone else holds an overlapping claim and either
    side is exclusive. Claiming a path you already hold renews it with the new
    TTL, mode and reason.
    """
    paths = _unique(payload.paths)
    payload = await scrub(db, principal, payload, ("reason",), widths={"reason": 1000})
    await _require_task_in_workspace(db, principal, payload.task_id)
    holder = author(principal, payload.holder)
    await _lock_workspace(db, principal)
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=payload.ttl_seconds)
    active = await _active(db, principal, now)

    granted: list[FileClaim] = []
    conflicts: list[ClaimConflict] = []
    for path in paths:
        blocking = [
            c for c in active if c.holder != holder and overlaps(path, c.path) and (c.exclusive or payload.exclusive)
        ]
        if blocking:
            conflicts.append(ClaimConflict(path=path, held_by=_out(blocking)))
            continue
        mine = next((c for c in active if c.holder == holder and c.path == path), None)
        if mine is None:
            mine = FileClaim(workspace_id=principal.workspace.id, path=path, holder=holder)
            db.add(mine)
            active.append(mine)
        mine.exclusive = payload.exclusive
        mine.reason = payload.reason
        mine.task_id = payload.task_id
        mine.expires_at = expires
        granted.append(mine)

    await db.flush()
    for c in granted:
        await db.refresh(c)
    result = ClaimResult(ok=not conflicts, granted=_out(granted), conflicts=conflicts)
    if granted:
        await events.emit(
            db,
            principal.workspace,
            "files_claimed",
            {"holder": holder, "claims": [c.model_dump(mode="json") for c in result.granted]},
        )
    await events.commit(db)
    return result


async def list_claims(db: AsyncSession, principal: Principal, path: str | None = None) -> list[ClaimOut]:
    active = await _active(db, principal, datetime.now(UTC))
    if path:
        wanted = normalize_path(path)
        active = [c for c in active if overlaps(wanted, c.path)]
    return _out(active)


async def check(db: AsyncSession, principal: Principal, payload: ClaimCheckIn) -> list[ClaimCheck]:
    """Who claims each path, without claiming anything (for hooks and agents)."""
    paths = _unique(payload.paths)
    me = author(principal, payload.holder)
    active = await _active(db, principal, datetime.now(UTC))
    out = []
    for path in paths:
        covering = [c for c in active if overlaps(path, c.path)]
        out.append(
            ClaimCheck(
                path=path,
                claimed_by_others=any(c.holder != me for c in covering),
                claims=_out(covering),
            )
        )
    return out


def _may_release(principal: Principal, claim_row: FileClaim, me: str | None) -> bool:
    return claim_row.holder == me or principal.has(Permission.admin_keys)


async def _release_rows(db: AsyncSession, principal: Principal, rows: list[FileClaim]) -> ReleaseResult:
    now = datetime.now(UTC)
    for row in rows:
        row.released_at = now
    released = [r.id for r in rows]
    if released:
        await events.emit(db, principal.workspace, "files_released", {"claim_ids": [str(i) for i in released]})
    await events.commit(db)
    return ReleaseResult(released=released)


async def release(db: AsyncSession, principal: Principal, payload: ReleaseIn) -> ReleaseResult:
    """Release the caller's active claims on ``paths`` (all of them if omitted)."""
    me = author(principal, payload.holder)
    await _lock_workspace(db, principal)
    mine = [c for c in await _active(db, principal, datetime.now(UTC)) if c.holder == me]
    if payload.paths is not None:
        wanted = set(_unique(payload.paths))
        mine = [c for c in mine if c.path in wanted]
    return await _release_rows(db, principal, mine)


async def release_one(db: AsyncSession, principal: Principal, claim_id: uuid.UUID) -> ReleaseResult:
    """Release one claim: your own, or anyone's with admin rights."""
    await _lock_workspace(db, principal)
    row = (
        (
            await db.execute(
                select(FileClaim).where(FileClaim.id == claim_id, FileClaim.workspace_id == principal.workspace.id)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise NotFound(f"claim '{claim_id}' not found")
    if row.released_at is not None:
        return ReleaseResult(released=[])
    if not _may_release(principal, row, author(principal, None)):
        raise Forbidden(f"claim is held by '{row.holder}'; only they or an admin can release it")
    return await _release_rows(db, principal, [row])


async def count_active(db: AsyncSession, principal: Principal) -> int:
    stmt = (
        select(func.count())
        .select_from(FileClaim)
        .where(
            FileClaim.workspace_id == principal.workspace.id,
            FileClaim.released_at.is_(None),
            FileClaim.expires_at > datetime.now(UTC),
        )
    )
    return (await db.execute(stmt)).scalar_one()


async def prune(db: AsyncSession, keep: timedelta = timedelta(days=7)) -> int:
    """Delete claims that expired or were released more than ``keep`` ago."""
    cutoff = datetime.now(UTC) - keep
    result = await db.execute(
        delete(FileClaim).where(or_(FileClaim.expires_at < cutoff, FileClaim.released_at < cutoff))
    )
    await db.commit()
    return result.rowcount or 0
