"""
NXLYR — LLM tool schemas and handlers (Task 4.1)

The three tools TRD §3.5 (02_TRD.md:344-397) specifies for the pre-sales agent:
book_site_visit, transfer_to_human, end_call.

WHY THIS MODULE EXISTS
----------------------
Until now these three were referenced by name in the system prompt's [TOOLS]
block and nowhere else — no schemas, no handlers, nothing registered with the
LLM. The model, told it could "use book_site_visit", did the only thing it
could: narrate the booking in prose. Both real test callers on 2026-08-08 were
told a site visit was booked and a confirmation was coming; neither ever
happened, because there was no mechanism behind the words. This module is the
mechanism.

HOW REGISTRATION WORKS IN PIPECAT 1.5.0
---------------------------------------
Not via a `tools=` argument on OpenAILLMService — that parameter does not
exist on this version (OpenAILLMService.__init__ takes only model /
service_tier / params / settings, and `tools` appears nowhere in
pipecat/services/openai/llm.py). Tools belong to the LLMContext:

    LLMContext(messages=[...], tools=TOOL_SCHEMAS)

Each FunctionSchema below carries its own `handler`. On seeing the context,
LLMService._register_advertised_tool_handlers() (llm_service.py:946) calls
register_function(schema.name, schema.handler) for every schema with a
non-None handler and marks it auto_registered. That is the entire wiring —
no explicit register_function() calls, and specifically not
register_direct_function(), which is deprecated since 1.4.0 in favour of
exactly this LLMContext(tools=...) path.

Handlers receive one FunctionCallParams and return nothing; they deliver their
result by awaiting params.result_callback(result).

app_resources
-------------
Per-call state (call_sid, Redis client) reaches the handlers through
PipelineWorker(app_resources=...), surfaced as params.app_resources. Passed by
reference, not copied, so one CallResources instance is shared by every handler
invocation on that call. This is what keeps the handlers free of module-level
globals, which would be wrong the moment two calls run concurrently in the same
worker process.
"""

import asyncio
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Any

from loguru import logger

from pipecat.adapters.schemas.direct_function import tool_options
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import FunctionCallResultProperties, TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams

import commitments
from prompt import CLOSING_PHRASE

# The closing line end_call speaks. Fixed rather than model-authored, for the
# same reason prompt.build_greeting is fixed: it removes an LLM round trip from
# a moment where latency is conspicuous, and it removes the model's last
# opportunity to improvise an unbacked promise on the way out the door.
#
# Deliberately promises nothing and mentions no timeframe. The first draft of
# this line was "...and someone will be in touch shortly", which is the exact
# over-promise the [CORE RULES] block now forbids the model from making about
# transfers — and worse coming from here, because a hardcoded string says it on
# every single call regardless of outcome. It also has to be true after
# `not_interested` and `wrong_number`, where nobody is following up at all.

# Matches EXPIRE session:call:{call_id} 14400 in 03_SOFTWARE_FLOW.md:87. Set
# here because nothing else currently creates the session hash (see
# CallResources.session_key), so if this module doesn't expire the key, nothing
# will and it leaks for the lifetime of the Redis volume.
SESSION_TTL_SECONDS = 14400
FLAGS_TIMEOUT_S = 0.25
_IN_FLIGHT_COMMITMENTS: set[asyncio.Task[Any]] = set()


@dataclass
class CallResources:
    """Per-call state handed to tool handlers via FunctionCallParams.app_resources.

    One instance per call, constructed in bot.run_bot() and passed to
    PipelineWorker(app_resources=...).

    Attributes:
        call_sid: Exotel's call identifier for this leg.
        redis: An awaitable redis.asyncio client, or None when Redis is
            unreachable/unconfigured (see make_redis_client below). Handlers must
            tolerate None — a missing Redis degrades post-call analytics, but it
            must never be the reason a live call fails.
    """

    call_sid: str | None
    redis: Any | None = None
    http_session: Any | None = None
    lead_phone: str | None = None
    booking_attempts: int = 0

    @property
    def session_key(self) -> str:
        """The Redis session hash key for this call.

        03_SOFTWARE_FLOW.md:70 specifies `session:call:{call_id}`, where call_id
        is the internal calls-table UUID minted by Flow 1's call-worker. That
        worker is Week 5 and does not exist yet, so the only identifier
        available inside a live call is Exotel's call_sid (bot.py reads it off
        the `start` event). We key on call_sid and keep the spec'd key shape.

        HANDOFF NOTE FOR WEEK 5: when Flow 1's call-worker lands and starts
        HSET-ing the real session hash, this must switch to the call_id UUID,
        and Flow 3's webhook handler must read the same key. Until then this
        HSET *creates* the hash rather than updating an existing one, which is
        why the write path below also sets an EXPIRE that Flow 1 would
        otherwise own.
        """
        return f"session:call:{self.call_sid}"


