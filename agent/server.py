"""
NXLYR — Exotel webhook + media-stream server (Week 3 / Task 2.4)

Three routes:

  GET  /health — liveness probe for the container HEALTHCHECK.
  POST /start  — stub. Will initiate the outbound call via Exotel's Connect API.
                 Returns 501 until Task 5.1 implements it.
  WS   /ws     — the endpoint Exotel's App Bazaar "Voicebot" applet connects to.
                 Accepts the socket and hands it to bot.run_bot() for the
                 lifetime of one call.

Structure follows pipecat-examples/exotel-chatbot/outbound/server.py. Deviations
from that reference are called out in comments where they occur.

Run locally:  python server.py       (or: uvicorn server:app --host 0.0.0.0 --port 7860)
"""

import os
from contextlib import asynccontextmanager

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

load_dotenv(override=True)

# Imported at module scope, unlike the reference which imports bot inside the
# WebSocket handler. We want a missing dependency or a broken import to kill the
# process at boot, not to surface as a dropped call on a live customer.
from bot import run_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage long-lived resources across the FastAPI app lifecycle.

    Creates a shared aiohttp.ClientSession on app.state.session at boot and closes
    it cleanly on shutdown.
    """
    logger.info("Initializing shared aiohttp.ClientSession on app.state.session")
    app.state.session = aiohttp.ClientSession()
    try:
        yield
    finally:
        logger.info("Closing shared aiohttp.ClientSession")
        await app.state.session.close()


app = FastAPI(title="NXLYR Exotel Agent", lifespan=lifespan)

# No CORSMiddleware here, deliberately. The reference adds a permissive
# allow_origins=["*"] block for browser testing, but every caller of this service
# is server-side — Exotel's webhook and Exotel's media stream. There is no browser
# origin to allow, so the middleware would only widen the surface. Say the word if
# a dashboard ends up calling /start directly and we'll add a scoped origin list.


class StartCallRequest(BaseModel):
    phone_number: str | None = Field(
        default=None,
        description="Target customer phone number (e.g. +919876500000)",
    )
    dialout_settings: dict | None = Field(
        default=None,
        description="Optional nested dialout settings dict containing phone_number",
    )


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


@app.post("/start")
async def initiate_outbound_call(
    request: Request, body: StartCallRequest
) -> JSONResponse:
    """Initiate an outbound call via Exotel's Connect API.

    Accepts {"phone_number": "..."} or {"dialout_settings": {"phone_number": "..."}}.
    Posts to https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect.json
    using HTTP Basic auth (EXOTEL_API_KEY / EXOTEL_API_TOKEN).

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
        # may have hung up first. Closing twice raises, and that's not worth
        # surfacing as a 500.
        try:
            await websocket.close()
        except RuntimeError:
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

