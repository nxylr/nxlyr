#!/usr/bin/env python3
"""Send an anonymous Exotel-shaped WebSocket handshake and report closure."""

import argparse
import asyncio
import json
import warnings

import websockets
from websockets.exceptions import ConnectionClosed


def display_sid(call_sid: str) -> str:
    return repr(call_sid)[:64]


def close_code(websocket, closed: ConnectionClosed) -> int | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        code = getattr(websocket, "close_code", None)
        received = getattr(websocket, "rcvd", None)
    return code or getattr(received, "code", None) or closed.code


async def probe(url: str, call_sid: str) -> None:
    websocket = None
    try:
        async with websockets.connect(url, open_timeout=10) as websocket:
            await websocket.send(json.dumps({"event": "connected", "version": "1.0.0"}))
            await websocket.send(
                json.dumps(
                    {
                        "event": "start",
                        "start": {"call_sid": call_sid, "stream_sid": "anonymous-probe"},
                    }
                )
            )
            deadline = asyncio.get_running_loop().time() + 8
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    print(f"connection remained open (sid={display_sid(call_sid)})")
                    return
                try:
                    await asyncio.wait_for(websocket.recv(), timeout=remaining)
                except ConnectionClosed as closed:
                    print(
                        f"connection closed (code={close_code(websocket, closed)}, "
                        f"sid={display_sid(call_sid)})"
                    )
                    return
    except ConnectionClosed as closed:
        code = close_code(websocket, closed) if websocket is not None else closed.code
        print(f"connection closed (code={code}, sid={display_sid(call_sid)})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe /ws without credentials.")
    parser.add_argument("url", help="WebSocket endpoint, for example wss://host/ws")
    parser.add_argument("call_sid", help="Fake Exotel call SID")
    args = parser.parse_args()
    asyncio.run(probe(args.url, args.call_sid))


if __name__ == "__main__":
    main()
