"""Provider abstraction.

The product must work with no credentials at all, so the provider interface is
narrow and every caller is written against it — never against the Anthropic SDK
directly. :class:`StubProvider` is a first-class implementation, not a mock:
it is what runs in CI and in a demo on a plane.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

from textileops.models.enums import AICallStatus

T = TypeVar("T", bound=BaseModel)


@dataclass
class AIUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class AIResult(Generic[T]):
    """The outcome of one structured call."""

    value: T | None
    status: AICallStatus
    provider: str
    model: str | None
    request_id: str | None = None
    latency_ms: int | None = None
    usage: AIUsage = field(default_factory=AIUsage)
    attempts: int = 1
    validation_error: str | None = None
    #: True when produced by the deterministic stub rather than a model.
    stubbed: bool = False

    @property
    def ok(self) -> bool:
        return self.value is not None


@dataclass
class ToolSpec:
    """A read-only tool exposed to the investigation agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    #: Enforced at registration time: an investigation agent may only ever hold
    #: tools declared read-only.
    read_only: bool = True


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    at: dt.datetime


@dataclass
class AgentResult(Generic[T]):
    value: T | None
    status: AICallStatus
    provider: str
    model: str | None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    request_id: str | None = None
    latency_ms: int | None = None
    usage: AIUsage = field(default_factory=AIUsage)
    validation_error: str | None = None
    stubbed: bool = False

    @property
    def ok(self) -> bool:
        return self.value is not None


class AIProvider(Protocol):
    """Everything TextileOps asks of a model provider."""

    name: str

    def structured(
        self,
        *,
        workflow: str,
        system: str,
        user_content: str,
        schema: type[T],
        context: dict[str, Any] | None = None,
    ) -> AIResult[T]:
        """One call, one schema-valid object (or a validation failure)."""

    def investigate(
        self,
        *,
        workflow: str,
        system: str,
        user_content: str,
        schema: type[T],
        tools: list[ToolSpec],
        context: dict[str, Any] | None = None,
        max_iterations: int = 8,
    ) -> AgentResult[T]:
        """An agentic loop restricted to read-only tools."""


#: Tool names that must never be exposed to an investigation agent, whatever
#: their ``read_only`` flag claims. A flag defaults to safe, so on its own it
#: only records an author's intention; this list does not depend on anyone
#: having remembered to set it.
FORBIDDEN_TOOL_NAMES = frozenset(
    {
        "send_email",
        "send_message",
        "send_whatsapp",
        "modify_purchase_order",
        "update_purchase_order",
        "adjust_inventory",
        "post_movement",
        "create_movement",
        "change_production_priority",
        "promise_delivery_date",
        "commit_payment",
        "approve_proposal",
        "approve",
        "execute_action",
        "execute",
        "delete_document",
        "delete_message",
        "write",
        "update",
        "delete",
    }
)

#: Verbs that indicate a tool changes something.
_WRITE_PREFIXES = ("create_", "update_", "delete_", "set_", "post_", "send_", "approve_",
                   "execute_", "adjust_", "modify_", "change_", "commit_", "write_")


def assert_read_only(tools: list[ToolSpec]) -> None:
    """Guard rail. An investigation agent never receives a write-capable tool.

    Checks three things, because the first alone is only a convention:
    the declared flag, an explicit deny list, and the tool's own name. A tool
    called ``send_email`` does not get to claim it is read-only.
    """
    offenders = sorted(
        {tool.name for tool in tools if not tool.read_only}
        | {tool.name for tool in tools if tool.name in FORBIDDEN_TOOL_NAMES}
        | {
            tool.name
            for tool in tools
            # `stage_action_proposal` stages in memory and writes nothing; it is
            # the one deliberate exception to the naming rule.
            if tool.name != "stage_action_proposal"
            and tool.name.startswith(_WRITE_PREFIXES)
        }
    )
    if offenders:
        raise ValueError(
            "Investigation agents are read-only; refusing to expose write-capable "
            f"tools: {', '.join(offenders)}"
        )


def new_request_id(prefix: str = "local") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"