def _resources(params: FunctionCallParams) -> CallResources | None:
    """Pull CallResources off a function call, or None if the call has none.

    prompt_harness.py drives these handlers without a PipelineWorker, so
    app_resources is legitimately absent there.
    """
    resources = params.app_resources
    return resources if isinstance(resources, CallResources) else None


async def _set_session_flags(
    resources: CallResources | None,
    fields: dict[str, str],
    *,
    if_absent: tuple[str, ...] = (),
) -> bool:
    """Write one tool's Redis fields atomically, best-effort."""
    started = monotonic()
    field_names = ",".join(sorted(fields))
    if resources is None or resources.redis is None:
        logger.warning(
            "flags write FAILED call_sid={} fields={} error_type={} ms={}",
            resources.call_sid if resources else None,
            field_names,
            "Unavailable",
            max(0, int((monotonic() - started) * 1000)),
        )
        return False

    try:
        pipeline = resources.redis.pipeline(transaction=True)
        regular = {key: value for key, value in fields.items() if key not in if_absent}
        if regular:
            pipeline.hset(resources.session_key, mapping=regular)
        for field in if_absent:
            if field in fields:
                pipeline.hsetnx(resources.session_key, field, fields[field])
        pipeline.expire(resources.session_key, SESSION_TTL_SECONDS)
        async with asyncio.timeout(FLAGS_TIMEOUT_S):
            await pipeline.execute()
        logger.info(
            "flags write ok call_sid={} fields={} ms={}",
            resources.call_sid,
            field_names,
            max(0, int((monotonic() - started) * 1000)),
        )
        return True
    except Exception as error:
        logger.error(
            "flags write FAILED call_sid={} fields={} error_type={} ms={}",
            resources.call_sid,
            field_names,
            type(error).__name__,
            max(0, int((monotonic() - started) * 1000)),
        )
        return False


def _pre_call_text(params: FunctionCallParams) -> tuple[int | None, str]:
    context = params.context
    if context is None:
        return None, "unknown"
    try:
        messages = context.get_messages()
        assistant = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, dict) and message.get("role") == "assistant"
            ),
            None,
        )
        if assistant is None:
            return 0, "no"
        content = assistant.get("content")
        text = content if isinstance(content, str) else ""
    except Exception:
        return None, "unknown"
    done = bool(re.search(r"\b(?:booked|confirmed|done)\b", text, re.IGNORECASE))
    return len(text), "yes" if done else "no"


def _log_pre_call(params: FunctionCallParams, tool_name: str, call_sid: str | None) -> None:
    length, done_word = _pre_call_text(params)
    chars = "unknown" if length is None else str(length)
    logger.info(
        "TOOL {} pre_call_text_chars={} pre_call_done_word={} call_sid={}",
        tool_name,
        chars,
        done_word,
        call_sid,
    )


async def _fixed_result(
    params: FunctionCallParams, result: dict[str, Any], sentence: str
) -> None:
    worker = params.pipeline_worker
    if worker is not None:
        await worker.queue_frames([TTSSpeakFrame(sentence, append_to_context=True)])
    else:
        logger.warning("fixed tool sentence not queued: no pipeline worker")
    await params.result_callback(
        result,
        properties=FunctionCallResultProperties(run_llm=False),
    )


