import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"
    blocked = "blocked"


class ActorRole(str, enum.Enum):
    """Coarse identity tier for an actor. Grants fine-tune below this."""

    reader = "reader"  # read-only
    writer = "writer"  # read + write tasks/decisions/presence
    owner = "owner"  # writer + mint/revoke keys, manage actors


class Permission(str, enum.Enum):
    """Fine-grained, per-resource actions a principal may be granted.

    Each API route / WS declares the action it requires; a principal may act
    when it holds the matching permission (``owner`` implies all).
    """

    read = "read"  # tasks/decisions/summary/search/presence reads
    write_tasks = "write_tasks"  # create/update tasks
    write_decisions = "write_decisions"  # create decisions
    presence = "presence"  # update presence heartbeat
    admin_keys = "admin_keys"  # mint/revoke actor keys, manage roles/grants
    owner = "owner"  # full access; implies every other permission


# Default grants per role. ``owner`` needs no explicit grants: it implies all.
ROLE_GRANTS: dict[ActorRole, frozenset[Permission]] = {
    ActorRole.reader: frozenset({Permission.read}),
    ActorRole.writer: frozenset(
        {Permission.read, Permission.write_tasks, Permission.write_decisions, Permission.presence}
    ),
    ActorRole.owner: frozenset(),  # implies everything
}


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    # When set, every route for this workspace requires this key. NULL means
    # the workspace is "open" (no auth) until a key is assigned.
    api_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tasks: Mapped[list[Task]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    decisions: Mapped[list[Decision]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    presences: Mapped[list[Presence]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    actors: Mapped[list[Actor]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class Actor(Base):
    """A named identity in a workspace with its own key and access grants.

    The raw key is never stored — only a SHA-256 hash — and is disclosed once at
    minting. ``role`` gives a coarse tier; explicit ``grants`` fine-tune access.
    """

    __tablename__ = "actors"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_actors_workspace_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[ActorRole] = mapped_column(Enum(ActorRole), default=ActorRole.writer)
    # SHA-256 hex digest of the raw API key; NULL for actors that only use JWT.
    key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="actors")
    grants: Mapped[list[Grant]] = relationship(back_populates="actor", cascade="all, delete-orphan", lazy="selectin")


class OAuthIdentity(Base):
    """Links an external OAuth account (Google/GitHub) to a workspace ``Actor``.

    OAuth is only an alternate way to mint the internal JWT: a successful
    social login resolves to a real ``Actor`` row (role ``writer``, no API key)
    and signs a token for it. ``provider`` + ``provider_subject`` is unique, so
    a given external account always maps to the same actor across logins.
    """

    __tablename__ = "oauth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32))  # "google" | "github"
    provider_subject: Mapped[str] = mapped_column(String(255))  # stable account id from the provider
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped[Actor] = relationship()


class Grant(Base):
    """A single permission granted to an actor (fine-grained, per-resource)."""

    __tablename__ = "actor_grants"
    __table_args__ = (UniqueConstraint("actor_id", "permission", name="uq_grants_actor_permission"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id", ondelete="CASCADE"), index=True)
    permission: Mapped[Permission] = mapped_column(Enum(Permission))

    actor: Mapped[Actor] = relationship(back_populates="grants")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(512))
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.todo)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="tasks")
    # Decisions linked to this task (decision ↔ task linking).
    decisions: Mapped[list[Decision]] = relationship(back_populates="task")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(512))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_files: Mapped[str | None] = mapped_column(Text, nullable=True)
    made_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Optional link to the task this decision informs (decision ↔ task linking).
    # SET NULL keeps the decision if the task is deleted.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="decisions")
    task: Mapped[Task | None] = relationship(back_populates="decisions", foreign_keys=[task_id])


class Presence(Base):
    __tablename__ = "presence"
    # One row per (workspace, actor): the upsert conflict target.
    __table_args__ = (UniqueConstraint("workspace_id", "actor_name", name="uq_presence_workspace_actor"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_name: Mapped[str] = mapped_column(String(128))
    actor_type: Mapped[str] = mapped_column(String(32), default="human")
    current_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    current_task: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="presences")
