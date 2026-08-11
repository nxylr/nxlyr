"""
NXLYR — text-only prompt testing harness (Task 2.3, extended in Task 4.1)

Same system prompt (bot.build_system_prompt), same OpenAI model/settings as
production (bot.LLM_MODEL / LLM_MAX_TOKENS / LLM_TEMPERATURE), and — since Task
4.1 — the same three tools with the same handlers (agent/tools.py). Plain text
in, text out. No Exotel, no audio, no Deepgram or ElevenLabs calls; only
OPENAI_API_KEY is required (REDIS_URL optional, see below).

Tool calls are real here, not simulated: the harness sends the identical tool
definitions production sends (tools.openai_tool_params(), built from the same
FunctionSchema objects the LLMContext advertises) and invokes the identical
handler functions with a real FunctionCallParams. So a booking tested here
writes the same Redis session flags a booking on a real call writes.

Two things necessarily differ from production, both because there is no
pipeline here:
  - params.pipeline_worker is None, so end_call cannot queue its goodbye or
    stop the pipeline. The handler detects this and says so. The harness prints
    the closing phrase the caller would have heard and ends the conversation,
    which is the text-mode equivalent of the pipeline shutting down.
  - cancel_on_interruption is meaningless without interruptions.

Interactive:
    python3 prompt_harness.py

Scripted (one caller line per line of input; blank lines and lines
starting with '#' are ignored; "exit"/"quit" or EOF ends the conversation):
    python3 prompt_harness.py < scenario.txt > transcript.txt
"""

import asyncio
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from openai import AsyncOpenAI

from bot import (
    GREETING,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    build_system_prompt,
    load_project_kb,
)
from tools import (
    CLOSING_PHRASE,
    TOOL_HANDLERS,
    CallResources,
    make_redis_client,
    openai_tool_params,
)

from pipecat.services.llm_service import FunctionCallParams

# Distinguishes harness-written Redis session hashes from real call_sids, so a
# developer poking at Redis can tell which is which. Same key shape either way
# (tools.CallResources.session_key).
HARNESS_CALL_SID_PREFIX = "harness"


async def get_reply(client: AsyncOpenAI, history: list[dict]):
    """One chat-completions turn, with the production tool definitions attached.

    Returns the raw message object rather than message.content — the whole
    point of Task 4.1 is that content may be None because the model chose to
    call a function instead, and the old harness (which returned .content
    directly) would have printed "Bot: None" and hidden exactly the behaviour
    we now need to see.
    """
    response = await client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        messages=history,
        tools=openai_tool_params(),
    )
    return response.choices[0].message


async def run_tool_call(tool_call, resources: CallResources, history: list[dict]):
    """Invoke one real handler and append its result to the history.

    Returns the FunctionCallResultProperties the handler passed back (or None),
    so the caller can honour run_llm the way Pipecat's function-call runner
    does.
    """
    name = tool_call.function.name
    raw_args = tool_call.function.arguments

    # Show the payload verbatim before parsing it — if the model emits
    # malformed JSON that is itself the finding, and a traceback from
    # json.loads would otherwise be the only evidence.
    print(f"\n  [TOOL CALL] {name}")
    print(f"  arguments: {raw_args}")

    try:
        arguments = json.loads(raw_args)
    except json.JSONDecodeError as e:
        print(f"  [TOOL ERROR] arguments were not valid JSON: {e}")
        arguments = {}

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        print(f"  [TOOL ERROR] no handler registered for {name!r}")
        return None

    captured: dict = {"result": None, "properties": None}

    async def result_callback(result, *, properties=None):
        captured["result"] = result
        captured["properties"] = properties

    await handler(
        FunctionCallParams(
            function_name=name,
            tool_call_id=tool_call.id,
            arguments=arguments,
            llm=None,
            # No pipeline in text mode. end_call checks for this rather than
            # assuming a worker is there.
            pipeline_worker=None,
            context=None,
            result_callback=result_callback,
            app_resources=resources,
        )
    )

    print(f"  [TOOL RESULT] {json.dumps(captured['result'], default=str)}")

    history.append(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {"name": name, "arguments": raw_args},
                }
            ],
        }
    )
    history.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(captured["result"], default=str),
        }
    )
    return captured["properties"]


async def handle_turn(client: AsyncOpenAI, history: list[dict], resources) -> bool:
    """Drive one caller turn to completion, tool calls included.

    Loops because a tool result feeds back into the model, which may then speak
    or call another tool. Bounded rather than while-True: a model that loops on
    tool calls should show up as a visible cap in the transcript, not as an
    unbounded spend.

    Returns True if the conversation should end (end_call fired).
    """
    for _ in range(4):
        message = await get_reply(client, history)

        if message.tool_calls:
            should_end = False
            for tool_call in message.tool_calls:
                properties = await run_tool_call(tool_call, resources, history)
                if tool_call.function.name == "end_call":
                    should_end = True
                # run_llm=False means the handler has taken responsibility for
                # what the caller hears next — for end_call, the fixed
                # CLOSING_PHRASE it would have queued as a TTSSpeakFrame.
                if properties is not None and properties.run_llm is False:
                    print(f"\nBot: {CLOSING_PHRASE}")
                    print("  [run_llm=False — no further model turn]")
                    return True
            if should_end:
                return True
            # Tool result is in history; loop so the model can respond to it.
            continue

        print(f"Bot: {message.content}\n")
        history.append({"role": "assistant", "content": message.content})
        return False

    print("  [harness] tool-call loop cap reached, moving on\n")
    return False


async def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    project_kb = load_project_kb()
    system_prompt = build_system_prompt(project_kb=project_kb)

    # Real handlers write real session flags. With REDIS_URL unset this is None
    # and the handlers log a warning and carry on, exactly as they do on a call
    # placed while Redis is down.
    redis_client = await make_redis_client()
    call_sid = f"{HARNESS_CALL_SID_PREFIX}-{os.getpid()}"
    resources = CallResources(call_sid=call_sid, redis=redis_client)

    print(
        f"[prompt_harness] model={LLM_MODEL} max_tokens={LLM_MAX_TOKENS} "
        f"temperature={LLM_TEMPERATURE} kb_loaded={bool(project_kb)} "
        f"tools={[t['function']['name'] for t in openai_tool_params()]} "
        f"redis={'connected' if redis_client else 'unavailable'} "
        f"session_key={resources.session_key}"
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

    try:
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

            if await handle_turn(client, history, resources):
                print("\n[prompt_harness] conversation ended by end_call")
                break
    finally:
        if redis_client is not None:
            # Dump what the handlers actually wrote. This is the evidence that
            # the tools changed real state rather than just returning happy
            # dicts to the model.
            session = await redis_client.hgetall(resources.session_key)
            ttl = await redis_client.ttl(resources.session_key)
            print(f"\n[prompt_harness] redis {resources.session_key}:")
            print(f"  {json.dumps(session, indent=2, sort_keys=True)}")
            print(f"  ttl={ttl}s")
            await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
