"""Text-only prompt harness using production prompt, model settings, and tools."""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any, TextIO

from dotenv import load_dotenv

load_dotenv(override=True)

from openai import AsyncOpenAI
from pipecat.services.llm_service import FunctionCallParams
from pipecat.utils.string import match_endofsentence

from bot import LLM_MAX_TOKENS, LLM_MODEL, LLM_TEMPERATURE, load_project_kb
from prompt import BANNED_OPENERS_V21, build_initial_messages
from tools import (
    CLOSING_PHRASE,
    TOOL_HANDLERS,
    CallResources,
    make_redis_client,
    openai_tool_params,
)


HARNESS_CALL_SID_PREFIX = "harness"
DEFAULT_KB_PATH = Path(__file__).parent / "prompt_scripts" / "kb_meridian_heights.json"
BOOLEAN_FLAGS = (
    "reintro",
    "banned",
    "didyoumean",
    "digits",
    "tag_in_reply",
    "two_questions",
    "over45",
    "claimed_without_tool",
    "generic_closer",
    "timing_word",
)
PROCESS_PHRASES = ("Let me check", "One second", "Let me note that down")
GENERIC_CLOSERS = (
    "would you like to know more",
    "anything else you'd like to know",
    "is there anything else",
    "how can i help you",
    "what would you like to know",
    "how can i assist you",
)


@dataclass
class ReplyResult:
    message: Any
    first_sentence_words: int
    first_sentence_ms: int


class HarnessOutput:
    def __init__(self, stream: TextIO, out_stream: TextIO | None = None) -> None:
        self.stream = stream
        self.out_stream = out_stream

    def line(self, text: str = "") -> None:
        rendered = f"{text}\n"
        self.stream.write(rendered)
        if self.out_stream is not None:
            self.out_stream.write(rendered)


def _first_sentence(text: str) -> str:
    end = match_endofsentence(text)
    return text[:end] if end else text


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def reply_flags(
    text: str,
    caller_line: str,
    reply_index: int,
    *,
    function_called: bool = False,
) -> dict[str, Any]:
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    stripped = text.strip()
    lowered = stripped.casefold()
    caller = caller_line.casefold()
    identity_was_requested = any(
        phrase in caller
        for phrase in (
            "who are you",
            "who is this",
            "which company",
            "why did you call",
            "why are you calling",
        )
    )
    reintro = reply_index > 1 and not identity_was_requested and any(
        phrase in lowered
        for phrase in (
            "aarya",
            "next layer",
            "calling about",
            "you asked for a demo",
            "my name is",
        )
    )

    banned = False
    for opener in sorted(BANNED_OPENERS_V21, key=len, reverse=True):
        if re.match(rf"^{re.escape(opener)}(?:\b|[.!?,])", stripped, re.I):
            banned = True
            break
    if re.match(r"^Right(?:\b|[.!?,])", stripped, re.I) and not re.match(
        r"^Right,?\s+so\b", stripped, re.I
    ):
        banned = True

    connective_match = re.match(r"^(Okay so|Right,? so|So)\b", stripped, re.I)
    process_count = sum(len(re.findall(re.escape(phrase), text, re.I)) for phrase in PROCESS_PHRASES)
    first_sentence = _first_sentence(stripped)
    closer_text = re.sub(r"[.!?]+$", "", lowered).strip()
    return {
        "reintro": reintro,
        "banned": banned,
        "didyoumean": "did you mean" in lowered,
        "digits": bool(re.search(r"\d|₹|\bRs\b", text, re.I)),
        "tag_in_reply": bool(re.search(r"\[[^]]+\]", text)),
        "two_questions": text.count("?") >= 2,
        "over45": _word_count(text) > 45,
        "claimed_without_tool": not function_called
        and bool(
            re.search(
                r"\b(?:booked|put you down|down for|confirmed|noted|passed on|passed that on|passed it on|i've noted)\b",
                lowered,
            )
        ),
        "generic_closer": any(
            closer_text.endswith(closer) for closer in GENERIC_CLOSERS
        )
        or bool(re.search(r"\bhow can i assist you(?:\s+[^.!?]+)?$", closer_text)),
        "timing_word": bool(
            re.search(r"\b(?:shortly|soon|right away|today)\b", lowered)
        ),
        "first_sentence_words": _word_count(first_sentence),
        "connective": connective_match.group(1) if connective_match else None,
        "process_phrases": process_count,
        "ends_question": stripped.endswith("?"),
    }