def _start_commitment_workflow(commit_awaitable: Any, after_alert: Any) -> asyncio.Future:
    """Hold commit through finalization while publishing its post-alert result."""
    loop = asyncio.get_running_loop()
    result_ready = loop.create_future()

    def consume_unobserved_result(done: asyncio.Future) -> None:
        if not done.cancelled():
            done.exception()

    result_ready.add_done_callback(consume_unobserved_result)

    async def workflow() -> None:
        try:
            result = await commit_awaitable
        except Exception as error:
            if not result_ready.done():
                result_ready.set_exception(error)
            return

        if not result_ready.done():
            result_ready.set_result(result)
        try:
            await after_alert(result)
        except Exception as error:
            logger.warning(
                "commitment finalize FAILED error_type={}", type(error).__name__
            )

    task = asyncio.create_task(workflow())
    _IN_FLIGHT_COMMITMENTS.add(task)

    def workflow_finished(done: asyncio.Task[Any]) -> None:
        _IN_FLIGHT_COMMITMENTS.discard(done)
        try:
            error = done.exception()
        except asyncio.CancelledError:
            error = None
        if error is not None:
            logger.warning(
                "commitment background FAILED error_type={}", type(error).__name__
            )

    task.add_done_callback(workflow_finished)
    return result_ready


# ---------------------------------------------------------------------------
# book_site_visit
# ---------------------------------------------------------------------------


# cancel_on_interruption=False. The default is True, which means an
# InterruptionFrame cancels every in-flight function call
# (llm_service.py:626-629). Our barge-in setup arms both VAD and transcription
# turn-start strategies with enable_interruptions=True (bot.py), so on a noisy
# Indian mobile line interruptions fire readily — and a caller saying "yeah,
# great" over the bot's confirmation would cancel the very booking they just
# agreed to. That reproduces the 2026-08-08 failure exactly: told it was
# booked, nothing happened. A tool that writes real state must not be
# cancellable by the caller making an approving noise.
#
# Side effect of False: the call becomes asynchronous — the LLM continues the
# conversation immediately and the result is injected later as a developer
# message. That is the right trade here. The booking is not something the
# caller waits in silence for.
@tool_options(cancel_on_interruption=False)
async def book_site_visit(params: FunctionCallParams) -> None:
    """Store and alert a visit before reporting it as booked."""
    resources = _resources(params)
    preferred_date = params.arguments.get("preferred_date")
    preferred_time = params.arguments.get("preferred_time")
    notes = params.arguments.get("notes")
    call_sid = resources.call_sid if resources else None
    _log_pre_call(params, "book_site_visit", call_sid)

    if not call_sid:
        logger.warning("TOOL book_site_visit REJECTED reason=missing_call_sid")
        await _fixed_result(
            params,
            {"status": "not_confirmed", "say": commitments.BOOKING_NOT_CONFIRMED},
            commitments.BOOKING_NOT_CONFIRMED,
        )
        return

    parsed = commitments.parse_visit(preferred_date, preferred_time)
    if isinstance(parsed, commitments.VisitError):
        logger.warning(
            "TOOL book_site_visit REJECTED reason={} call_sid={}",
            parsed.reason,
            call_sid,
        )
        await _fixed_result(
            params,
            {"status": "error", "reason": parsed.reason, "say": parsed.say},
            parsed.say,
        )
        return
    visit_date, visit_time = parsed
    lookup_previous = bool(resources and resources.booking_attempts > 0)
    if resources:
        resources.booking_attempts += 1
    async def after_alert(result: commitments.CommitResult) -> None:
        await commitments.finalize_visit(
            resources.http_session if resources else None,
            call_sid=call_sid,
            result=result,
        )
        await _set_session_flags(
            resources,
            {
                "end_call_tool_invoked": "false",
                "site_visit_booked": "true",
                "site_visit_date": visit_date.isoformat(),
            },
            if_absent=("end_call_tool_invoked",),
        )

    result_ready = _start_commitment_workflow(
        commitments.commit_visit(
            resources.http_session if resources else None,
            project_slug=commitments.PROJECT_SLUG,
            call_sid=call_sid,
            visit_date=visit_date,
            visit_time=visit_time,
            notes=notes,
            phone=resources.lead_phone if resources else None,
            lookup_previous=lookup_previous,
        ),
        after_alert,
    )
    try:
        result = await asyncio.shield(result_ready)
    except commitments.AlertError as error:
        logger.error(
            "commitment FAILED stage=alert call_sid={} error_type={} http_status={} db_ms={} tg_ms={}",
            call_sid,
            type(error).__name__,
            error.status,
            error.db_ms,
            error.tg_ms,
        )
        await _fixed_result(
            params,
            {"status": "not_confirmed", "say": commitments.BOOKING_NOT_CONFIRMED},
            commitments.BOOKING_NOT_CONFIRMED,
        )
        return
    except commitments.CommitmentError as error:
        logger.error(
            "commitment FAILED stage={} call_sid={} error_type={} http_status={} db_ms={} tg_ms={}",
            error.stage,
            call_sid,
            type(error).__name__,
            error.status,
            error.db_ms,
            error.tg_ms,
        )
        await _fixed_result(
            params,
            {"status": "not_confirmed", "say": commitments.BOOKING_NOT_CONFIRMED},
            commitments.BOOKING_NOT_CONFIRMED,
        )
        return

    visit_text = f"{visit_date:%A}, {visit_date.day} {visit_date:%B}, {visit_time:%H:%M} IST"
    payload = {
        "status": "booked",
        "reference": result.reference,
        "visit": visit_text,
        "alert": "sent",
        "next_step": (
            "Confirm the day and time in one sentence; you may say the team has "
            "been told. Give no time for a follow-up and keep the call going."
        ),
    }
    if result.replaces:
        replaced = "; ".join(
            f"{item.visit_date:%A}, {item.visit_date.day} {item.visit_date:%B}, "
            f"{item.visit_time:%H:%M}"
            for item in result.replaces
        )
        payload["replaces"] = replaced
        payload["next_step"] = (
            "Confirm the new day and time in one sentence and say it replaces the "
            "earlier booking; you may say the team has been told. Give no time for "
            "a follow-up."
        )
    logger.info("TOOL book_site_visit result status=booked call_sid={}", call_sid)
    await params.result_callback(payload)


