import uuid
from datetime import datetime

from app.models.models import ActorRole, Permission, TaskStatus
from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSummary(BaseModel):
    slug: str
    name: str
    task_count: int = 0
    open_task_count: int = 0
    decision_count: int = 0
    active_developers: list[str] = Field(default_factory=list)


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    created_at: datetime


class WorkspaceCreated(WorkspaceOut):
    """Returned once at provisioning time; the api_key is shown only here."""

    api_key: str | None


class WorkspaceListItem(WorkspaceOut):
    """A workspace in a directory listing: ``secured`` flags whether it needs a key."""

    secured: bool


class WorkspaceSecured(BaseModel):
    """Returned once when an open workspace is secured; the key is shown only here."""

    slug: str
    secured: bool
    api_key: str | None


class WorkspaceKeyRotated(BaseModel):
    """Returned once when the workspace key rotates; the new key is shown only here."""

    slug: str
    api_key: str | None


class DecisionIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    reason: str | None = None
    related_files: str | None = None
    made_by: str | None = None
    task_id: uuid.UUID | None = None  # link this decision to a task


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    reason: str | None
    related_files: str | None
    made_by: str | None
    task_id: uuid.UUID | None
    created_at: datetime


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    assigned_to: str | None = None
    created_by: str | None = None
    status: TaskStatus = TaskStatus.todo


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    status: TaskStatus | None = None
    assigned_to: str | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: TaskStatus
    assigned_to: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime | None


class PresenceIn(BaseModel):
    actor_name: str = Field(min_length=1, max_length=128)
    actor_type: str = "human"
    current_file: str | None = None
    current_task: str | None = None


class PresenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_name: str
    actor_type: str
    current_file: str | None
    current_task: str | None
    last_seen: datetime


# ---------------------------------------------------------------------------
# Actors, access grants, and tokens
# ---------------------------------------------------------------------------


class ActorIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role: ActorRole = ActorRole.writer
    permissions: list[Permission] | None = None  # defaults to the role's grants


class ActorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: ActorRole
    active: bool
    created_at: datetime


class ActorToken(BaseModel):
    """Minted bearer token for an actor (returned from the login endpoint)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRequest(BaseModel):
    """Login: exchange an actor (or legacy workspace) API key for a JWT."""

    api_key: str = Field(min_length=1)


class ActorCreated(ActorOut):
    """Returned once at minting; the raw API key is shown only here."""

    api_key: str | None
