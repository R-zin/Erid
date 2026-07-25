from pydantic import BaseModel
from datetime import datetime
import uuid


class WorkspaceSummary(BaseModel):
    slug: str
    name: str
    task_count: int = 0
    open_task_count: int = 0
    decision_count: int = 0
    active_developers: list[str] = []


class DecisionOut(BaseModel):
    id: uuid.UUID
    title: str
    reason: str | None
    related_files: str | None
    made_by: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    assigned_to: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True
