"""Workspace context services: tasks, decisions, handoffs, presence, search, summary.

Every function takes an open ``AsyncSession`` and the caller's resolved
:class:`~app.core.security.Principal` (authorization has already happened at the
edge, in ``require_action`` for REST or the MCP auth hook), does its work in one
transaction, records the matching event in the outbox, and returns an API schema
object. The REST routes and the in-process MCP endpoint are thin adapters over
these, so both share one implementation of each operation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import Principal, PrincipalKind
from app.models.models import Decision, Handoff, HandoffStatus, Presence, Task, TaskStatus
from app.schemas.schemas import (
    DecisionIn,
    DecisionOut,
    HandoffIn,
    HandoffOut,
    PresenceIn,
    PresenceOut,
    SearchResults,
    TaskIn,
    TaskOut,
    TaskUpdate,
    WorkspaceSummary,
)
from app.services import events
from app.services.errors import Conflict, NotFound
from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

# A presence record is considered active if seen within this window.
STALE_AFTER = timedelta(minutes=10)


def author(principal: Principal, claimed: str | None) -> str | None:
    """Who to record as the author of a write.

    A per-actor credential (actor key, or a JWT minted from one) *is* an
    identity, so its name wins and a client-supplied ``created_by``/``made_by``
    is ignored: an actor can't attribute its writes to someone else. Shared
    credentials (the legacy workspace key, an open workspace) identify nobody in
    particular, so the caller's claim is kept, falling back to the principal's
    name and then the workspace slug.
    """
    if principal.kind == PrincipalKind.actor and principal.actor_name:
        return principal.actor_name
    return claimed or principal.actor_name or principal.workspace.slug


def _search_vector(model: type) -> ColumnElement:
    """Reference the generated ``search_vector`` tsvector column on a model's table.

    The column exists only in Postgres (added by the FTS migration) and is not
    ORM-mapped. It is referenced as a free-standing typed column expression rather
    than appended to the shared ``Table``: mutating the metadata at query time made
    every later ``create_all`` (e.g. on SQLite) try to render a TSVECTOR column.
    """
    return literal_column(f"{model.__tablename__}.search_vector", type_=TSVECTOR)


def _dump(model) -> dict:
    return model.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


async def _get_task(db: AsyncSession, principal: Principal, task_id: uuid.UUID) -> Task:
    task = (
        (await db.execute(select(Task).where(Task.id == task_id, Task.workspace_id == principal.workspace.id)))
        .scalars()
        .first()
    )
    if task is None:
        raise NotFound(f"task '{task_id}' not found")
    return task


async def _require_task_in_workspace(db: AsyncSession, principal: Principal, task_id: uuid.UUID | None) -> None:
    if task_id is None:
        return
    try:
        await _get_task(db, principal, task_id)
    except NotFound:
        raise NotFound(f"task '{task_id}' not found in workspace") from None


async def list_tasks(db: AsyncSession, principal: Principal, status: TaskStatus | None = None) -> list[TaskOut]:
    stmt = select(Task).where(Task.workspace_id == principal.workspace.id).order_by(Task.created_at)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    return [TaskOut.model_validate(t) for t in (await db.execute(stmt)).scalars().all()]


async def create_task(db: AsyncSession, principal: Principal, payload: TaskIn) -> TaskOut:
    task = Task(
        workspace_id=principal.workspace.id,
        title=payload.title,
        assigned_to=payload.assigned_to,
        created_by=author(principal, payload.created_by),
        status=payload.status,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    out = TaskOut.model_validate(task)
    await events.emit(db, principal.workspace, "task_created", _dump(out))
    await events.commit(db)
    return out


async def update_task(db: AsyncSession, principal: Principal, task_id: uuid.UUID, payload: TaskUpdate) -> TaskOut:
    task = await _get_task(db, principal, task_id)
    if payload.title is not None:
        task.title = payload.title
    if payload.status is not None:
        task.status = payload.status
    if payload.assigned_to is not None:
        task.assigned_to = payload.assigned_to
    await db.flush()
    await db.refresh(task)
    out = TaskOut.model_validate(task)
    await events.emit(db, principal.workspace, "task_updated", _dump(out))
    await events.commit(db)
    return out


async def delete_task(db: AsyncSession, principal: Principal, task_id: uuid.UUID) -> None:
    """Delete a task. Decisions/handoffs that link to it are kept (task_id SET NULL)."""
    task = await _get_task(db, principal, task_id)
    await db.delete(task)
    await events.emit(
        db, principal.workspace, "task_deleted", {"id": str(task_id), "workspace_id": str(principal.workspace.id)}
    )
    await events.commit(db)


async def list_task_decisions(db: AsyncSession, principal: Principal, task_id: uuid.UUID) -> list[DecisionOut]:
    result = await db.execute(
        select(Decision)
        .where(Decision.workspace_id == principal.workspace.id, Decision.task_id == task_id)
        .order_by(Decision.created_at.desc())
    )
    return [DecisionOut.model_validate(d) for d in result.scalars().all()]


async def list_task_handoffs(db: AsyncSession, principal: Principal, task_id: uuid.UUID) -> list[HandoffOut]:
    result = await db.execute(
        select(Handoff)
        .where(Handoff.workspace_id == principal.workspace.id, Handoff.task_id == task_id)
        .order_by(Handoff.created_at.desc())
    )
    return [HandoffOut.model_validate(h) for h in result.scalars().all()]


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


async def list_decisions(db: AsyncSession, principal: Principal, limit: int = 20) -> list[DecisionOut]:
    stmt = (
        select(Decision)
        .where(Decision.workspace_id == principal.workspace.id)
        .order_by(Decision.created_at.desc())
        .limit(limit)
    )
    return [DecisionOut.model_validate(d) for d in (await db.execute(stmt)).scalars().all()]


async def create_decision(db: AsyncSession, principal: Principal, payload: DecisionIn) -> DecisionOut:
    await _require_task_in_workspace(db, principal, payload.task_id)
    decision = Decision(
        workspace_id=principal.workspace.id,
        title=payload.title,
        reason=payload.reason,
        related_files=payload.related_files,
        made_by=author(principal, payload.made_by),
        task_id=payload.task_id,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)
    out = DecisionOut.model_validate(decision)
    await events.emit(db, principal.workspace, "decision_created", _dump(out))
    await events.commit(db)
    return out


async def delete_decision(db: AsyncSession, principal: Principal, decision_id: uuid.UUID) -> None:
    decision = (
        (
            await db.execute(
                select(Decision).where(Decision.id == decision_id, Decision.workspace_id == principal.workspace.id)
            )
        )
        .scalars()
        .first()
    )
    if decision is None:
        raise NotFound(f"decision '{decision_id}' not found")
    await db.delete(decision)
    await events.emit(
        db,
        principal.workspace,
        "decision_deleted",
        {"id": str(decision_id), "workspace_id": str(principal.workspace.id)},
    )
    await events.commit(db)


# ---------------------------------------------------------------------------
# Session handoffs
# ---------------------------------------------------------------------------


async def _get_handoff(db: AsyncSession, principal: Principal, handoff_id: uuid.UUID) -> Handoff:
    handoff = (
        (
            await db.execute(
                select(Handoff).where(Handoff.id == handoff_id, Handoff.workspace_id == principal.workspace.id)
            )
        )
        .scalars()
        .first()
    )
    if handoff is None:
        raise NotFound(f"handoff '{handoff_id}' not found")
    return handoff


async def list_handoffs(
    db: AsyncSession, principal: Principal, status: HandoffStatus | None = None, limit: int = 20
) -> list[HandoffOut]:
    stmt = (
        select(Handoff)
        .where(Handoff.workspace_id == principal.workspace.id)
        .order_by(Handoff.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(Handoff.status == status)
    return [HandoffOut.model_validate(h) for h in (await db.execute(stmt)).scalars().all()]


async def get_handoff(db: AsyncSession, principal: Principal, handoff_id: uuid.UUID) -> HandoffOut:
    return HandoffOut.model_validate(await _get_handoff(db, principal, handoff_id))


async def create_handoff(db: AsyncSession, principal: Principal, payload: HandoffIn) -> HandoffOut:
    await _require_task_in_workspace(db, principal, payload.task_id)
    handoff = Handoff(
        workspace_id=principal.workspace.id,
        task_id=payload.task_id,
        created_by=author(principal, payload.created_by),
        recipient=payload.recipient,
        branch=payload.branch,
        worktree=payload.worktree,
        summary=payload.summary,
        files_changed=payload.files_changed,
        commands_run=payload.commands_run,
        blockers=payload.blockers,
        next_action=payload.next_action,
    )
    db.add(handoff)
    await db.flush()
    await db.refresh(handoff)
    out = HandoffOut.model_validate(handoff)
    await events.emit(db, principal.workspace, "handoff_created", _dump(out))
    await events.commit(db)
    return out


async def _save_handoff_transition(db: AsyncSession, principal: Principal, handoff: Handoff) -> HandoffOut:
    await db.flush()
    await db.refresh(handoff)
    out = HandoffOut.model_validate(handoff)
    await events.emit(db, principal.workspace, "handoff_updated", _dump(out))
    await events.commit(db)
    return out


async def acknowledge_handoff(db: AsyncSession, principal: Principal, handoff_id: uuid.UUID) -> HandoffOut:
    """open → acknowledged. Idempotent when already acknowledged; 409 once resolved."""
    handoff = await _get_handoff(db, principal, handoff_id)
    if handoff.status == HandoffStatus.resolved:
        raise Conflict("handoff is already resolved")
    if handoff.status != HandoffStatus.open:
        return HandoffOut.model_validate(handoff)
    handoff.status = HandoffStatus.acknowledged
    handoff.acknowledged_at = datetime.now(UTC)
    handoff.acknowledged_by = principal.actor_name
    return await _save_handoff_transition(db, principal, handoff)


async def resolve_handoff(db: AsyncSession, principal: Principal, handoff_id: uuid.UUID) -> HandoffOut:
    """open/acknowledged → resolved. Idempotent when already resolved."""
    handoff = await _get_handoff(db, principal, handoff_id)
    if handoff.status == HandoffStatus.resolved:
        return HandoffOut.model_validate(handoff)
    handoff.status = HandoffStatus.resolved
    handoff.resolved_at = datetime.now(UTC)
    handoff.resolved_by = principal.actor_name
    return await _save_handoff_transition(db, principal, handoff)


async def delete_handoff(db: AsyncSession, principal: Principal, handoff_id: uuid.UUID) -> None:
    handoff = await _get_handoff(db, principal, handoff_id)
    await db.delete(handoff)
    await events.emit(
        db,
        principal.workspace,
        "handoff_deleted",
        {"id": str(handoff_id), "workspace_id": str(principal.workspace.id)},
    )
    await events.commit(db)


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


async def list_presence(db: AsyncSession, principal: Principal) -> list[PresenceOut]:
    cutoff = datetime.now(UTC) - STALE_AFTER
    stmt = (
        select(Presence)
        .where(Presence.workspace_id == principal.workspace.id, Presence.last_seen > cutoff)
        .order_by(Presence.last_seen.desc())
    )
    return [PresenceOut.model_validate(p) for p in (await db.execute(stmt)).scalars().all()]


async def update_presence(db: AsyncSession, principal: Principal, payload: PresenceIn) -> PresenceOut:
    """Upsert a presence heartbeat, keyed on (workspace, actor).

    A true atomic ``INSERT ... ON CONFLICT ... DO UPDATE`` (Postgres or SQLite
    construct depending on the bound dialect), so concurrent heartbeats never
    race. Heartbeats are ephemeral: their event is delivered live but not stored
    in the outbox, which would otherwise fill with one row per actor per beat.
    """
    workspace = principal.workspace
    values = {
        "workspace_id": workspace.id,
        "actor_name": payload.actor_name,
        "actor_type": payload.actor_type,
        "current_file": payload.current_file,
        "current_task": payload.current_task,
        "last_seen": datetime.now(UTC),
    }
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    stmt = insert(Presence).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["workspace_id", "actor_name"],
        set_={
            "actor_type": stmt.excluded.actor_type,
            "current_file": stmt.excluded.current_file,
            "current_task": stmt.excluded.current_task,
            "last_seen": stmt.excluded.last_seen,
        },
    )
    await db.execute(stmt)
    presence = (
        (
            await db.execute(
                select(Presence)
                .where(Presence.workspace_id == workspace.id, Presence.actor_name == payload.actor_name)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .one()
    )
    out = PresenceOut.model_validate(presence)
    await events.emit(db, workspace, "presence_updated", _dump(out), persist=False)
    await events.commit(db)
    return out


# ---------------------------------------------------------------------------
# Search & summary
# ---------------------------------------------------------------------------


async def search(db: AsyncSession, principal: Principal, q: str, limit: int = 20) -> SearchResults:
    """Search decisions and tasks.

    On Postgres: full-text search over the generated ``search_vector`` columns
    (stemmed, ranked). Elsewhere (SQLite in tests): escaped substring match.
    """
    workspace = principal.workspace
    if db.bind.dialect.name == "postgresql":
        query = func.websearch_to_tsquery("english", q)
        decisions_stmt = (
            select(Decision)
            .where(Decision.workspace_id == workspace.id, _search_vector(Decision).op("@@")(query))
            .order_by(func.ts_rank(_search_vector(Decision), query).desc())
        )
        tasks_stmt = (
            select(Task)
            .where(Task.workspace_id == workspace.id, _search_vector(Task).op("@@")(query))
            .order_by(func.ts_rank(_search_vector(Task), query).desc())
        )
    else:
        # Escape LIKE wildcards so %, _, and \ match literally (backslash first).
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        decisions_stmt = select(Decision).where(
            Decision.workspace_id == workspace.id,
            or_(Decision.title.ilike(like, escape="\\"), Decision.reason.ilike(like, escape="\\")),
        )
        tasks_stmt = select(Task).where(Task.workspace_id == workspace.id, Task.title.ilike(like, escape="\\"))

    decisions = (await db.execute(decisions_stmt.limit(limit))).scalars().all()
    tasks = (await db.execute(tasks_stmt.limit(limit))).scalars().all()
    return SearchResults(
        query=q,
        decisions=[DecisionOut.model_validate(d) for d in decisions],
        tasks=[TaskOut.model_validate(t) for t in tasks],
    )


async def summary(db: AsyncSession, principal: Principal) -> WorkspaceSummary:
    """Counts + open handoffs + active developers, aggregated in SQL."""
    workspace = principal.workspace

    async def count(model, *where) -> int:
        stmt = select(func.count()).select_from(model).where(model.workspace_id == workspace.id, *where)
        return (await db.execute(stmt)).scalar_one()

    active = (
        await db.execute(
            select(Presence.actor_name)
            .where(Presence.workspace_id == workspace.id, Presence.last_seen > datetime.now(UTC) - STALE_AFTER)
            .distinct()
        )
    ).scalars()
    return WorkspaceSummary(
        slug=workspace.slug,
        name=workspace.name,
        task_count=await count(Task),
        open_task_count=await count(Task, Task.status != TaskStatus.done),
        decision_count=await count(Decision),
        # Handoffs still needing a pickup (acknowledged ones are in flight).
        open_handoff_count=await count(Handoff, Handoff.status == HandoffStatus.open),
        active_developers=sorted(active),
    )
