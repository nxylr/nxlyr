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

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from loguru import logger

load_dotenv(override=True)

# Imported at module scope, unlike the reference which imports bot inside the
# WebSocket handler. We want a missing dependency or a broken import to kill the
# process at boot, not to surface as a dropped call on a live customer.
from bot import run_bot

app = FastAPI(title="NXLYR Exotel Agent")

# No CORSMiddleware here, deliberately. The reference adds a permissive
# allow_origins=["*"] block for browser testing, but every caller of this service
# is server-side — Exotel's webhook and Exotel's media stream. There is no browser
# origin to allow, so the middleware would only widen the surface. Say the word if
# a dashboard ends up calling /start directly and we'll add a scoped origin list.


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
async def initiate_outbound_call() -> JSONResponse:
    """Not implemented yet — placeholder for Task 5.1.

    Task 5.1 will make this:
      - accept {"dialout_settings": {"phone_number": "..."}}
      - POST to https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect
        with HTTP Basic auth (EXOTEL_API_KEY / EXOTEL_API_TOKEN) and
        From/To/CallerId built off EXOTEL_PHONE_NUMBER
      - parse the <Sid> out of Exotel's XML response and return it
      - add an aiohttp.ClientSession on the app lifespan to make those calls
        (the reference keeps one on app.state.session)

    OPEN QUESTION for 5.1, not resolved here: bot.py greets the caller as soon as
    on_client_connected fires. Whether that's right depends on the call flow this
    endpoint sets up. Exotel's connect-two-numbers flow rings the bot leg first
    and only then dials the customer, so an immediate greeting would play before
    anyone is on the line. Settle this once /start's real flow exists.
    """
    return JSONResponse(
        status_code=501,
        content={
            "error": "not_implemented",
            "detail": "Outbound call initiation lands in Task 5.1.",
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
