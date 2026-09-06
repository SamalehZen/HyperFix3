"""``MiddlewareExecutor.wrap_model_invocation`` failure contract.

The provider retry + fallback policy lives INSIDE ``invoke_fn``
(``ainvoke_llm``): a 429/quota error with a working fallback never reaches
this layer. What reaches it is either a middleware bug (before or after the
model ran) or a total outage (primary AND fallback down). The contract:

- pre-model middleware failure -> one direct ``invoke_fn`` safety-net call,
  rebuilt from the REQUEST (system message preserved), not raw state;
- post-model middleware failure -> the model's own response is shipped, the
  model is NOT invoked a second time (no double spend);
- ``GraphBubbleUp`` (HIL interrupt control flow) and ``CancelledError``
  always propagate — the safety net must never swallow them;
- total outage -> the error propagates loud, after the policy is spent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphBubbleUp
import pytest

from app.agents.middleware.executor import MiddlewareExecutor

SYSTEM = SystemMessage(content="you are gaia")
USER = HumanMessage(content="fais le récap d'aujourd'hui")


def _state() -> dict[str, Any]:
    return {"messages": [SYSTEM, USER]}


def _executor(middleware: list[AgentMiddleware]) -> MiddlewareExecutor:
    return MiddlewareExecutor(middleware)  # type: ignore[arg-type]


class _Passthrough(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(request)


class _BreakBeforeModel(AgentMiddleware):
    """Raises without ever calling the handler (pre-model middleware bug)."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        raise RuntimeError("pre-model middleware boom")


class _BreakAfterModel(AgentMiddleware):
    """Calls the model, then raises (post-model middleware bug)."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        await handler(request)
        raise RuntimeError("post-model middleware boom")


class _Interrupt(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        raise GraphBubbleUp()


async def _invoke(
    executor: MiddlewareExecutor,
    invoke_fn: AsyncMock[Any],
) -> AIMessage:
    return await executor.wrap_model_invocation(
        model=MagicMock(),
        state=_state(),  # type: ignore[arg-type]
        config={},
        store=None,
        tools=[],
        invoke_fn=invoke_fn,
    )


async def test_passthrough_returns_model_answer() -> None:
    invoke_fn = AsyncMock(return_value=AIMessage(content="model-answer"))
    result = await _invoke(_executor([_Passthrough()]), invoke_fn)
    assert result.content == "model-answer"
    invoke_fn.assert_awaited_once()


async def test_pre_model_failure_safety_net_keeps_system_message() -> None:
    """The safety net rebuilds the prompt from the request: the system message
    extracted out of state must still reach the model."""
    invoke_fn = AsyncMock(return_value=AIMessage(content="direct-answer"))
    result = await _invoke(_executor([_BreakBeforeModel()]), invoke_fn)
    assert result.content == "direct-answer"
    invoke_fn.assert_awaited_once()
    sent = invoke_fn.await_args.args[0]
    assert sent == [SYSTEM, USER]


async def test_post_model_failure_ships_response_without_reinvoke() -> None:
    """The model already answered: ship its response, do NOT spend a second
    model call (retry + fallback included) to work around a middleware bug."""
    invoke_fn = AsyncMock(return_value=AIMessage(content="model-answer"))
    result = await _invoke(_executor([_BreakAfterModel()]), invoke_fn)
    assert result.content == "model-answer"
    invoke_fn.assert_awaited_once()


async def test_interrupt_propagates_without_invoking_model() -> None:
    invoke_fn = AsyncMock(return_value=AIMessage(content="must-not-run"))
    with pytest.raises(GraphBubbleUp):
        await _invoke(_executor([_Interrupt()]), invoke_fn)
    invoke_fn.assert_not_awaited()


async def test_cancellation_propagates_without_invoking_model() -> None:
    class _Cancel(AgentMiddleware):
        async def awrap_model_call(
            self,
            request: ModelRequest,
            handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        ) -> ModelResponse:
            raise asyncio.CancelledError()

    invoke_fn = AsyncMock(return_value=AIMessage(content="must-not-run"))
    with pytest.raises(asyncio.CancelledError):
        await _invoke(_executor([_Cancel()]), invoke_fn)
    invoke_fn.assert_not_awaited()


async def test_total_outage_raises_loud() -> None:
    """Primary AND fallback down (``invoke_fn`` itself raises): no silent
    empty reply, the provider error propagates after the policy is spent."""
    invoke_fn = AsyncMock(side_effect=RuntimeError("429 quota exhausted"))
    with pytest.raises(RuntimeError, match="429 quota exhausted"):
        await _invoke(_executor([_Passthrough()]), invoke_fn)
