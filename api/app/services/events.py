"""Transactional outbox for workspace events.

Services call :func:`emit` while their transaction is open and :func:`commit`
instead of ``db.commit()``. Together they guarantee:

- **No phantom events.** The outbox row (and, on Postgres, the ``pg_notify``)
  is part of the change's own transaction; a rollback discards both.
- **No lost events.** Postgres delivers the notification as part of commit, so
  there is no window between "committed" and "published" for a crash to fall
  into. (The in-process bus publishes right after commit; it is single-process
  by definition, so there is no other instance to miss it.)
- **Replay.** Each persisted event gets a sequence number (the outbox ``id``),
  sent to clients as ``seq``. A reconnecting client passes ``?since=<seq>`` and
  :func:`events_since` replays what it missed.

Ordering caveat: ``seq`` is assigned at insert and transactions can commit out of
order, so a slow transaction can commit ``seq=N`` after ``N+1`` was delivered.
Live delivery still sees both; only a client that disconnects in exactly that
window and resumes from ``N+1`` could miss ``N``. The dashboard's periodic
snapshot covers that rare case.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.settings import settings
from app.models.models import Event, Workspace
from app.services.event_bus import NOTIFY_CHANNEL, get_event_bus, notify_payload
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("context_hub.events")

_PENDING_KEY = "erid_pending_events"

# Upper bound on a single replay. A client further behind than this is told to
# resync from a fresh snapshot instead of streaming an unbounded backlog.
REPLAY_LIMIT = 500


def _envelope(slug: str, event_type: str, data: dict[str, Any], seq: int | None, ts: datetime) -> dict[str, Any]:
    envelope: dict[str, Any] = {"workspace": slug, "type": event_type, "data": data, "ts": ts.isoformat()}
    if seq is not None:
        envelope["seq"] = seq
    return envelope


async def emit(
    db: AsyncSession,
    workspace: Workspace,
    event_type: str,
    data: dict[str, Any],
    *,
    persist: bool = True,
) -> None:
    """Record an event as part of the caller's open transaction.

    ``persist=False`` is for ephemeral events (presence heartbeats, a deleted
    workspace) that are not worth replaying: they are delivered live only.
    """
    now = datetime.now(UTC)
    seq: int | None = None
    if persist:
        row = Event(workspace_id=workspace.id, type=event_type, data=data, created_at=now)
        db.add(row)
        await db.flush()
        seq = row.id
    envelope = _envelope(workspace.slug, event_type, data, seq, now)

    bus = await get_event_bus()
    if bus.transactional and db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": NOTIFY_CHANNEL, "payload": notify_payload(envelope)},
        )
    else:
        db.info.setdefault(_PENDING_KEY, []).append(envelope)


async def commit(db: AsyncSession) -> None:
    """Commit the session, then publish any events that weren't sent in-transaction."""
    try:
        await db.commit()
    except BaseException:
        db.info.pop(_PENDING_KEY, None)
        raise
    pending = db.info.pop(_PENDING_KEY, [])
    if not pending:
        return
    bus = await get_event_bus()
    for envelope in pending:
        slug = envelope["workspace"]
        await bus.publish(slug, {k: v for k, v in envelope.items() if k != "workspace"})


async def events_since(db: AsyncSession, workspace: Workspace, since: int) -> tuple[list[dict[str, Any]], bool]:
    """Return ``(events after since, complete)`` for a reconnecting client.

    ``complete`` is ``False`` when the client must resync from a snapshot
    instead: the backlog exceeds :data:`REPLAY_LIMIT`, or events after ``since``
    may already have been pruned from the outbox.
    """
    oldest, newest = (await db.execute(select(func.min(Event.id), func.max(Event.id)))).one()
    if newest is None:
        # Empty outbox: fine for a client that never saw an event, otherwise
        # whatever followed its ``since`` may have been pruned.
        return [], since <= 0
    if since >= newest:
        return [], True
    if since < oldest - 1:
        # The window starts before the oldest retained row (ids are global, so
        # this means rows after ``since`` may already have been pruned).
        return [], False
    rows = (
        (
            await db.execute(
                select(Event)
                .where(Event.workspace_id == workspace.id, Event.id > since)
                .order_by(Event.id)
                .limit(REPLAY_LIMIT + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) > REPLAY_LIMIT:
        return [], False
    return [_envelope(workspace.slug, r.type, r.data, r.id, r.created_at) for r in rows], True


async def load_envelope(slug: str, seq: int) -> dict[str, Any] | None:
    """Load one outbox row as an envelope (for oversize ``pg_notify`` references)."""
    from app.db import session as db_session

    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Event, seq)
        if row is None:
            return None
        return _envelope(slug, row.type, row.data, row.id, row.created_at)


async def prune_events(db: AsyncSession) -> int:
    """Delete outbox rows older than the retention window; return how many."""
    cutoff = datetime.now(UTC) - timedelta(hours=settings.event_retention_hours)
    result = await db.execute(delete(Event).where(Event.created_at < cutoff))
    await db.commit()
    return result.rowcount or 0
