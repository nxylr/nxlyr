"""
NXLYR — Exotel webhook + media-stream server (Week 3 / Task 2.4)

Four routes:

  GET  /health — liveness probe for the container HEALTHCHECK.
  POST /start  — initiate an outbound call via Exotel's Connect API.
  POST /demo/call — rate-limited, public demo wrapper around /start's call path.
  WS   /ws     — the endpoint Exotel's App Bazaar "Voicebot" applet connects to.
                 Accepts the socket and hands it to bot.run_bot() for the
                 lifetime of one call.

Structure follows pipecat-examples/exotel-chatbot/outbound/server.py. Deviations
from that reference are called out in comments where they occur.

Run locally:  python server.py       (or: uvicorn server:app --host 0.0.0.0 --port 7860)
"""

import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

# Imported from starlette rather than fastapi. FastAPI re-exports this exact
# class (the two names are the same object), but the exception is raised by
# starlette's WebSocket.send, so importing it from the module that raises it
# keeps the provenance obvious to anyone tracing the except clause below.
from starlette.websockets import WebSocketDisconnect

load_dotenv(override=True)

# Imported at module scope, unlike the reference which imports bot inside the
# WebSocket handler. We want a missing dependency or a broken import to kill the
# process at boot, not to surface as a dropped call on a live customer.
from bot import run_bot


E164_PHONE_NUMBER = re.compile(r"^\+[1-9]\d{1,14}$")
DEMO_PHONE_LIMIT = 5
DEMO_GLOBAL_LIMIT = 50
DEMO_RATE_LIMIT_TTL_SECONDS = 24 * 60 * 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage long-lived resources across the FastAPI app lifecycle.

    Creates a shared aiohttp.ClientSession on app.state.session at boot and closes
    it cleanly on shutdown. The Redis connection used by /demo/call is opened
    lazily, because health checks must not fail just because Redis is restarting.
    """
    logger.info("Initializing shared aiohttp.ClientSession on app.state.session")
    app.state.session = aiohttp.ClientSession()
    try:
        yield
    finally:
        logger.info("Closing shared aiohttp.ClientSession")
        await app.state.session.close()
        redis_client = getattr(app.state, "redis", None)
        if redis_client is not None:
            logger.info("Closing shared Redis client")
            await redis_client.aclose()


app = FastAPI(title="NXLYR Exotel Agent", lifespan=lifespan)

# No CORSMiddleware here, deliberately. The reference adds a permissive
# allow_origins=["*"] block for browser testing, but /start and the Exotel
# webhook/media-stream callers are server-side and must not receive browser CORS
# access. The public /demo/call route is the sole exception: its narrowly scoped
# CORS headers are handled one layer up in infra/nginx/api.infrasmith.dev.conf,
# where only https://nxlyr.vercel.app may POST to that route.


class StartCallRequest(BaseModel):
    phone_number: str | None = Field(
        default=None,
        description="Target customer phone number (e.g. +919876500000)",
    )
    dialout_settings: dict | None = Field(
        default=None,
        description="Optional nested dialout settings dict containing phone_number",
    )


class DemoCallRequest(BaseModel):
    """The intentionally small public contract for the landing-page demo."""

    # Any lets this route return its documented 400 JSON response for a number
    # supplied as (for example) null or a JSON number, rather than FastAPI
    # rejecting the request before the endpoint can explain the problem.
    phone_number: Any = Field(default=None)


# ----------------- API ----------------- #


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness only — is the ASGI app serving?

    Deliberately checks nothing else. No Deepgram/OpenAI/ElevenLabs reachability,
    no credential validation: a readiness check that calls third-party APIs turns
    every upstream blip into a container restart, which is worse than the blip.
    Boot-time failures (missing keys, bad imports) already crash the process
    before this route can answer.
    """
    return JSONResponse(status_code=200, content={"status": "ok"})