@dataclass
class HarnessStats:
    replies: int = 0
    flag_counts: Counter = field(default_factory=Counter)
    first_sentence_words: list[int] = field(default_factory=list)
    first_sentence_ms: list[int] = field(default_factory=list)
    connective_counts: Counter = field(default_factory=Counter)
    process_phrases: int = 0
    ending_questions: int = 0
    sentences: Counter = field(default_factory=Counter)

    def add(
        self,
        text: str,
        flags: dict[str, Any],
        *,
        run_id: int,
        first_sentence_ms: int | None = None,
    ) -> None:
        self.replies += 1
        for name in BOOLEAN_FLAGS:
            self.flag_counts[name] += int(bool(flags[name]))
        self.first_sentence_words.append(flags["first_sentence_words"])
        if first_sentence_ms is not None:
            self.first_sentence_ms.append(first_sentence_ms)
        if flags["connective"]:
            self.connective_counts[flags["connective"].casefold()] += 1
        self.process_phrases += flags["process_phrases"]
        self.ending_questions += int(flags["ends_question"])
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
            normalized = " ".join(sentence.casefold().split())
            if normalized:
                self.sentences[(run_id, normalized)] += 1

    def render_summary(self) -> str:
        repeated = sum(max(0, count - 1) for count in self.sentences.values())
        median_words = statistics.median(self.first_sentence_words) if self.first_sentence_words else 0
        median_ms = statistics.median(self.first_sentence_ms) if self.first_sentence_ms else 0
        flag_text = " ".join(f"{name}={self.flag_counts[name]}" for name in BOOLEAN_FLAGS)
        connective_total = sum(self.connective_counts.values())
        connective_share = connective_total / self.replies if self.replies else 0
        return (
            "[summary]\n"
            f"replies={self.replies} p50_first_sentence_words={median_words:g} "
            f"p50_first_sentence_ms={median_ms:g}\n"
            f"{flag_text}\n"
            f"replies_with_two_questions={self.flag_counts['two_questions']} "
            f"repeated_sentences={repeated} replies_over_45={self.flag_counts['over45']}\n"
            f"connective_share={connective_share:.3f} connectives={connective_total} "
            f"connective_counts={dict(self.connective_counts)} process_phrases={self.process_phrases}\n"
            f"ending_in_question={self.ending_questions}/{self.replies}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--prompt-version", choices=("v2", "v21"), default="v21")
    parser.add_argument("--kb", "--kb-file", dest="kb", default=None)
    parser.add_argument("--partial-greeting", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--timing",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def parse_script(path: Path) -> list[list[str]]:
    scenarios: list[list[str]] = [[]]
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "---":
            if scenarios[-1]:
                scenarios.append([])
            continue
        scenarios[-1].append(line)
    return [scenario for scenario in scenarios if scenario]


def load_harness_kb(selection: str | None) -> dict:
    if selection == "live":
        return load_project_kb()
    path = Path(selection) if selection else DEFAULT_KB_PATH
    return json.loads(path.read_text())


def seed_history(
    project_kb: dict,
    prompt_version: str,
    *,
    partial_greeting: bool,
) -> list[dict]:
    history = build_initial_messages(project_kb, version=prompt_version)
    if partial_greeting:
        history[-1] = {
            **history[-1],
            "content": " ".join(history[-1]["content"].split()[:6]),
        }
    return history


def _simple_reply(message: Any) -> ReplyResult:
    content = message.content or ""
    return ReplyResult(message, _word_count(_first_sentence(content)), 0)


async def get_reply(
    client: AsyncOpenAI,
    history: list[dict],
    *,
    timing: bool,
) -> ReplyResult:
    request = {
        "model": LLM_MODEL,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": LLM_TEMPERATURE,
        "messages": history,
        "tools": openai_tool_params(),
    }
    if not timing:
        response = await client.chat.completions.create(**request)
        return _simple_reply(response.choices[0].message)

    stream = await client.chat.completions.create(**request, stream=True)
    if not hasattr(stream, "__aiter__"):
        return _simple_reply(stream.choices[0].message)

    content_parts: list[str] = []
    tool_parts: dict[int, dict[str, Any]] = {}
    first_token_at: float | None = None
    first_sentence_ms: int | None = None
    first_sentence_words = 0
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            if first_token_at is None:
                first_token_at = monotonic()
            content_parts.append(delta.content)
            content = "".join(content_parts)
            sentence_end = match_endofsentence(content)
            if sentence_end and first_sentence_ms is None:
                first_sentence_ms = int((monotonic() - first_token_at) * 1000)
                first_sentence_words = _word_count(content[:sentence_end])
        for item in delta.tool_calls or []:
            part = tool_parts.setdefault(
                item.index,
                {"id": item.id, "name": "", "arguments": ""},
            )
            if item.id:
                part["id"] = item.id
            if item.function and item.function.name:
                part["name"] += item.function.name
            if item.function and item.function.arguments:
                part["arguments"] += item.function.arguments

    content = "".join(content_parts) or None
    if content and first_sentence_ms is None:
        first_sentence_ms = int((monotonic() - first_token_at) * 1000) if first_token_at else 0
        first_sentence_words = _word_count(_first_sentence(content))
    tool_calls = [
        SimpleNamespace(
            id=part["id"],
            function=SimpleNamespace(name=part["name"], arguments=part["arguments"]),
        )
        for _, part in sorted(tool_parts.items())
    ] or None
    return ReplyResult(
        SimpleNamespace(content=content, tool_calls=tool_calls),
        first_sentence_words,
        first_sentence_ms or 0,
    )


async def run_tool_call(
    tool_call,
    resources: CallResources,
    history: list[dict],
    output: HarnessOutput,
):
    name = tool_call.function.name
    raw_args = tool_call.function.arguments
    output.line(f"\n  [TOOL CALL] {name}")
    output.line(f"  arguments: {raw_args}")
    try:
        arguments = json.loads(raw_args)
    except json.JSONDecodeError as error:
        output.line(f"  [TOOL ERROR] arguments were not valid JSON: {error}")
        arguments = {}

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        output.line(f"  [TOOL ERROR] no handler registered for {name!r}")
        return None

    captured: dict[str, Any] = {"result": None, "properties": None}

    async def result_callback(result, *, properties=None):
        captured["result"] = result
        captured["properties"] = properties

    await handler(
        FunctionCallParams(
            function_name=name,
            tool_call_id=tool_call.id,
            arguments=arguments,
            llm=None,
            pipeline_worker=None,
            context=None,
            result_callback=result_callback,
            app_resources=resources,
        )
    )
    output.line(f"  [TOOL RESULT] {json.dumps(captured['result'], default=str)}")
    history.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(captured["result"], default=str),
        }
    )
    return captured["properties"]