BOOK_SITE_VISIT_SCHEMA = FunctionSchema(
    name="book_site_visit",
    description=(
        "Call this when the lead has explicitly agreed to a site visit and given a "
        "day or time. Booking a visit does not end the call: keep talking."
    ),
    properties={
        "preferred_date": {"type": "string", "description": "YYYY-MM-DD"},
        "preferred_time": {"type": "string", "description": "HH:MM in 24h format"},
        "notes": {"type": "string"},
    },
    required=["preferred_date", "preferred_time"],
    handler=book_site_visit,
)


# ---------------------------------------------------------------------------
# transfer_to_human
# ---------------------------------------------------------------------------


# cancel_on_interruption=False for the same reason as book_site_visit: this
# tool has a real-world consequence (a human gets pulled onto the call) and a
# half-executed transfer is worse than either outcome. A caller who keeps
# talking while the handoff is arranged must not silently un-arrange it.
@tool_options(cancel_on_interruption=False)
async def transfer_to_human(params: FunctionCallParams) -> None:
    """Store and alert a callback request before reporting it as passed on."""
    resources = _resources(params)
    reason = params.arguments.get("reason")
    context_summary = params.arguments.get("context_summary")
    call_sid = resources.call_sid if resources else None
    _log_pre_call(params, "transfer_to_human", call_sid)
    if not call_sid:
        logger.warning("TOOL transfer_to_human REJECTED reason=missing_call_sid")
        await _fixed_result(
            params,
            {"status": "not_passed_on", "say": commitments.CALLBACK_NOT_PASSED_ON},
            commitments.CALLBACK_NOT_PASSED_ON,
        )
        return
    notes = " — ".join(str(value) for value in (reason, context_summary) if value)
    async def after_alert(result: commitments.CommitResult) -> None:
        await commitments.finalize_callback(
            resources.http_session if resources else None,
            call_sid=call_sid,
            result=result,
        )
        await _set_session_flags(
            resources,
            {
                "transfer_requested": "true",
                "transfer_reason": str(reason or "")[:500],
            },
        )

    result_ready = _start_commitment_workflow(
        commitments.commit_callback(
            resources.http_session if resources else None,
            project_slug=commitments.PROJECT_SLUG,
            call_sid=call_sid,
            notes=notes,
            phone=resources.lead_phone if resources else None,
        ),
        after_alert,
    )
    try:
        result = await asyncio.shield(result_ready)
    except commitments.AlertError as error:
        logger.error(
            "commitment FAILED stage=alert call_sid={} error_type={} http_status={} db_ms={} tg_ms={}",
            call_sid,
            type(error).__name__,
            error.status,
            error.db_ms,
            error.tg_ms,
        )
        await _fixed_result(
            params,
            {"status": "not_passed_on", "say": commitments.CALLBACK_NOT_PASSED_ON},
            commitments.CALLBACK_NOT_PASSED_ON,
        )
        return
    except commitments.CommitmentError as error:
        logger.error(
            "commitment FAILED stage={} call_sid={} error_type={} http_status={} db_ms={} tg_ms={}",
            error.stage,
            call_sid,
            type(error).__name__,
            error.status,
            error.db_ms,
            error.tg_ms,
        )
        await _fixed_result(
            params,
            {"status": "not_passed_on", "say": commitments.CALLBACK_NOT_PASSED_ON},
            commitments.CALLBACK_NOT_PASSED_ON,
        )
        return

    logger.info("TOOL transfer_to_human result status=passed_on call_sid={}", call_sid)
    await params.result_callback(
        {
            "status": "passed_on",
            "reference": result.reference,
            "alert": "sent",
            "bridge_connected": False,
            "next_step": (
                'Say exactly: "I\'ve passed your question to a colleague. I can\'t '
                'connect you now, but they have it." Give no time. Do not offer to connect.'
            ),
        }
    )