async def trigger_exotel_call(request: Request, phone_number: str) -> JSONResponse:
    """Use the existing Exotel Connect API path to trigger one outbound call.

    GREETING TIMING CITATION (Task 5.3):
    Official Exotel Connect to Call Flow API documentation:
    https://developer.exotel.com/api/outgoing-call-to-connect-number-to-a-call-flow
    Exotel's Connect-to-Url API dials the customer number ('From') first. When the
    customer picks up, Exotel executes the App Bazaar Voicebot flow, which opens
    the /ws WebSocket connection to our bot. Because the customer is already on
    the line when on_client_connected fires in bot.py, triggering the bot's
    greeting immediately on connection is correct for this flow.
    """
    sid = os.getenv("EXOTEL_SID")
    api_key = os.getenv("EXOTEL_API_KEY")
    api_token = os.getenv("EXOTEL_API_TOKEN")
    caller_id = os.getenv("EXOTEL_PHONE_NUMBER")
    app_id = os.getenv("EXOTEL_APP_ID")
    status_callback = os.getenv("EXOTEL_STATUS_CALLBACK_URL")

    missing = [
        var_name
        for var_name, val in [
            ("EXOTEL_SID", sid),
            ("EXOTEL_API_KEY", api_key),
            ("EXOTEL_API_TOKEN", api_token),
            ("EXOTEL_PHONE_NUMBER", caller_id),
            ("EXOTEL_APP_ID", app_id),
        ]
        if not val
    ]

    if missing:
        logger.error(f"Missing required Exotel environment variables: {missing}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": "missing_credentials",
                "detail": f"Missing required Exotel environment variables: {', '.join(missing)}",
            },
        )

    url = f"https://api.exotel.com/v1/Accounts/{sid}/Calls/connect.json"
    flow_url = f"https://my.exotel.com/{sid}/exoml/start_voice/{app_id}"

    data = {
        "From": phone_number,
        "CallerId": caller_id,
        "Url": flow_url,
    }
    # Pass StatusCallback webhook URL if configured in env
    if status_callback:
        data["StatusCallback"] = status_callback


    auth = aiohttp.BasicAuth(login=api_key, password=api_token)
    session: aiohttp.ClientSession = request.app.state.session

    try:
        async with session.post(url, data=data, auth=auth) as resp:
            resp_text = await resp.text()
            try:
                res_data = await resp.json()
            except Exception:
                res_data = None

            if resp.status == 200 and isinstance(res_data, dict) and "Call" in res_data:
                call_sid = res_data["Call"].get("Sid")
                logger.info(f"Outbound call initiated via Exotel: CallSid={call_sid}")
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "success",
                        "call_sid": call_sid,
                        "data": res_data["Call"],
                    },
                )
            else:
                logger.warning(
                    f"Exotel Connect API returned status {resp.status}: {resp_text}"
                )
                return JSONResponse(
                    status_code=resp.status,
                    content={
                        "status": "error",
                        "exotel_status": resp.status,
                        "detail": res_data or resp_text,
                    },
                )
    except Exception as e:
        logger.exception("Failed to connect to Exotel API")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": "exotel_connection_failed",
                "detail": str(e),
            },
        )


@app.post("/start")
async def initiate_outbound_call(
    request: Request, body: StartCallRequest
) -> JSONResponse:
    """Initiate an outbound call via Exotel's Connect API.

    Accepts {"phone_number": "..."} or {"dialout_settings": {"phone_number": "..."}}.
    The Exotel request is delegated to trigger_exotel_call(), which is also the
    only call path used by the public demo endpoint.
    """
    phone_number = body.phone_number
    if not phone_number and body.dialout_settings:
        phone_number = body.dialout_settings.get("phone_number")

    if not phone_number:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": "invalid_request",
                "detail": "Field 'phone_number' is required.",
            },
        )

    return await trigger_exotel_call(request, phone_number)


async def get_demo_redis_client(request: Request) -> Any:
    """Return the shared Redis client used to enforce demo-call limits.

    This follows tools.make_redis_client's redis.asyncio/from_url/decode_responses
    pattern. Unlike call-session analytics, rate limiting is a safety boundary,
    so an unavailable Redis instance is surfaced to the caller and never bypassed.
    """
    existing_client = getattr(request.app.state, "redis", None)
    if existing_client is not None:
        return existing_client

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not configured")

    import redis.asyncio as redis_asyncio

    client = redis_asyncio.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        raise

    request.app.state.redis = client
    logger.info("Redis connected for /demo/call rate limiting")
    return client