def _record_reply(
    text: str,
    *,
    label: str,
    caller_line: str,
    reply_index: int,
    first_sentence_ms: int,
    output: HarnessOutput,
    stats: HarnessStats,
    run_id: int,
    function_called: bool,
) -> None:
    output.line(f"{label}: {text}")
    flags = reply_flags(
        text,
        caller_line,
        reply_index,
        function_called=function_called,
    )
    stats.add(
        text,
        flags,
        run_id=run_id,
        first_sentence_ms=first_sentence_ms,
    )
    active = [name for name in BOOLEAN_FLAGS if flags[name]]
    flag_text = ",".join(active) if active else "none"
    output.line(
        f"  [flags] {flag_text} first_sentence_words={flags['first_sentence_words']} "
        f"first_sentence_ms={first_sentence_ms}"
    )


async def handle_turn(
    client: AsyncOpenAI,
    history: list[dict],
    resources: CallResources,
    *,
    output: HarnessOutput,
    timing: bool,
    caller_line: str,
    stats: HarnessStats,
    run_id: int,
    reply_index: int,
) -> bool:
    emitted = 0
    function_called = False
    for _ in range(4):
        reply = await get_reply(client, history, timing=timing)
        message = reply.message
        if message.tool_calls:
            function_called = True
            if message.content:
                _record_reply(
                    message.content,
                    label="Bot (before tool)",
                    caller_line=caller_line,
                    reply_index=reply_index + emitted,
                    first_sentence_ms=reply.first_sentence_ms,
                    output=output,
                    stats=stats,
                    run_id=run_id,
                    function_called=function_called,
                )
                emitted += 1
            history.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
            should_end = False
            for tool_call in message.tool_calls:
                properties = await run_tool_call(tool_call, resources, history, output)
                should_end = should_end or tool_call.function.name == "end_call"
                if properties is not None and properties.run_llm is False:
                    output.line(f"\nBot: {CLOSING_PHRASE}")
                    output.line("  [run_llm=False — no further model turn]")
                    return True
            if should_end:
                return True
            continue

        text = message.content or ""
        _record_reply(
            text,
            label="Bot",
            caller_line=caller_line,
            reply_index=reply_index + emitted,
            first_sentence_ms=reply.first_sentence_ms,
            output=output,
            stats=stats,
            run_id=run_id,
            function_called=function_called,
        )
        history.append({"role": "assistant", "content": text})
        return False

    output.line("  [harness] tool-call loop cap reached, moving on")
    return False


