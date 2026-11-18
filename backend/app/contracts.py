"""Public response schemas. Bank-specific ledger detail is limited to PlanView.private."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class Milestone(BaseModel):
    month: int
    amount: int
    progress_pct: float


class Projection(BaseModel):
    capital: int
    monthly: int
    projected: int
    gap: int
    needed_months: int | None
    extra_monthly: int | None
    remaining_cycles: int
    target_date: str
    achieve_date: str | None
    milestones: list[Milestone]


class PlanView(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: UUID
    owner: Literal["kb","b"]
    title: str
    target: int
    months: int
    version: int
    status: Literal["invited","review","confirmed","rejected"]
    shares: dict
    private: dict
    forecast: Projection | None
    votes: dict[str,str]
    confirmed: dict | None


class RunReceipt(BaseModel):
    id: UUID
    state: str


class RunRecord(RunReceipt):
    session_id: UUID
    prompt: str
    answer: str | None
    created_at: datetime


class TraceRecord(BaseModel):
    seq: int
    session_id: UUID
    run_id: UUID
    kind: str
    payload: dict
    created_at: datetime


class TraceGroup(BaseModel):
    session_id: UUID
    events: int
    updated: datetime