TRANSFER_TO_HUMAN_SCHEMA = FunctionSchema(
    name="transfer_to_human",
    description=(
        "Call this when the lead asks something outside your scope — legal "
        "questions, negotiation, complaints, or requests to speak with a manager."
    ),
    properties={
        "reason": {"type": "string"},
        "context_summary": {"type": "string"},
    },
    required=["reason", "context_summary"],
    handler=transfer_to_human,
)


# ---------------------------------------------------------------------------
# end_call
# ---------------------------------------------------------------------------

END_CALL_OUTCOMES = [
    "site_visit_booked",
    "qualified_interested",
    "follow_up_needed",
    "not_interested",
    "wrong_number",
]


# Left at the default cancel_on_interruption=True, unlike the other two. There
# is nothing to lose by letting a barge-in cancel an end-call attempt — a
# caller who starts speaking mid-goodbye is giving a legitimate reason not to
# hang up on them.
async def end_call(params: FunctionCallParams) -> None:
    """Close the conversation cleanly: speak a fixed goodbye, then end the call.

    ORDERING — this is the part that is easy to get wrong.

    PipelineWorker.stop_when_done() queues an EndFrame. EndFrame is a
    ControlFrame, so it is processed in queue order and flows *behind* audio
    already queued — which is what we want. But calling it inline here would
    still truncate the goodbye, because at the moment this handler runs the
    closing phrase does not exist yet: with run_llm=True it would come from a
    second LLM turn that only starts after the handler returns, so the EndFrame
    would be queued ahead of it and cut the caller off mid-sentence — the
    mirror image of the bug we are fixing.

    So instead: push a fixed CLOSING_PHRASE as a TTSSpeakFrame now, return with
    run_llm=False (no second LLM turn to wait for or to be surprised by), and
    hang stop_when_done() off on_context_updated, which fires once the tool
    result has been folded into the context. The EndFrame is then queued behind
    the goodbye audio and the pipeline drains in order.

    The alternative — model-authored goodbye, shutdown hung off
    on_bot_stopped_speaking — buys slightly more natural wording at the cost of
    an extra turn of latency and one more chance for the model to improvise a
    promise. prompt.build_greeting already set the precedent for fixing the
    words at the edges of the call.
    """
    resources = _resources(params)
    outcome = params.arguments.get("outcome")
    summary = params.arguments.get("summary")

    outcome_kind = outcome if outcome in END_CALL_OUTCOMES else "other"
    logger.info(
        "TOOL end_call call_sid={} outcome={} summary_chars={}",
        resources.call_sid if resources else None,
        outcome_kind,
        len(str(summary or "")),
    )

    worker = params.pipeline_worker
    if worker is None:
        logger.warning("end_call: no pipeline_worker available — cannot end the call")
        await params.result_callback(
            {"status": "ended", "outcome": outcome},
            properties=FunctionCallResultProperties(run_llm=False),
        )
        return

    await worker.queue_frames([TTSSpeakFrame(CLOSING_PHRASE)])

    async def _stop_pipeline() -> None:
        fields = {"end_call_tool_invoked": "true"}
        if outcome:
            fields["call_outcome"] = str(outcome)
        await _set_session_flags(resources, fields)
        logger.info(
            f"end_call: goodbye queued, scheduling pipeline stop "
            f"(call_sid={resources.call_sid if resources else None})"
        )
        await worker.stop_when_done()

    await params.result_callback(
        {"status": "ended", "outcome": outcome},
        properties=FunctionCallResultProperties(
            run_llm=False,
            on_context_updated=_stop_pipeline,
        ),
    )


