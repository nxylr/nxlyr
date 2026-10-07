"""Truthful-agent tests (F04, F05). Everything is mocked: no network, no keys,
no Redis server. Run from agent/:  python -m pytest test_truthful_agent.py
"""

import asyncio
import re
from datetime import date
from types import SimpleNamespace

from loguru import logger

import bot
import kb_loader
import tools

PROMISE_RE = re.compile(
    r"whatsapp|brochure|right away|right after|immediately", re.IGNORECASE
)
FORBIDDEN_ON_FAILURE = ("booked", "confirmed", "scheduled", "reserved")
SECRET = "redis://user:hunter2@internal-host:6379"


class FakeRedis:
    def __init__(self, fail=False):
        self.fail = fail
        self.writes = []

    async def hset(self, key, field, value):
        if self.fail:
            raise ConnectionError(f"cannot reach {SECRET}")
        self.writes.append((key, field, value))

    async def expire(self, key, ttl):
        if self.fail:
            raise ConnectionError(f"cannot reach {SECRET}")


def _call(handler, arguments, redis):
    """Run a tool handler with a fake FunctionCallParams; return its result."""
    results = []

    async def result_callback(result, *, properties=None):
        results.append(result)

    params = SimpleNamespace(
        arguments=arguments,
        app_resources=tools.CallResources(call_sid="CA_TEST", redis=redis),
        result_callback=result_callback,
        pipeline_worker=None,
    )
    asyncio.run(handler(params))
    assert len(results) == 1
    return results[0]


def _capture_logs(level="DEBUG"):
    lines = []
    sink_id = logger.add(lambda m: lines.append(str(m)), level=level)
    return lines, sink_id


VISIT_ARGS = {"preferred_date": date.today().isoformat(), "preferred_time": "11:00"}
TRANSFER_ARGS = {"reason": "legal question", "context_summary": "asked about RERA"}


# --- _set_session_flag ------------------------------------------------------


def test_set_session_flag_returns_false_on_redis_error_and_logs_no_message():
    lines, sink = _capture_logs()
    try:
        res = tools.CallResources(call_sid="CA_TEST", redis=FakeRedis(fail=True))
        ok = asyncio.run(tools._set_session_flag(res, "f", "v-secret-value", "book_site_visit"))
    finally:
        logger.remove(sink)
    assert ok is False
    joined = "\n".join(lines)
    assert "ConnectionError" in joined and "book_site_visit" in joined
    assert "hunter2" not in joined and "internal-host" not in joined
    assert "v-secret-value" not in joined


def test_set_session_flag_false_without_redis():
    assert asyncio.run(tools._set_session_flag(None, "f", "v", "end_call")) is False
    res = tools.CallResources(call_sid="x", redis=None)
    assert asyncio.run(tools._set_session_flag(res, "f", "v", "end_call")) is False


def test_set_session_flag_true_on_success():
    redis = FakeRedis()
    res = tools.CallResources(call_sid="CA_TEST", redis=redis)
    assert asyncio.run(tools._set_session_flag(res, "f", "v", "end_call")) is True
    assert redis.writes == [("session:call:CA_TEST", "f", "v")]


# --- book_site_visit / transfer_to_human -------------------------------------


def _assert_failure_result(result):
    assert set(result) == {"recorded", "notified", "guidance"}
    assert result["recorded"] is False
    assert result["notified"] is False
    low = result["guidance"].lower()
    assert not any(word in low for word in FORBIDDEN_ON_FAILURE)
    assert "could not note" in low


def _assert_success_result(result):
    assert set(result) == {"recorded", "notified", "guidance"}
    assert result["recorded"] is True
    assert result["notified"] is False
    assert "noted" in result["guidance"].lower()


def test_book_site_visit_redis_failure():
    _assert_failure_result(_call(tools.book_site_visit, VISIT_ARGS, FakeRedis(fail=True)))


def test_book_site_visit_no_redis_is_not_recorded():
    _assert_failure_result(_call(tools.book_site_visit, VISIT_ARGS, None))


def test_book_site_visit_redis_ok():
    _assert_success_result(_call(tools.book_site_visit, VISIT_ARGS, FakeRedis()))


def test_book_site_visit_validation_error_uses_contract():
    result = _call(tools.book_site_visit, {"preferred_date": "2020-01-01"}, FakeRedis())
    assert set(result) == {"recorded", "notified", "guidance"}
    assert result["recorded"] is False and result["notified"] is False


