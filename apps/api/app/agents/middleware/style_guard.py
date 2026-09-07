"""Comms style guard: score the draft reply, and make the model rewrite it once.

The prompt could not carry this on its own. A 60-vs-60 A/B of the shipped comms
prompt against a rewritten one, on real production queries at a fixed
temperature and reasoning effort, was a null result — by turn forty the model's
own tell-laden replies fill the context and outvote any instruction sitting in
the system prompt. So the lever is code: ``app.agents.evals.ai_isms`` scores the
draft deterministically, and a draft that scores dirty goes back to the model
with its own offending fragments quoted.

The retry is bounded to one. Two things make that the right cap: the second
call is charged to the user like any other, and every tell the scorer knows
about is a single-shot fix (drop the em dash, drop the sign-off) rather than
something a model converges on over rounds.

**The draft's tokens are already on the client.** The model call streams
through the same ``messages`` stream mode ``execute_graph_streaming`` consumes,
so by the time this middleware has a complete draft to score, the user has read
it. It can only be taken back, never suppressed — and the protocol for taking
back streamed text already exists, because the handoff preamble needs exactly
the same thing: a ``message_boundary`` frame carrying ``discarded: true``. This
middleware writes one for the draft, on the graph's custom stream, BEFORE it
asks for the rewrite. Bots key nothing by message id — they hold the text
streamed since the last boundary and either keep it or drop it — so a retraction
that arrived after the replacement text would drop the replacement too.

That ordering is also why a rewrite scoring WORSE than the draft is still
delivered: the draft was retracted on the wire before the rewrite was
requested, and returning it now would persist text every client was told to
drop. The regression is recorded on the wide event instead.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.agents.evals.ai_isms import AiIsmScore, score_reply, violation_snippets
from app.agents.llm.lane import ModelLane
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.llm import LANE_FIELD_ID, UNKNOWN_MODEL_NAME
from app.constants.log_tags import LogTag
from app.constants.style_guard import (
    STYLE_GUARD_CORRECTION_INSTRUCTION,
    STYLE_GUARD_MAX_SNIPPETS_PER_DETECTOR,
    STYLE_GUARD_MAX_VIOLATIONS,
    STYLE_GUARD_RULES,
)
from app.models.agent_models import AgentConfigurable, agent_configurable, current_run_config
from app.models.stream_events import MessageBoundaryPayload
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.llm_metering import (
    LLMCallContext,
    extract_finish_reason,
    extract_generation_id,
    extract_message_cost,
    extract_message_model,
    extract_message_provider,
    extract_message_usage,
    record_llm_call,
    resolve_channel,
)
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import log

ModelCallHandler = Callable[[ModelRequest], Awaitable[ModelResponse]]

#: Channels whose clients render markdown and OpenUI components — the only
#: ones whose prompt carries the Rich Chat section.
_RENDERABLE_SOURCES = frozenset({"web", "mobile", "desktop"})

#: A draft is a structured rich reply (report, recap, analysis), not
#: conversational chat, when it carries markdown headings, a markdown table
#: (header + separator at minimum), or an OpenUI component fence.
_RICH_HEADING_PATTERN = re.compile(r"^#{1,3} ", re.M)
_RICH_TABLE_ROW_PATTERN = re.compile(r"^\s*\|.*\|\s*$", re.M)


def build_correction_note(text: str) -> str:
    """The rewrite instruction for a draft, naming every tell it actually used."""
    lines = [
        f"- {STYLE_GUARD_RULES[detector]} ×{len(snippets)}: "
        + "; ".join(f'"{snippet}"' for snippet in snippets[:STYLE_GUARD_MAX_SNIPPETS_PER_DETECTOR])
        for detector, snippets in violation_snippets(text).items()
    ]
    body = "\n".join(
        ["Your draft violated the voice rules:", *lines, STYLE_GUARD_CORRECTION_INSTRUCTION]
    )
    return wrap_agent_payload(AgentTag.STYLE_CORRECTION, body)


def _fired_detectors(score: AiIsmScore) -> list[str]:
    return sorted(detector for detector in STYLE_GUARD_RULES if getattr(score, detector))


def _is_rich_draft(text: str) -> bool:
    """Whether ``text`` is a structured rich reply rather than chat.

    Headings, tables, and component fences are the medium of a recap or a
    report; bold inside them is formatting, not a tell. A one-liner with a
    stray ``**bold**`` is still chat and still scores.
    """
    if ":::openui" in text:
        return True
    if _RICH_HEADING_PATTERN.search(text) is not None:
        return True
    return len(_RICH_TABLE_ROW_PATTERN.findall(text)) >= 2


def _source_is_renderable(configurable: AgentConfigurable) -> bool:
    """Whether this turn serves a channel that renders markdown.

    Unknown surfaces default to renderable: ``get_comms_static_prompt``
    serves them the web prompt (Rich Chat section included), so the guard
    must judge the draft by the same rules the model wrote it under.
    """
    source = resolve_channel(configurable)
    return source is None or str(source).strip().lower() in _RENDERABLE_SOURCES


class StyleGuardMiddleware(AgentMiddleware):
    """Rewrite a comms reply that scores dirty against the AI-ism detectors.

    Comms tier only — it is registered by ``create_comms_middleware`` and
    nothing else. The executor's text is read by comms, never by a person, and
    a subagent's is read by the executor.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: ModelCallHandler,
    ) -> ModelResponse:
        response = await handler(request)
        draft = response.result[0] if response.result else None
        if not isinstance(draft, AIMessage) or draft.tool_calls:
            return response

        text = extract_text_content(draft.content)
        if not text.strip():
            return response

        configurable = agent_configurable(current_run_config())
        # A workflow delivery has no live client to retract from and nobody
        # watching it stream, so the second call would buy nothing.
        if configurable.get("execution_mode") == "background":
            return response

        # A structured rich reply (recap, report, analysis with headings,
        # tables, or charts) is content-creation output: bold and headings
        # are its medium, not tells. Scoring it would rewrite every rich
        # answer back to plain text and spend a second model call doing it.
        # Text-only platforms keep the strict guard: their prompt bans bold
        # and tables outright, so rich markup there is a real violation.
        if _is_rich_draft(text) and _source_is_renderable(configurable):
            log.set_ns(
                "style_guard",
                violations_before=0,
                violations_after=0,
                regenerated=False,
                regressed=False,
                detectors=[],
                rich_skipped=True,
            )
            return response

        before = score_reply(text)
        if before.total_violations <= STYLE_GUARD_MAX_VIOLATIONS:
            log.set_ns(
                "style_guard",
                violations_before=before.total_violations,
                violations_after=before.total_violations,
                regenerated=False,
                regressed=False,
                detectors=_fired_detectors(before),
            )
            return response

        self._retract(draft.id or "")
        retry = await handler(
            request.override(
                messages=[
                    *request.messages,
                    draft,
                    HumanMessage(content=build_correction_note(text)),
                ]
            )
        )
        rewrite = retry.result[0] if retry.result else None
        rewritten_text = (
            extract_text_content(rewrite.content) if isinstance(rewrite, AIMessage) else ""
        )
        # A rewrite that carries tool calls is the model choosing to act rather
        # than answer. It stands as-is: the graph's own preamble handling covers
        # a tool-call message whose text the user must not keep.
        rewrite_is_usable = bool(
            rewritten_text.strip() or (isinstance(rewrite, AIMessage) and rewrite.tool_calls)
        )
        if not rewrite_is_usable:
            # The second call came back with nothing — truncated, refused, or
            # dropped by the provider. The draft is already retracted and cannot
            # be un-retracted, so returning the empty rewrite would end the turn
            # in silence and persist an empty reply. The draft's text goes out
            # under the rewrite's id instead: the turn keeps a real answer, the
            # thread's history stays coherent, and the failure is loud.
            log.error(
                f"{LogTag.AGENT} Style guard rewrite came back empty; keeping the draft text",
                agent_name="comms_agent",
                violations_before=before.total_violations,
            )
            rewrite = AIMessage(
                content=draft.content,
                id=rewrite.id if isinstance(rewrite, AIMessage) else draft.id,
            )
            retry = ModelResponse(result=[rewrite])
            rewritten_text = text

        after = score_reply(rewritten_text)
        retracted_cost = await self._charge_retracted_draft(draft, configurable)
        log.set_ns(
            "style_guard",
            violations_before=before.total_violations,
            violations_after=after.total_violations,
            regenerated=True,
            regressed=after.total_violations > before.total_violations,
            detectors=_fired_detectors(before),
            retracted_cost_usd=retracted_cost,
        )
        user_id = configurable.get("user_id")
        if user_id:
            capture_event(
                str(user_id),
                AnalyticsEvents.CHAT_STYLE_GUARD_REGENERATED,
                {
                    "violations_before": before.total_violations,
                    "violations_after": after.total_violations,
                    "detectors": _fired_detectors(before),
                },
            )
        return retry

    async def _charge_retracted_draft(
        self, draft: AIMessage, configurable: AgentConfigurable
    ) -> float:
        """Bill the draft the user paid for and never saw.

        ``LLMAccountingMiddleware`` prices the run from the LAST AI message in
        state, and the retracted draft never reaches state — so without this the
        regenerated turn costs two calls and charges for one. That gap is not
        cosmetic on the free tier, where the daily budget is roughly one turn:
        an unbilled second call silently doubles real spend against a wall the
        user is already sitting at.

        The spend lands in the budget windows and under ``style_guard`` on the
        wide event. It is deliberately NOT folded into the event's ``model``
        totals, which accounting aggregates from state — the two would have to
        agree on ordering across middleware to do that safely, and the budget is
        the number that actually gates anyone.
        """
        lane = ModelLane.from_configurable(configurable.get(LANE_FIELD_ID))
        usage = extract_message_usage(draft)
        user_id = configurable.get("user_id")
        root_request_id = configurable.get("root_request_id")
        thread_id = configurable.get("thread_id")
        workflow_id = configurable.get("workflow_id")
        return await record_llm_call(
            user_id=str(user_id) if user_id else None,
            model_name=(lane.model if lane else None) or UNKNOWN_MODEL_NAME,
            usage=usage,
            root_request_id=str(root_request_id) if root_request_id else None,
            provider_cost=extract_message_cost(draft),
            context=LLMCallContext(
                agent_name="comms_agent",
                # The user asked for this turn; they just never saw this draft
                # of it. Charged, and not background — same as any comms call.
                background=False,
                charge_to_budget=True,
                model_served=extract_message_model(draft),
                provider=extract_message_provider(draft),
                generation_id=extract_generation_id(draft),
                conversation_id=(
                    str(configurable["conversation_id"])
                    if configurable.get("conversation_id")
                    else None
                ),
                thread_id=str(thread_id) if thread_id else None,
                workflow_id=str(workflow_id) if workflow_id else None,
                channel=resolve_channel(configurable),
                finish_reason=extract_finish_reason(draft),
                # ``duration_ms`` is left at its default: the draft was produced
                # by the wrapped model call that accounting timed, and this seam
                # only sees the finished message — there is no second latency to
                # report and none is invented.
            ),
        )

    def _retract(self, message_id: str) -> None:
        """Tell every live consumer to drop the draft it has already shown.

        The same frame the handoff preamble uses, on the graph's custom stream so
        it lands between the draft's tokens and the rewrite's. A run with no
        stream writer (workflows, a direct graph invoke) has nobody to tell, and
        that is normal — logged at debug, never raised.
        """
        try:
            get_stream_writer()(
                {
                    "message_boundary": MessageBoundaryPayload(
                        message_id=message_id, discarded=True
                    ).model_dump()
                }
            )
        except Exception as e:
            log.debug(
                f"{LogTag.AGENT} Style guard retraction not streamed",
                error=str(e),
                error_type=type(e).__name__,
            )
