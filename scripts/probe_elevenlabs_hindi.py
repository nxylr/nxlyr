#!/usr/bin/env python3
"""Render fixed Hindi/English lines with two ElevenLabs models for listening."""

import argparse
import asyncio
import os
import re
import time
import wave
from pathlib import Path

import aiohttp


VOICE_ID = "9lx2GDtpvyyNBM7O9Mmx"
MODELS = ("eleven_v4_turbo", "eleven_flash_v2_5")
LINES = (
    "जी, Meridian Heights Gurugram में एक residential project है।",
    "इस project में three BHK homes उपलब्ध हैं।",
    "कीमत two point two crore rupees से शुरू होती है।",
    "Saturday को eleven बजे ठीक रहेगा।",
    "the fifteenth of November को site visit रख सकते हैं।",
    "माफ़ कीजिए, मुझे ठीक से सुनाई नहीं दिया।",
    "This is a pure English sentence for the control sample.",
    "जी, मैं एक AI assistant हूँ, Next Layer की तरफ़ से call कर रही हूँ।",
)


def slug(text: str) -> str:
    latin = "-".join(re.findall(r"[A-Za-z0-9]+", text.lower())[:5])
    return latin or "hindi"


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(pcm)


async def render(
    session: aiohttp.ClientSession,
    *,
    api_key: str,
    out_dir: Path,
    line_number: int,
    text: str,
    model: str,
    language_code: str | None,
) -> None:
    payload = {"text": text, "model_id": model}
    if language_code:
        payload["language_code"] = language_code
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
    started_at = time.monotonic()
    first_byte_ms: int | None = None
    pcm = bytearray()
    label = "hi" if language_code else "auto"
    try:
        async with session.post(
            url,
            params={"output_format": "pcm_8000"},
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        ) as response:
            async for chunk in response.content.iter_chunked(4096):
                if first_byte_ms is None:
                    first_byte_ms = int((time.monotonic() - started_at) * 1000)
                pcm.extend(chunk)
            filename = (
                f"{line_number:02d}-{slug(text)}-{model}-{label}.wav"
            )
            if response.status == 200:
                write_wav(out_dir / filename, bytes(pcm))
            print(
                f"line={line_number} model={model} language_code={label} "
                f"status={response.status} first_byte_ms={first_byte_ms or 'none'} "
                f"bytes={len(pcm)} file={filename if response.status == 200 else 'none'}"
            )
    except Exception as error:
        print(
            f"line={line_number} model={model} language_code={label} "
            f"status=failed error={type(error).__name__}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / "021-elevenlabs-probe",
    )
    args = parser.parse_args()
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is required")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for line_number, text in enumerate(LINES, 1):
            for model in MODELS:
                for language_code in (None, "hi"):
                    await render(
                        session,
                        api_key=api_key,
                        out_dir=args.out_dir,
                        line_number=line_number,
                        text=text,
                        model=model,
                        language_code=language_code,
                    )


if __name__ == "__main__":
    asyncio.run(main())
