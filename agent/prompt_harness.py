"""
NXLYR — text-only prompt testing harness (Task 2.3)

Same system prompt (bot.build_system_prompt), same OpenAI model/settings as
production (bot.LLM_MODEL / LLM_MAX_TOKENS / LLM_TEMPERATURE) — but plain
text in, text out. No Exotel, no audio, no Deepgram or ElevenLabs calls;
only OPENAI_API_KEY is required.

Interactive:
    python3 prompt_harness.py

Scripted (one caller line per line of input; blank lines and lines
starting with '#' are ignored; "exit"/"quit" or EOF ends the conversation):
    python3 prompt_harness.py < scenario.txt > transcript.txt
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from openai import OpenAI

from bot import GREETING, LLM_MAX_TOKENS, LLM_MODEL, LLM_TEMPERATURE, build_system_prompt, load_project_kb


def get_reply(client: OpenAI, history: list[dict]) -> str:
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        messages=history,
    )
    return response.choices[0].message.content


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    project_kb = load_project_kb()
    system_prompt = build_system_prompt(project_kb=project_kb)

    print(
        f"[prompt_harness] model={LLM_MODEL} max_tokens={LLM_MAX_TOKENS} "
        f"temperature={LLM_TEMPERATURE} kb_loaded={bool(project_kb)}"
    )
    print("=" * 72)

    # Seeds the same first assistant turn production starts every call with
    # (bot.py's on_client_connected), so the buyer's opening line here is a
    # reply to the same greeting they'd hear on a real call, not a cold open.
    history = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": GREETING},
    ]
    print(f"Bot: {GREETING}\n")

    interactive = sys.stdin.isatty()

    while True:
        if interactive:
            print("> ", end="", flush=True)
        try:
            line = input()
        except EOFError:
            if interactive:
                print()
            break

        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower() in ("exit", "quit"):
            break

        print(f"You: {line}")
        history.append({"role": "user", "content": line})

        reply = get_reply(client, history)
        print(f"Bot: {reply}\n")
        history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
