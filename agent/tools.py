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

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from loguru import logger

from pipecat.adapters.schemas.direct_function import tool_options
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import FunctionCallResultProperties, TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams

# Matches EXPIRE session:call:{call_id} 14400 in 03_SOFTWARE_FLOW.md:87. Set
# here because nothing else currently creates the session hash (see
# CallResources.session_key), so if this module doesn't expire the key, nothing
# will and it leaks for the lifetime of the Redis volume.
SESSION_TTL_SECONDS = 14400

# The closing line end_call speaks. Fixed rather than model-authored, for the
# same reason bot.GREETING is fixed: it removes an LLM round trip from a moment
# where latency is conspicuous, and it removes the model's last opportunity to
# improvise an unbacked promise on the way out the door.
#
# Deliberately promises nothing and mentions no timeframe. The first draft of
# this line was "...and someone will be in touch shortly", which is the exact
# over-promise the [TOOLS] block now forbids the model from making about
# transfers — and worse coming from here, because a hardcoded string says it on
# every single call regardless of outcome. It also has to be true after
# `not_interested` and `wrong_number`, where nobody is following up at all.
CLOSING_PHRASE = "Thanks for your time — that's everything I needed. Have a good day."


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


async def _set_session_flag(
    resources: CallResources | None, field: str, value: str
) -> None:
    """HSET one field on the call's Redis session hash, best-effort.

    Deliberately swallows every Redis error after logging it. This is the
    opposite of kb_loader.load_kb()'s fail-loud policy, and the difference is
    intentional: a call cannot proceed without its KB, but it proceeds fine
    without an analytics flag. Letting a Redis blip abort a live conversation
    with a real buyer would be a far worse failure than the degraded drop
    classification we get from a missing flag.
    """
    if resources is None or resources.redis is None:
        logger.warning(
            f"No Redis client available — skipping {field}={value} "
            f"(call_sid={resources.call_sid if resources else None})"
        )
        return

    try:
        await resources.redis.hset(resources.session_key, field, value)
        # Re-applied on every write rather than set once: the hash may not have
        # existed before the first HSET (see CallResources.session_key), and
        # re-arming a 4h TTL mid-call is harmless.
        await resources.redis.expire(resources.session_key, SESSION_TTL_SECONDS)
        logger.info(f"Redis {resources.session_key} {field}={value}")
    except Exception as e:
        logger.error(
            f"Failed to set {field}={value} on {resources.session_key}: {e} "
            "— call continues, post-call classification will be degraded"
        )


# ---------------------------------------------------------------------------
# book_site_visit
# ---------------------------------------------------------------------------


def _validate_visit_date(preferred_date: Any) -> str | None:
    """Return an error string if preferred_date isn't a usable future date.

    Returns None when the date is fine. Today counts as valid — a caller can
    legitimately ask to visit this afternoon.
    """
    if not preferred_date:
        return "preferred_date is required"
    try:
        parsed = date.fromisoformat(str(preferred_date))
    except ValueError:
        return (
            f"preferred_date {preferred_date!r} is not a valid YYYY-MM-DD date. "
            "Ask the caller to confirm the day and call again."
        )
    today = date.today()
    if parsed < today:
        return (
            f"preferred_date {parsed.isoformat()} is in the past (today is "
            f"{today.isoformat()}). Confirm the intended date with the caller "
            "and call again."
        )
    return None


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
    """Record a site visit the lead has agreed to.

    Persistence to the leads table (UPDATE lead SET status='site_visit_booked',
    site_visit_date=...) is Flow 2's job (03_SOFTWARE_FLOW.md:187-190) and
    depends on the Supabase call/lead records that Week 5's call-worker
    creates. Until those exist this logs the booking as a structured event and
    reports success to the model, so the confirmation the bot speaks is at
    least backed by a real, greppable record rather than by nothing at all.
    """
    resources = _resources(params)
    preferred_date = params.arguments.get("preferred_date")
    preferred_time = params.arguments.get("preferred_time")
    notes = params.arguments.get("notes")

    logger.info(
        f"TOOL book_site_visit — call_sid={resources.call_sid if resources else None} "
        f"date={preferred_date!r} time={preferred_time!r} notes={notes!r}"
    )

    # Belt and braces behind the [CURRENT DATE] prompt block. The first Task
    # 4.1 harness run had gpt-4o resolve "Saturday the 15th of August" to
    # 2024-08-15 — well-formed and two years stale — because nothing in the
    # prompt told it what day it was. The prompt block is the actual fix; this
    # is the guard that stops a regression there from being invisible, since a
    # past-dated booking looks exactly like a good one in the logs.
    #
    # Refuses rather than warns: the whole point of this task is that the bot
    # must not confirm bookings that aren't real. Returning an error gives the
    # model a chance to re-ask the caller, which is the honest recovery.
    date_error = _validate_visit_date(preferred_date)
    if date_error:
        logger.error(
            f"TOOL book_site_visit REJECTED — {date_error} "
            f"(call_sid={resources.call_sid if resources else None})"
        )
        await params.result_callback({"status": "error", "error": date_error})
        return

    # Explicitly false, not merely absent. 03_SOFTWARE_FLOW.md:190 calls this
    # out: a booking is not a call ending — the conversation may well continue
    # after it — so Flow 3 must not read a successful booking as a clean close.
    await _set_session_flag(resources, "end_call_tool_invoked", "false")
    await _set_session_flag(resources, "site_visit_booked", "true")
    if preferred_date:
        await _set_session_flag(resources, "site_visit_date", str(preferred_date))

    await params.result_callback(
        {
            "status": "booked",
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
        }
    )