def test_transfer_to_human_redis_failure():
    _assert_failure_result(_call(tools.transfer_to_human, TRANSFER_ARGS, FakeRedis(fail=True)))


def test_transfer_to_human_redis_ok():
    result = _call(tools.transfer_to_human, TRANSFER_ARGS, FakeRedis())
    _assert_success_result(result)
    low = result["guidance"].lower()
    assert "no live transfer" in low
    assert "transferring you" not in low and "putting you through" not in low


def test_end_call_logs_flag_result_and_keeps_result_shape():
    lines, sink = _capture_logs()
    try:
        result = _call(tools.end_call, {"outcome": "not_interested"}, FakeRedis(fail=True))
    finally:
        logger.remove(sink)
    assert result == {"status": "ended", "outcome": "not_interested"}
    assert "end_call_tool_invoked=False" in "\n".join(lines)


def test_schema_descriptions_mirror_contract():
    for schema in (tools.BOOK_SITE_VISIT_SCHEMA, tools.TRANSFER_TO_HUMAN_SCHEMA):
        assert "{recorded, notified, guidance}" in schema.description


# --- prompt ------------------------------------------------------------------

FIXTURE_KB = {
    "project_name": "Test Towers",
    "developer": "Test Developer",
    "pricing": {"3bhk": "1.2 crore onwards"},
}


def _prompt():
    return bot.build_system_prompt(project_kb=FIXTURE_KB, today=date(2026, 10, 7))


def _section(prompt, name, next_name):
    return prompt.split(f"[{name}]\n", 1)[1].split(f"\n\n[{next_name}]", 1)[0]


def test_few_shot_assistant_lines_and_greeting_have_no_promise_text():
    examples = _section(_prompt(), "CONVERSATION EXAMPLES", "TOOLS")
    assistant_lines = [
        line[len("You: "):] for line in examples.splitlines() if line.startswith("You: ")
    ]
    assert len(assistant_lines) == len(bot.FEW_SHOT_EXAMPLES) > 0
    for line in assistant_lines + [bot.GREETING]:
        assert not PROMISE_RE.search(line), line


def test_rules_contain_verbatim_no_send_rule():
    rules = _section(_prompt(), "RULES", "PROJECT KNOWLEDGE BASE")
    assert (
        "You cannot send brochures, documents, WhatsApp messages, SMS or emails. "
        "Never promise to. If asked, say you can't send anything from this call "
        "and offer to share the key details now. Never say a request is booked, "
        "confirmed or scheduled. Only say the team will follow up if the tool "
        "result says notified is true."
    ) in rules


def test_rules_require_ai_disclosure_when_sincerely_asked():
    prompt = _prompt()
    assert (
        "If the caller sincerely asks whether they are speaking to a person, a "
        "bot or an AI, say plainly that you are an AI assistant. Never claim to "
        "be a human."
    ) in _section(prompt, "RULES", "PROJECT KNOWLEDGE BASE")
    assert "Never reveal you are an AI" not in prompt


def test_tools_block_does_not_teach_follow_up_promise():
    tools_block = _prompt().split("[TOOLS]\n", 1)[1]
    assert "they'll follow up" not in tools_block
    assert "never tell someone a visit is booked" not in tools_block.lower()


# --- kb_loader ---------------------------------------------------------------


def _fetch_with_config(monkeypatch, config):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-key")
    response = SimpleNamespace(
        status_code=200, json=lambda: [{"id": "p1", "config": config}], text=""
    )
    monkeypatch.setattr(kb_loader.requests, "get", lambda *a, **k: response)
    return kb_loader._fetch_kb("fixture-slug")


def test_kb_loader_warns_on_promise_text_without_altering_kb(monkeypatch):
    config = {"faqs": [{"a": "ok"}, {"a": "we'll WhatsApp you right away"}]}
    lines, sink = _capture_logs(level="WARNING")
    try:
        returned = _fetch_with_config(monkeypatch, config)
    finally:
        logger.remove(sink)
    joined = "\n".join(lines)
    assert "faqs[1].a" in joined
    assert "'whatsapp'" in joined and "'right away'" in joined
    assert "we'll WhatsApp you" not in joined  # never the full text
    assert returned == {"faqs": [{"a": "ok"}, {"a": "we'll WhatsApp you right away"}]}


def test_kb_loader_silent_on_clean_kb(monkeypatch):
    lines, sink = _capture_logs(level="WARNING")
    try:
        _fetch_with_config(monkeypatch, FIXTURE_KB)
    finally:
        logger.remove(sink)
    assert lines == []
