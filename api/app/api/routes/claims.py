"""File claims: advisory leases on paths (see :mod:`app.services.claims`)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal, require_action
from app.db.session import get_db
from app.models.models import Permission
from app.schemas.schemas import ClaimCheck, ClaimCheckIn, ClaimIn, ClaimOut, ClaimResult, ReleaseIn, ReleaseResult
from app.services import claims as svc

router = APIRouter()

READ = require_action(Permission.read)
# Claiming is coordination, like presence: writers and agents have it.
CLAIM = require_action(Permission.presence)


@router.post("/workspaces/{slug}/claims", response_model=ClaimResult)
async def claim_files(
    payload: ClaimIn, principal: Principal = Depends(CLAIM), db: AsyncSession = Depends(get_db)
) -> ClaimResult:
    """Claim paths before editing them. Non-conflicting paths are granted;
    conflicting ones come back under ``conflicts`` with who holds them.
    Claiming a path you already hold renews it."""
    return await svc.claim(db, principal, payload)


@router.get("/workspaces/{slug}/claims", response_model=list[ClaimOut])
async def list_claims(
    path: str | None = Query(default=None, max_length=512),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> list[ClaimOut]:
    """Active claims, optionally only those overlapping ``path``."""
    return await svc.list_claims(db, principal, path)


@router.post("/workspaces/{slug}/claims/check", response_model=list[ClaimCheck])
async def check_claims(
    payload: ClaimCheckIn, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> list[ClaimCheck]:
    """For each path, the active claims covering it (claims nothing). Built for
    pre-commit hooks: fail when ``claimed_by_others`` is true."""
    return await svc.check(db, principal, payload)


@router.post("/workspaces/{slug}/claims/release", response_model=ReleaseResult)
async def release_claims(
    payload: ReleaseIn, principal: Principal = Depends(CLAIM), db: AsyncSession = Depends(get_db)
) -> ReleaseResult:
    """Release your claims on ``paths``, or all your claims when omitted."""
    return await svc.release(db, principal, payload)


@router.delete("/workspaces/{slug}/claims/{claim_id}", response_model=ReleaseResult)
async def release_claim(
    claim_id: uuid.UUID, principal: Principal = Depends(CLAIM), db: AsyncSession = Depends(get_db)
) -> ReleaseResult:
    """Release one claim: your own, or anyone's if you are an admin."""
    return await svc.release_one(db, principal, claim_id)
