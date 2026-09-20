"""Anthropic-backed provider.

Used when ``ANTHROPIC_API_KEY`` is configured. Two call shapes:

* :meth:`structured` — a single schema-constrained call via
  ``client.messages.parse``, which validates the response against the Pydantic
  model for us. Validation failures are retried once with the error fed back,
  then reported as failures rather than silently patched.

* :meth:`investigate` — an explicit tool loop. We drive it by hand rather than
  using the SDK's tool runner because the loop is where the read-only
  guarantee is enforced: every tool comes from a registry that refuses
  write-capable handlers, and every call is recorded for the audit trail.
"""

from __future__ import annotations

import json
import time
from typing import Any, TypeVar, cast

from anthropic.types import MessageParam, ToolParam
from pydantic import BaseModel

from textileops.ai.base import (
    AgentResult,
    AIProvider,
    AIResult,
    AIUsage,
    ToolCallRecord,
    ToolSpec,
    assert_read_only,
)
from textileops.core.config import settings
from textileops.core.logging import get_logger
from textileops.models.enums import AICallStatus
from textileops.services import clock

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        import anthropic

        self._anthropic = anthropic
        self.model = model or settings.ai_model
        self._client = anthropic.Anthropic(
            api_key=api_key or settings.anthropic_api_key,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    # --- structured -------------------------------------------------------
    def structured(
        self,
        *,
        workflow: str,
        system: str,
        user_content: str,
        schema: type[T],
        context: dict[str, Any] | None = None,
    ) -> AIResult[T]:
        started = time.perf_counter()
        attempts = 0
        last_error: str | None = None
        messages: list[MessageParam] = [{"role": "user", "content": user_content}]

        while attempts < max(1, settings.ai_max_retries):
            attempts += 1
            try:
                response = self._client.messages.parse(
                    model=self.model,
                    max_tokens=settings.ai_max_tokens,
                    system=system,
                    messages=messages,
                    output_format=schema,
                )
            except self._anthropic.APIStatusError as exc:
                logger.warning("ai_provider_error", workflow=workflow, status=exc.status_code)
                return AIResult(
                    value=None,
                    status=AICallStatus.PROVIDER_ERROR,
                    provider=self.name,
                    model=self.model,
                    attempts=attempts,
                    validation_error=f"HTTP {exc.status_code}",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            except self._anthropic.APIConnectionError as exc:
                return AIResult(
                    value=None,
                    status=AICallStatus.PROVIDER_ERROR,
                    provider=self.name,
                    model=self.model,
                    attempts=attempts,
                    validation_error=f"connection error: {exc}",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )

            parsed = getattr(response, "parsed_output", None)
            if isinstance(parsed, schema):
                return AIResult(
                    value=parsed,
                    status=AICallStatus.SUCCESS,
                    provider=self.name,
                    model=self.model,
                    request_id=getattr(response, "_request_id", None),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    usage=_usage(response),
                    attempts=attempts,
                )

            last_error = "Model response did not validate against the required schema."
            messages = [
                *messages,
                {"role": "assistant", "content": _text_of(response)},
                {
                    "role": "user",
                    "content": (
                        "That response did not match the required schema. Return only a "
                        "valid object for the schema, with no commentary."
                    ),
                },
            ]

        return AIResult(
            value=None,
            status=AICallStatus.VALIDATION_FAILED,
            provider=self.name,
            model=self.model,
            attempts=attempts,
            validation_error=last_error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    # --- agentic investigation -------------------------------------------
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
        assert_read_only(tools)
        started = time.perf_counter()
        calls: list[ToolCallRecord] = []
        handlers = {tool.name: tool for tool in tools}
        tool_defs: list[ToolParam] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
        messages: list[MessageParam] = [{"role": "user", "content": user_content}]
        request_id: str | None = None
        usage = AIUsage(input_tokens=0, output_tokens=0)

        for _ in range(max_iterations):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=settings.ai_max_tokens,
                    system=system,
                    messages=messages,
                    tools=tool_defs,
                )
            except self._anthropic.APIError as exc:
                return AgentResult(
                    value=None,
                    status=AICallStatus.PROVIDER_ERROR,
                    provider=self.name,
                    model=self.model,
                    tool_calls=calls,
                    validation_error=str(exc),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )

            request_id = getattr(response, "_request_id", None) or request_id
            call_usage = _usage(response)
            usage.input_tokens = (usage.input_tokens or 0) + (call_usage.input_tokens or 0)
            usage.output_tokens = (usage.output_tokens or 0) + (call_usage.output_tokens or 0)

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                results: list[Any] = []
                for raw_block in response.content:
                    # The SDK content block is a wide union; only a tool_use
                    # block carries a name and arguments.
                    if raw_block.type != "tool_use":
                        continue
                    block = cast(Any, raw_block)
                    tool = handlers.get(block.name)
                    if tool is None:
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": f"Unknown tool {block.name}.",
                            }
                        )
                        continue
                    try:
                        payload = tool.handler(**dict(block.input))
                        body = json.dumps(payload, default=str)[:20000]
                        ok = True
                    except Exception as exc:
                        body = f"{type(exc).__name__}: {exc}"
                        ok = False
                    calls.append(
                        ToolCallRecord(
                            name=block.name,
                            arguments=dict(block.input),
                            ok=ok,
                            summary=body[:300],
                            at=clock.now(),
                        )
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": not ok,
                            "content": body,
                        }
                    )
                messages.append({"role": "user", "content": results})
                continue

            # No more tools wanted: ask for the final structured answer.
            messages.append({"role": "assistant", "content": _text_of(response)})
            final = self.structured(
                workflow=workflow,
                system=system,
                user_content=(
                    "Now produce your final investigation as a single object matching the "
                    "required schema, using only the evidence gathered above.\n\n"
                    + "\n\n".join(
                        f"Tool {call.name} returned: {call.summary}" for call in calls
                    )
                    + f"\n\nOriginal brief:\n{user_content}"
                ),
                schema=schema,
            )
            return AgentResult(
                value=final.value,
                status=final.status,
                provider=self.name,
                model=self.model,
                tool_calls=calls,
                request_id=request_id or final.request_id,
                latency_ms=int((time.perf_counter() - started) * 1000),
                usage=usage,
                validation_error=final.validation_error,
            )

        return AgentResult(
            value=None,
            status=AICallStatus.VALIDATION_FAILED,
            provider=self.name,
            model=self.model,
            tool_calls=calls,
            validation_error=f"Investigation did not conclude within {max_iterations} steps.",
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=usage,
        )


def _usage(response: Any) -> AIUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return AIUsage()
    return AIUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


def _text_of(response: Any) -> str:
    parts = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts) or "(no text)"