END_CALL_SCHEMA = FunctionSchema(
    name="end_call",
    description=(
        "Hang up on the caller. Call this only when the caller's latest message says "
        "goodbye, says they are finished, asks to end the call, or says it is a wrong "
        "number. Never in the same turn as another function, and never in the turn "
        "after a function result unless the caller's latest message already said "
        "goodbye. A booking, a passed-on question or a finished answer is not a reason."
    ),
    properties={
        "outcome": {
            "type": "string",
            "enum": END_CALL_OUTCOMES,
            "description": (
                "How the call went so far. site_visit_booked only if a visit was "
                "booked earlier on this call. It is not a reason to hang up."
            ),
        },
        "summary": {"type": "string"},
    },
    required=["outcome"],
    handler=end_call,
)


# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [BOOK_SITE_VISIT_SCHEMA, TRANSFER_TO_HUMAN_SCHEMA, END_CALL_SCHEMA]

# Name -> handler, for callers that dispatch tool calls themselves rather than
# going through Pipecat's registry (prompt_harness.py). Derived from
# TOOL_SCHEMAS rather than written out again, so the harness cannot drift from
# what production advertises.
TOOL_HANDLERS = {schema.name: schema.handler for schema in TOOL_SCHEMAS}


def openai_tool_params() -> list[dict]:
    """TOOL_SCHEMAS in OpenAI chat-completions `tools=` format.

    For direct OpenAI SDK callers (prompt_harness.py). Mirrors what
    OpenAILLMAdapter.to_provider_tools_format() does for the production path
    (open_ai_adapter.py:156-173) — same FunctionSchema objects, same
    to_default_dict(), so the harness sends the model byte-identical tool
    definitions to the ones a real call sends.
    """
    return [
        {"type": "function", "function": schema.to_default_dict()}
        for schema in TOOL_SCHEMAS
    ]


async def make_redis_client() -> Any | None:
    """Connect to Redis from REDIS_URL, or return None if that isn't possible.

    The project's first real Redis client — redis exists as a container in
    docker-compose.yml and the agent already depends_on it, but no Python code
    has touched it before now.

    Returns None rather than raising on a missing REDIS_URL or an unreachable
    server, for the reason given on _set_session_flags: the session flag is
    valuable, but not so valuable that a live sales call should die for it.
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        logger.warning(
            "REDIS_URL is not set — session flags (including "
            "end_call_tool_invoked) will not be written for this call"
        )
        return None

    client = None
    try:
        import redis.asyncio as redis_asyncio

        client = redis_asyncio.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=2.0,
        )
        await asyncio.wait_for(client.ping(), timeout=1.0)
        logger.info("Redis connected")
        return client
    except Exception as error:
        if client is not None:
            with suppress(Exception):
                await asyncio.wait_for(client.aclose(), timeout=1.0)
        logger.error(
            f"Could not connect to Redis: {error} — session flags "
            "will not be written for this call"
        )
        return None