async def check_demo_rate_limits(request: Request, phone_number: str) -> str | None:
    """Reserve a demo-call slot, returning the exceeded limit when blocked.

    Redis INCR is atomic, so concurrent requests cannot both take the last slot.
    EXPIRE is applied when each key is first created: phone keys have a rolling
    24-hour window and dated global keys are automatically cleaned up.
    """
    redis_client = await get_demo_redis_client(request)
    phone_key = f"demo:rate:phone:{phone_number}"
    global_key = f"demo:rate:global:{datetime.now(timezone.utc).date().isoformat()}"

    phone_count = await redis_client.incr(phone_key)
    if phone_count == 1:
        await redis_client.expire(phone_key, DEMO_RATE_LIMIT_TTL_SECONDS)
    if phone_count > DEMO_PHONE_LIMIT:
        return "phone"

    global_count = await redis_client.incr(global_key)
    if global_count == 1:
        await redis_client.expire(global_key, DEMO_RATE_LIMIT_TTL_SECONDS)
    if global_count > DEMO_GLOBAL_LIMIT:
        return "global"

    return None


def demo_exotel_failure_response(exotel_response: JSONResponse) -> JSONResponse:
    """Translate /start's operational response into the demo's stable contract."""
    payload = json.loads(exotel_response.body)
    error = payload.get("error") if isinstance(payload, dict) else None
    status_code = 500 if error in {"missing_credentials", "exotel_connection_failed"} else 502

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "type": "exotel_call_failed",
            "error": error or "exotel_request_failed",
            "detail": "We could not start the demo call. Please try again later.",
        },
    )


@app.post("/demo/call")
async def request_demo_call(request: Request, body: DemoCallRequest) -> JSONResponse:
    """Validate and rate-limit a landing-page demo request before calling Exotel."""
    phone_number = body.phone_number
    if not isinstance(phone_number, str) or not E164_PHONE_NUMBER.fullmatch(phone_number):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "type": "invalid_phone_number",
                "error": "invalid_phone_number",
                "detail": "phone_number must be an E.164 number, for example +919876543210.",
            },
        )

    try:
        limited_by = await check_demo_rate_limits(request, phone_number)
    except Exception:
        logger.exception("Unable to enforce /demo/call rate limits")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "type": "rate_limit_unavailable",
                "error": "rate_limit_unavailable",
                "detail": "Demo calls are temporarily unavailable. Please try again later.",
            },
        )

    if limited_by:
        return JSONResponse(
            status_code=429,
            content={
                "status": "error",
                "type": "rate_limited",
                "error": "rate_limit_exceeded",
                "limit": limited_by,
                "detail": (
                    "This number has reached its demo-call limit."
                    if limited_by == "phone"
                    else "The daily demo-call limit has been reached."
                ),
            },
        )

    exotel_response = await trigger_exotel_call(request, phone_number)
    if exotel_response.status_code != 200:
        return demo_exotel_failure_response(exotel_response)

    exotel_payload = json.loads(exotel_response.body)
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "type": "call_triggered",
            "call_sid": exotel_payload.get("call_sid"),
        },
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle one Exotel Media Streams connection."""
    await websocket.accept()
    logger.info("WebSocket accepted — handing off to bot")

    try:
        await run_bot(websocket)
    except Exception:
        # logger.exception keeps the traceback; the reference prints the bare
        # exception, which loses where it came from.
        logger.exception("Call ended with an error")
    finally:
        # run_bot's transport usually closes the socket on its way out, and Exotel
        # may have hung up first. Either way this close is redundant, and which
        # exception it raises depends on who went first — neither is worth
        # surfacing as a 500:
        #
        #   RuntimeError        — we already sent the close frame, so starlette
        #                         refuses a second send (websockets.py:98).
        #   WebSocketDisconnect — the peer vanished. uvicorn raises
        #                         ClientDisconnected, an OSError, which starlette
        #                         converts to WebSocketDisconnect(1006).
        #
        # Catching only RuntimeError covered the first case but not the second —
        # which is the one that happens on every real call, since the carrier
        # hangs up. Every normal call end therefore escaped this handler and
        # uvicorn logged a ~40-line ASGI traceback at ERROR level. Harmless (it
        # runs after the pipeline has already torn down) but it would bury real
        # errors once call volume is real.
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            logger.debug("WebSocket was already closed")


# ----------------- Main ----------------- #


if __name__ == "__main__":
    # 7860 matches the reference example. Overridable so Dockerization (Task 2.5)
    # can pick the port without editing this file.
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "7860")),
    )