BOOK_SITE_VISIT_SCHEMA = FunctionSchema(
    name="book_site_visit",
    description=(
        "Call this when the lead has explicitly agreed to a site visit and "
        "provided a date or time preference."
    ),
    properties={
        "preferred_date": {"type": "string", "description": "YYYY-MM-DD"},
        "preferred_time": {"type": "string", "description": "HH:MM in 24h format"},
        "notes": {"type": "string"},
    },
    required=["preferred_date"],
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
    """Hand the call off to a human agent.

    The actual Exotel call bridge (03_SOFTWARE_FLOW.md:192-195) needs a
    configured human-agent DID and Exotel's bridge API, neither of which is
    wired up yet. Logging the transfer request with its full context summary is
    the honest interim behaviour: the model gets a truthful "requested, not yet
    connected" result rather than a fabricated success, so it says something it
    can actually stand behind.
    """
    resources = _resources(params)
    reason = params.arguments.get("reason")
    context_summary = params.arguments.get("context_summary")

    logger.info(
        f"TOOL transfer_to_human — call_sid={resources.call_sid if resources else None} "
        f"reason={reason!r} context_summary={context_summary!r}"
    )

    await _set_session_flag(resources, "transfer_requested", "true")
    if reason:
        await _set_session_flag(resources, "transfer_reason", str(reason))

    # next_step spells out in the result what bridge_connected=False implies,
    # rather than leaving the model to infer it. On the first Task 4.1 harness
    # run it read the honest `bridge_connected: false` and still told the
    # caller "they'll be reaching out to you shortly" — nobody was going to.
    # The [TOOLS] prompt block is the primary fix; this puts the same
    # correction directly in the model's context at the moment it composes the
    # handoff sentence.
    await params.result_callback(
        {
            "status": "transfer_requested",
            "bridge_connected": False,
            "reason": reason,
            "next_step": (
                "Logged for a colleague to pick up. Nobody is on the line and "
                "no callback is scheduled yet — tell the caller a colleague "
                "will get back to them, and do not promise a timeframe."
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
    promise. bot.GREETING already set the precedent for fixing the words at the
    edges of the call.
    """
    resources = _resources(params)
    outcome = params.arguments.get("outcome")
    summary = params.arguments.get("summary")

    logger.info(
        f"TOOL end_call — call_sid={resources.call_sid if resources else None} "
        f"outcome={outcome!r} summary={summary!r}"
    )

    # THE FLAG. Scoped in Week 3 planning (06_IMPLEMENTATION_PLAN.md:107) and
    # again in Week 4 (line 257), never implemented until now. Flow 3's webhook
    # handler (03_SOFTWARE_FLOW.md:256-262) branches on it: call.completed with
    # the flag true is a CLEAN_COMPLETION; call.completed with it false is a
    # DROP, duration-classified into drop_type 1-4 and potentially scheduled for
    # a resumption call. Without this write every clean bot-initiated ending
    # would be misfiled as a dropped call and the lead re-dialled for no reason.
    #
    # Written before the goodbye is spoken, deliberately: if the carrier tears
    # the leg down during the closing phrase, the ending was still clean and the
    # flag should already say so.
    await _set_session_flag(resources, "end_call_tool_invoked", "true")
    if outcome:
        await _set_session_flag(resources, "call_outcome", str(outcome))

    # No PipelineWorker under prompt_harness.py — the flag write and the
    # outcome logging above are the testable part there; the shutdown is not.
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
        "Call this to gracefully close the conversation after achieving a "
        "clear outcome."
    ),
    properties={
        "outcome": {"type": "string", "enum": END_CALL_OUTCOMES},
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
    server, for the reason given on _set_session_flag: the session flag is
    valuable, but not so valuable that a live sales call should die for it.
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        logger.warning(
            "REDIS_URL is not set — session flags (including "
            "end_call_tool_invoked) will not be written for this call"
        )
        return None

    try:
        import redis.asyncio as redis_asyncio

        client = redis_asyncio.from_url(redis_url, decode_responses=True)
        await client.ping()
        logger.info(f"Redis connected ({redis_url})")
        return client
    except Exception as e:
        logger.error(
            f"Could not connect to Redis at {redis_url}: {e} — session flags "
            "will not be written for this call"
        )
        return None