async def _run_lines(
    lines: list[str],
    *,
    client: AsyncOpenAI,
    resources: CallResources,
    project_kb: dict,
    args: argparse.Namespace,
    output: HarnessOutput,
    stats: HarnessStats,
    run_id: int,
) -> None:
    history = seed_history(
        project_kb,
        args.prompt_version,
        partial_greeting=args.partial_greeting,
    )
    output.line(f"Bot: {history[-1]['content']}")
    reply_index = 1
    for line in lines:
        if line.casefold() in {"exit", "quit"}:
            break
        output.line(f"You: {line}")
        history.append({"role": "user", "content": line})
        if await handle_turn(
            client,
            history,
            resources,
            output=output,
            timing=args.timing,
            caller_line=line,
            stats=stats,
            run_id=run_id,
            reply_index=reply_index,
        ):
            output.line("[prompt_harness] conversation ended by end_call")
            break
        reply_index += 1


async def run_harness(
    args: argparse.Namespace,
    *,
    client: AsyncOpenAI | None = None,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> HarnessStats:
    if args.runs < 1:
        raise ValueError("--runs must be at least 1")
    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing required environment variable: OPENAI_API_KEY")
        client = AsyncOpenAI(api_key=api_key)

    project_kb = load_harness_kb(args.kb)
    redis_client = await make_redis_client()
    resources = CallResources(
        call_sid=f"{HARNESS_CALL_SID_PREFIX}-{os.getpid()}",
        redis=redis_client,
    )
    output_stream = output_stream or sys.stdout
    out_stream = args.out.open("w") if args.out else None
    output = HarnessOutput(output_stream, out_stream)
    stats = HarnessStats()
    output.line(
        f"[prompt_harness] model={LLM_MODEL} max_tokens={LLM_MAX_TOKENS} "
        f"temperature={LLM_TEMPERATURE} kb_loaded={bool(project_kb)} "
        f"prompt_version={args.prompt_version} "
        f"tools={[tool['function']['name'] for tool in openai_tool_params()]} "
        f"redis={'connected' if redis_client else 'unavailable'} "
        f"session_key={resources.session_key}"
    )
    output.line("=" * 72)

    try:
        if args.script:
            scenarios = parse_script(args.script)
            run_id = 0
            for _ in range(args.runs):
                run_id += 1
                for scenario in scenarios:
                    await _run_lines(
                        scenario,
                        client=client,
                        resources=resources,
                        project_kb=project_kb,
                        args=args,
                        output=output,
                        stats=stats,
                        run_id=run_id,
                    )
        else:
            stream = input_stream or sys.stdin
            lines: list[str] = []
            interactive = bool(getattr(stream, "isatty", lambda: False)())
            while True:
                if interactive:
                    output_stream.write("> ")
                    output_stream.flush()
                line = stream.readline()
                if not line:
                    break
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                lines.append(line)
                if line.casefold() in {"exit", "quit"}:
                    break
            await _run_lines(
                lines,
                client=client,
                resources=resources,
                project_kb=project_kb,
                args=args,
                output=output,
                stats=stats,
                run_id=1,
            )
        output.line(stats.render_summary())
    finally:
        if redis_client is not None:
            session = await redis_client.hgetall(resources.session_key)
            ttl = await redis_client.ttl(resources.session_key)
            output.line(f"[prompt_harness] redis {resources.session_key}:")
            output.line(f"  {json.dumps(session, indent=2, sort_keys=True)}")
            output.line(f"  ttl={ttl}s")
            await redis_client.aclose()
        if out_stream is not None:
            out_stream.close()
    return stats


async def main() -> None:
    await run_harness(build_arg_parser().parse_args())


if __name__ == "__main__":
    asyncio.run(main())
