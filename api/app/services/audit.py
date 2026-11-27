"""Audit trail of security-relevant actions.

Records who did what to which workspace, from which address, and whether it
succeeded: provisioning, claiming, key rotation, deletion, actor changes,
token issuance and refusals, OAuth logins and invites, and rejected
credentials. Owners read it at ``GET /api/workspaces/{slug}/audit``.

Writes are best-effort: a failure to record is logged and never fails the
request it describes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.settings import settings
from app.models.models import AuditEvent, Workspace
from app.schemas.schemas import AuditEventOut
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("context_hub.audit")


async def record(
    db: AsyncSession,
    action: str,
    *,
    workspace: Workspace | None = None,
    slug: str | None = None,
    actor: str | None = None,
    target: str | None = None,
    outcome: str = "success",
    ip: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one audit event in its own transaction."""
    try:
        db.add(
            AuditEvent(
                workspace_id=workspace.id if workspace is not None else None,
                workspace_slug=(workspace.slug if workspace is not None else slug),
                action=action,
                actor=(actor or None) and actor[:128],
                target=(target or None) and target[:256],
                outcome=outcome,
                client_ip=(ip or None) and ip[:64],
                detail=detail,
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - auditing must never break the request
        logger.exception("audit: failed to record %s", action)
        await db.rollback()
    # Mirror to the log stream too, for log-based SIEM pipelines.
    logger.info(
        "audit action=%s workspace=%s actor=%s target=%s outcome=%s ip=%s",
        action,
        workspace.slug if workspace is not None else slug,
        actor,
        target,
        outcome,
        ip,
    )


async def list_events(
    db: AsyncSession, workspace: Workspace, *, action: str | None = None, limit: int = 100, offset: int = 0
) -> list[AuditEventOut]:
    stmt = (
        select(AuditEvent)
        # By id, not slug: a workspace that reuses a deleted one's slug must not
        # see the old workspace's trail.
        .where(AuditEvent.workspace_id == workspace.id)
        .order_by(AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    return [AuditEventOut.model_validate(e) for e in (await db.execute(stmt)).scalars().all()]


async def prune(db: AsyncSession) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=settings.audit_retention_days)
    result = await db.execute(delete(AuditEvent).where(AuditEvent.created_at < cutoff))
    await db.commit()
    return result.rowcount or 0
