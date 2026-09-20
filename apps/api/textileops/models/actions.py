"""ActionProposal → Approval → Execution → AuditEvent.

The only path by which a consequential action reaches the world. AI may
propose and draft; a human approves; TextileOps executes deterministically.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.models.base import TS, Base, TimestampMixin, enum_column, pk_column
from textileops.models.enums import (
    ActionType,
    ApprovalDecision,
    ExecutionMode,
    ExecutionStatus,
    ProposalOrigin,
    ProposalStatus,
)


class ActionProposal(Base, TimestampMixin):
    __tablename__ = "action_proposals"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    exception_id: Mapped[uuid.UUID | None] = mapped_column(
        # RESTRICT: an exception cannot be deleted out from under a proposal
        # that is carrying an approval, which is what made the whole chain
        # reachable by a single cascading delete.
        ForeignKey("operational_exceptions.id", ondelete="RESTRICT"), nullable=True
    )
    action_type: Mapped[ActionType] = mapped_column(
        enum_column(ActionType, "action_type"), nullable=False
    )
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        enum_column(ExecutionMode, "execution_mode"), nullable=False
    )
    status: Mapped[ProposalStatus] = mapped_column(
        enum_column(ProposalStatus, "proposal_status"),
        nullable=False,
        default=ProposalStatus.PENDING_APPROVAL,
    )
    origin: Mapped[ProposalOrigin] = mapped_column(
        enum_column(ProposalOrigin, "proposal_origin"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    #: Typed arguments for the deterministic executor. Validated on approval.
    payload: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)

    #: Human-copyable communication draft, when the action is a message.
    draft_subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    draft_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_original_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ai_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)

    approvals: Mapped[list[Approval]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan", lazy="selectin"
    )
    executions: Mapped[list[Execution]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_proposals_status_created", "status", "created_at"),
        Index("ix_proposals_exception", "exception_id"),
    )


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = pk_column()
    action_proposal_id: Mapped[uuid.UUID] = mapped_column(
        # RESTRICT, not CASCADE. An approval is the record of a person taking
        # responsibility for an action; deleting the proposal must not be able
        # to erase who authorised it. One DELETE of a production batch used to
        # cascade all the way down to here and take the approval with it.
        ForeignKey("action_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        enum_column(ApprovalDecision, "approval_decision"), nullable=False
    )
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Operator adjustments to the proposal payload, recorded verbatim.
    modified_payload: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    proposal: Mapped[ActionProposal] = relationship(back_populates="approvals")

    __table_args__ = (
        Index("ix_approvals_proposal", "action_proposal_id"),
        # Two operators clicking Approve at the same moment produced two
        # approval rows against one proposal, so "who authorised this?" had two
        # answers. The service takes a row lock; this is the backstop that does
        # not depend on the service being called correctly.
        Index(
            "uq_approvals_one_decision_per_proposal",
            "action_proposal_id",
            unique=True,
        ),
    )


class Execution(Base, TimestampMixin):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = pk_column()
    action_proposal_id: Mapped[uuid.UUID] = mapped_column(
        # RESTRICT for the same reason as Approval: the record that something
        # actually ran is the last evidence that it did.
        ForeignKey("action_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[ExecutionMode] = mapped_column(
        enum_column(ExecutionMode, "execution_mode"), nullable=False
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        enum_column(ExecutionStatus, "execution_status"),
        nullable=False,
        default=ExecutionStatus.PENDING,
    )
    attempted_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: One execution per proposal per attempt key — replays are no-ops.
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    executed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    proposal: Mapped[ActionProposal] = relationship(back_populates="executions")

    __table_args__ = (
        CheckConstraint(
            "(status <> 'succeeded') or (completed_at is not null)",
            name="succeeded_requires_completion",
        ),
        Index("ix_executions_proposal", "action_proposal_id"),
    )
