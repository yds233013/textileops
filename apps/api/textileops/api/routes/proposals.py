"""Action proposals, approvals and executions."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from textileops.api.deps import ApproverUser, CurrentUser, DbSession
from textileops.core.errors import NotFoundError
from textileops.models.actions import ActionProposal
from textileops.models.enums import ActionType, ProposalOrigin, ProposalStatus
from textileops.services import actions as action_service

router = APIRouter(prefix="/proposals", tags=["proposals"])


class ApprovalOut(BaseModel):
    id: uuid.UUID
    decision: str
    decided_by_user_id: uuid.UUID
    decided_at: dt.datetime
    note: str | None


class ExecutionOut(BaseModel):
    id: uuid.UUID
    mode: str
    status: str
    attempted_at: dt.datetime
    completed_at: dt.datetime | None
    result: dict[str, Any] | None
    error: str | None


class ProposalOut(BaseModel):
    id: uuid.UUID
    code: str
    exception_id: uuid.UUID | None
    action_type: str
    execution_mode: str
    status: str
    origin: str
    title: str
    rationale: str
    payload: dict[str, Any]
    draft_subject: str | None
    draft_body: str | None
    draft_edited: bool
    model: str | None
    created_at: dt.datetime
    expires_at: dt.datetime | None
    approvals: list[ApprovalOut]
    executions: list[ExecutionOut]
    #: Plain-language statement of what approving will actually do.
    effect_description: str


_EFFECTS: dict[str, str] = {
    "internal": "TextileOps will carry this out immediately and record an audit event.",
    "external_draft": (
        "TextileOps has no connected channel for this. Approving records the decision and "
        "produces a draft for you to send yourself — nothing is sent automatically."
    ),
}


def _out(proposal: ActionProposal) -> ProposalOut:
    return ProposalOut(
        id=proposal.id,
        code=proposal.code,
        exception_id=proposal.exception_id,
        action_type=proposal.action_type.value,
        execution_mode=proposal.execution_mode.value,
        status=proposal.status.value,
        origin=proposal.origin.value,
        title=proposal.title,
        rationale=proposal.rationale,
        payload=proposal.payload,
        draft_subject=proposal.draft_subject,
        draft_body=proposal.draft_body,
        draft_edited=proposal.draft_edited,
        model=proposal.model,
        created_at=proposal.created_at,
        expires_at=proposal.expires_at,
        effect_description=_EFFECTS[proposal.execution_mode.value],
        approvals=[
            ApprovalOut(
                id=approval.id,
                decision=approval.decision.value,
                decided_by_user_id=approval.decided_by_user_id,
                decided_at=approval.decided_at,
                note=approval.note,
            )
            for approval in proposal.approvals
        ],
        executions=[
            ExecutionOut(
                id=execution.id,
                mode=execution.mode.value,
                status=execution.status.value,
                attempted_at=execution.attempted_at,
                completed_at=execution.completed_at,
                result=execution.result,
                error=execution.error,
            )
            for execution in proposal.executions
        ],
    )


@router.get("", response_model=list[ProposalOut])
def list_proposals(
    session: DbSession,
    _user: CurrentUser,
    status: str | None = None,
    exception_id: uuid.UUID | None = None,
    pending_only: bool = False,
    limit: int = Query(200, ge=1, le=500),
) -> list[ProposalOut]:
    stmt = select(ActionProposal).order_by(ActionProposal.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ActionProposal.status == ProposalStatus(status))
    elif pending_only:
        stmt = stmt.where(ActionProposal.status == ProposalStatus.PENDING_APPROVAL)
    if exception_id:
        stmt = stmt.where(ActionProposal.exception_id == exception_id)
    return [_out(proposal) for proposal in session.scalars(stmt).all()]


@router.get("/{proposal_id}", response_model=ProposalOut)
def get_proposal(
    proposal_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> ProposalOut:
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"Proposal {proposal_id} not found.")
    return _out(proposal)


class CreateProposalRequest(BaseModel):
    action_type: str
    title: str
    rationale: str
    payload: dict[str, Any]
    exception_id: uuid.UUID | None = None
    draft_subject: str | None = None
    draft_body: str | None = None


@router.post("", response_model=ProposalOut)
def create_proposal(
    payload: CreateProposalRequest, session: DbSession, user: ApproverUser
) -> ProposalOut:
    proposal = action_service.create_proposal(
        session,
        action_type=ActionType(payload.action_type),
        title=payload.title,
        rationale=payload.rationale,
        payload=payload.payload,
        origin=ProposalOrigin.HUMAN,
        exception_id=payload.exception_id,
        draft_subject=payload.draft_subject,
        draft_body=payload.draft_body,
        created_by_user_id=user.id,
    )
    session.commit()
    return _out(proposal)


class DraftEditRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    subject: str | None = None


@router.patch("/{proposal_id}/draft", response_model=ProposalOut)
def edit_draft(
    proposal_id: uuid.UUID,
    payload: DraftEditRequest,
    session: DbSession,
    user: ApproverUser,
) -> ProposalOut:
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"Proposal {proposal_id} not found.")
    action_service.edit_draft(
        session, proposal, body=payload.body, subject=payload.subject, user_id=user.id
    )
    session.commit()
    return _out(proposal)


class DecisionRequest(BaseModel):
    note: str | None = None
    modified_payload: dict[str, Any] | None = None


class DecisionResponse(BaseModel):
    proposal: ProposalOut
    execution: ExecutionOut | None
    message: str
    #: "ok" | "failed" | "awaiting_external". The client used to have only
    #: `message` to go on and rendered every 200 in success green — including
    #: "Approved, but execution failed: …", which an operator reads as done.
    outcome: str = "ok"


@router.post("/{proposal_id}/approve", response_model=DecisionResponse)
def approve(
    proposal_id: uuid.UUID,
    payload: DecisionRequest,
    session: DbSession,
    user: ApproverUser,
) -> DecisionResponse:
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"Proposal {proposal_id} not found.")
    _, execution = action_service.approve(
        session,
        proposal,
        user_id=user.id,
        note=payload.note,
        modified_payload=payload.modified_payload,
    )
    session.commit()
    out = _out(proposal)
    outcome = "ok"
    if execution is None:
        message = "Approved."
    elif execution.status.value == "awaiting_external":
        outcome = "awaiting_external"
        message = (
            "Approved and recorded. The draft is ready to copy — TextileOps has not sent "
            "anything, because no channel is connected."
        )
    elif execution.status.value == "succeeded":
        message = "Approved and carried out."
    else:
        outcome = "failed"
        message = f"Approved, but execution failed: {execution.error}"
    return DecisionResponse(
        proposal=out,
        execution=out.executions[-1] if out.executions else None,
        message=message,
        outcome=outcome,
    )


@router.post("/{proposal_id}/reject", response_model=ProposalOut)
def reject(
    proposal_id: uuid.UUID,
    payload: DecisionRequest,
    session: DbSession,
    user: ApproverUser,
) -> ProposalOut:
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"Proposal {proposal_id} not found.")
    action_service.reject(session, proposal, user_id=user.id, note=payload.note)
    session.commit()
    return _out(proposal)
