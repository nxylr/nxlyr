import os
import sys
import time as process_time
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from loguru import logger


AGENT_DIRECTORY = str(Path(__file__).parent)
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

import commitments
import prompt
import tools
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import FunctionCallParams


FIXED_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=commitments.IST)
FAKE_ENV = {
    "SUPABASE_URL": "https://database.invalid",
    "SUPABASE_SERVICE_ROLE_KEY": "fake-supabase-key",
    "TELEGRAM_BOT_TOKEN": "123456:fake-token",
    "TELEGRAM_CHAT_ID": "987654321",
}


class FakeResponse:
    def __init__(self, status: int, payload: object = None) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def json(self, content_type=None):
        return self.payload


class ScriptedSession:
    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def _request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        status, payload = self.responses.pop(0)
        return FakeResponse(status, payload)

    def get(self, url: str, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self._request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self._request("PATCH", url, **kwargs)


class DynamicRequest:
    def __init__(
        self,
        factory,
        wait_for: asyncio.Event | None = None,
        wait_after: asyncio.Event | None = None,
    ) -> None:
        self.factory = factory
        self.wait_for = wait_for
        self.wait_after = wait_after
        self.response = None

    async def __aenter__(self):
        if self.wait_for is not None:
            await self.wait_for.wait()
        status, payload = self.factory()
        if self.wait_after is not None:
            await self.wait_after.wait()
        self.response = FakeResponse(status, payload)
        return self.response

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class MemorySession:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.rows: list[dict[str, object]] = []
        self.alerts: list[str] = []
        self.next_id = 1
        self.fail_next_insert: int | None = None
        self.fail_next_alert: int | None = None
        self.fail_alert_marker = False
        self.fail_supersede = False
        self.lookup_release: asyncio.Event | None = None
        self.mark_release: asyncio.Event | None = None
        self.alert_delivered: asyncio.Event | None = None
        self.alert_release: asyncio.Event | None = None
        self.lookup_started = 0

    def get(self, url: str, **kwargs):
        snapshot = [
            dict(row)
            for row in self.rows
            if row["call_sid"] == kwargs["params"]["call_sid"].removeprefix("eq.")
            and row["kind"] == "site_visit"
            and row.get("superseded_at") is None
        ]
        self.lookup_started += 1
        self.calls.append({"method": "GET", "label": "lookup", "url": url, **kwargs})
        return DynamicRequest(lambda: (200, snapshot), self.lookup_release)

    def post(self, url: str, **kwargs):
        if "api.telegram.org" in url:
            self.calls.append({"method": "POST", "label": "alert", "url": url, **kwargs})

            def alert():
                if self.fail_next_alert is not None:
                    status = self.fail_next_alert
                    self.fail_next_alert = None
                    return status, {"ok": False}
                self.alerts.append(kwargs["json"]["text"])
                if self.alert_delivered is not None:
                    self.alert_delivered.set()
                return 200, {"ok": True}

            return DynamicRequest(alert, wait_after=self.alert_release)

        self.calls.append({"method": "POST", "label": "insert", "url": url, **kwargs})

        def insert():
            if self.fail_next_insert is not None:
                status = self.fail_next_insert
                self.fail_next_insert = None
                return status, {}
            payload = dict(kwargs["json"])
            existing = next(
                (
                    row
                    for row in self.rows
                    if row["call_sid"] == payload["call_sid"]
                    and row["kind"] == payload["kind"]
                    and row.get("visit_date") == payload.get("visit_date")
                    and row.get("visit_time") == payload.get("visit_time")
                    and payload["kind"] == "site_visit"
                ),
                None,
            )
            if existing is None:
                payload["id"] = f"ref-{self.next_id}"
                payload["alert_sent_at"] = None
                self.next_id += 1
                self.rows.append(payload)
                existing = payload
            else:
                existing.update(payload)
            return 201, [{"id": existing["id"]}]

        return DynamicRequest(insert)

    def patch(self, url: str, **kwargs):
        label = "supersede" if "superseded_at=is.null" in url else "mark_alerted"
        self.calls.append({"method": "PATCH", "label": label, "url": url, **kwargs})

        def update():
            if label == "mark_alerted" and self.fail_alert_marker:
                return 500, None
            if label == "supersede" and self.fail_supersede:
                return 500, None
            if label == "mark_alerted":
                reference = url.split("id=eq.", 1)[1]
                for row in self.rows:
                    if row["id"] == reference:
                        row.update(kwargs["json"])
            else:
                references = url.split("id=in.(", 1)[1].split(")", 1)[0].split(",")
                for row in self.rows:
                    if row["id"] in references and row.get("superseded_at") is None:
                        row.update(kwargs["json"])
            return 204, None

        wait_for = self.mark_release if label == "mark_alerted" else None
        return DynamicRequest(update, wait_for)


class ExplodingSession:
    def post(self, url: str, **kwargs):
        raise OSError("token=123456:fake-token chat=987654321 phone=9876543210 key=fake-supabase-key")


class AlertExplodingSession(ScriptedSession):
    def post(self, url: str, **kwargs):
        if "api.telegram.org" in url:
            raise OSError("aiohttp-error-private-marker")
        return super().post(url, **kwargs)


class SlowAlertSession(ScriptedSession):
    def __init__(self) -> None:
        super().__init__([(201, [{"id": "ref-slow"}])])
        self.never = asyncio.Event()

    def post(self, url: str, **kwargs):
        if "api.telegram.org" in url:
            self.calls.append({"method": "POST", "url": url, **kwargs})
            return DynamicRequest(lambda: (200, {"ok": True}), self.never)
        return super().post(url, **kwargs)


class SlowSession:
    def post(self, url: str, **kwargs):
        async def wait_forever():
            await asyncio.sleep(10)
            return 201, []

        class SlowRequest:
            async def __aenter__(self):
                status, payload = await wait_forever()
                return FakeResponse(status, payload)

            async def __aexit__(self, exc_type, exc, traceback):
                return None

        return SlowRequest()


class CallData:
    def __init__(self, from_number: str = "", to_number: str = "") -> None:
        self.from_number = from_number
        self.to_number = to_number


class FakePipeline:
    def __init__(self, redis, fail: bool = False) -> None:
        self.redis = redis
        self.fail = fail
        self.operations: list[tuple] = []

    def hset(self, key, mapping=None):
        self.operations.append(("hset", key, mapping))
        return self

    def hsetnx(self, key, field, value):
        self.operations.append(("hsetnx", key, field, value))
        return self

    def expire(self, key, seconds):
        self.operations.append(("expire", key, seconds))
        return self

    async def execute(self):
        if self.fail:
            raise ConnectionError("redis-password phone=9876543210")
        for operation in self.operations:
            if operation[0] == "hset":
                self.redis.values.update(operation[2])
            elif operation[0] == "hsetnx":
                self.redis.values.setdefault(operation[2], operation[3])
        return [True] * len(self.operations)


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.fail = fail
        self.pipelines: list[FakePipeline] = []

    def pipeline(self, transaction=True):
        pipeline = FakePipeline(self, self.fail)
        pipeline.transaction = transaction
        self.pipelines.append(pipeline)
        return pipeline


class FakeWorker:
    def __init__(self) -> None:
        self.frames: list[object] = []
        self.stopped = False

    async def queue_frames(self, frames):
        self.frames.extend(frames)

    async def stop_when_done(self):
        self.stopped = True


class ResultCapture:
    def __init__(self) -> None:
        self.result = None
        self.properties = None
        self.called = asyncio.Event()

    async def __call__(self, result, *, properties=None):
        self.result = result
        self.properties = properties
        self.called.set()


class CancellingResultCapture(ResultCapture):
    async def __call__(self, result, *, properties=None):
        self.result = result
        self.properties = properties
        self.called.set()
        asyncio.current_task().cancel()
        await asyncio.sleep(0)


class BlockingResultCapture(ResultCapture):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def __call__(self, result, *, properties=None):
        self.result = result
        self.properties = properties
        self.called.set()
        await self.release.wait()


def tool_params(
    name: str,
    arguments: dict[str, object],
    resources: tools.CallResources | None,
    *,
    worker=None,
    context=None,
) -> tuple[FunctionCallParams, ResultCapture]:
    capture = ResultCapture()
    return (
        FunctionCallParams(
            function_name=name,
            tool_call_id="test-call",
            arguments=arguments,
            llm=None,
            pipeline_worker=worker,
            context=context,
            result_callback=capture,
            app_resources=resources,
        ),
        capture,
    )


class VisitValidationTests(unittest.TestCase):
    def assert_visit_error(
        self, preferred_date: object, preferred_time: object, reason: str
    ) -> None:
        result = commitments.parse_visit(preferred_date, preferred_time, FIXED_NOW)
        self.assertIsInstance(result, commitments.VisitError)
        self.assertEqual(result.reason, reason)

    def test_t01_rejects_malformed_dates_and_times(self) -> None:
        for bad_time in ("25:99", "24:00", "9:5", "11.30", "11:30pm", "", None):
            with self.subTest(preferred_time=bad_time):
                reason = "time_missing" if bad_time in ("", None) else "time_malformed"
                self.assert_visit_error("2026-10-26", bad_time, reason)

        for bad_date in (
            "20261025",
            "2026-W43-1",
            "2026-10-25T11:00",
            "2026-13-01",
            "",
        ):
            with self.subTest(preferred_date=bad_date):
                reason = "date_missing" if bad_date == "" else "date_malformed"
                self.assert_visit_error(bad_date, "11:00", reason)

        self.assert_visit_error("٢٠٢٦-١٠-٢٦", "11:00", "date_malformed")
        self.assert_visit_error("2026-10-26", "١١:٣٠", "time_malformed")
        self.assert_visit_error("2026-10-26", "1٣:30", "time_malformed")
        self.assert_visit_error("2026-10-26", "11:٣٠", "time_malformed")

    def test_t02_validation_uses_ist_not_process_timezone(self) -> None:
        utc_now = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
        old_tz = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/Los_Angeles"
            if hasattr(process_time, "tzset"):
                process_time.tzset()
            self.assert_visit_error("2026-10-24", "18:00", "in_the_past")
            accepted = commitments.parse_visit("2026-10-25", "09:00", utc_now)
            self.assertEqual(accepted[0].isoformat(), "2026-10-25")
            self.assertEqual(accepted[1].isoformat(timespec="minutes"), "09:00")
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            if hasattr(process_time, "tzset"):
                process_time.tzset()

        self.assertEqual(
            commitments.now_ist().utcoffset(), timedelta(hours=5, minutes=30)
        )

    def test_t03_same_day_must_be_strictly_future(self) -> None:
        self.assert_visit_error("2026-10-25", "11:59", "in_the_past")
        self.assert_visit_error("2026-10-25", "12:00", "in_the_past")
        accepted = commitments.parse_visit("2026-10-25", "12:01", FIXED_NOW)
        self.assertEqual(accepted[1].isoformat(timespec="minutes"), "12:01")

    def test_t04_hours_horizon_and_check_order(self) -> None:
        midnight = FIXED_NOW.replace(hour=0, minute=0)
        for value, expected in (
            ("08:59", "outside_hours"),
            ("19:01", "outside_hours"),
        ):
            with self.subTest(value=value):
                result = commitments.parse_visit("2026-10-26", value, midnight)
                self.assertEqual(result.reason, expected)

        for value in ("09:00", "19:00"):
            with self.subTest(value=value):
                result = commitments.parse_visit("2026-10-26", value, midnight)
                self.assertNotIsInstance(result, commitments.VisitError)

        accepted_date = (midnight.date() + timedelta(days=90)).isoformat()
        refused_date = (midnight.date() + timedelta(days=91)).isoformat()
        self.assertNotIsInstance(
            commitments.parse_visit(accepted_date, "09:00", midnight),
            commitments.VisitError,
        )
        self.assert_visit_error(refused_date, "09:00", "too_far")

        past_outside_hours = midnight.replace(hour=8)
        result = commitments.parse_visit("2026-10-25", "07:00", past_outside_hours)
        self.assertEqual(result.reason, "in_the_past")
        far_date = (midnight.date() + timedelta(days=91)).isoformat()
        result = commitments.parse_visit(far_date, "03:00", midnight)
        self.assertEqual(result.reason, "too_far")


class CommitmentIOTests(unittest.IsolatedAsyncioTestCase):
    async def test_t10_booking_retry_uses_upsert_contract(self) -> None:
        session = ScriptedSession([(201, [{"id": "a1b2c3d4-full"}])])
        row = {
            "kind": "site_visit",
            "call_sid": "call-1",
            "visit_date": "2026-10-26",
            "visit_time": "11:00",
        }
        with patch.dict(os.environ, FAKE_ENV, clear=True):
            reference = await commitments.store_commitment(session, row)

        self.assertEqual(reference, "a1b2c3d4-full")
        call = session.calls[0]
        self.assertIn(
            "on_conflict=call_sid,kind,visit_date,visit_time", call["url"]
        )
        self.assertIn("resolution=merge-duplicates", call["headers"]["Prefer"])
        self.assertIsNone(call["json"]["superseded_at"])

    async def test_wrapped_http_errors_suppress_the_raw_exception_context(self) -> None:
        with patch.dict(os.environ, FAKE_ENV, clear=True):
            with self.assertRaises(commitments.CommitmentError) as store_error:
                await commitments.store_commitment(
                    ExplodingSession(), {"kind": "callback_request"}
                )
            with self.assertRaises(commitments.AlertError) as alert_error:
                await commitments.send_alert(ExplodingSession(), "safe")
        for wrapped in (store_error.exception, alert_error.exception):
            self.assertIsNone(wrapped.__cause__)
            self.assertTrue(wrapped.__suppress_context__)

    async def test_t17_alert_text_is_plain_and_redacted(self) -> None:
        session = ScriptedSession([(200, {"ok": True})])
        note = "call 98765 43210 " + "n" * 250
        with patch.dict(os.environ, FAKE_ENV, clear=True):
            await commitments.send_alert(
                session,
                commitments.booking_alert_text(
                    "a1b2c3d4-full",
                    date_value=datetime(2026, 10, 31).date(),
                    time_value=datetime(2026, 10, 31, 11, 0).time(),
                    note=note,
                    phone="+919876543210",
                    replaces=[(datetime(2026, 11, 1).date(), datetime(2026, 11, 1, 11).time())],
                ),
            )

        payload = session.calls[0]["json"]
        self.assertTrue(payload["text"].startswith("Updated booking"))
        self.assertIn("replaces Sun 1 Nov, 11:00", payload["text"])
        self.assertIn("Phone: ends 3210", payload["text"])
        self.assertNotIn("9876543210", payload["text"])
        self.assertNotIn("98765 43210", payload["text"])
        self.assertNotIn("parse_mode", payload)
        note_line = next(
            line for line in payload["text"].splitlines() if line.startswith("Note: ")
        )
        self.assertLessEqual(len(note_line.removeprefix("Note: ")), 200)

    def test_t18_pick_lead_phone_excludes_our_configured_exotel_number(self) -> None:
        cases = (
            (CallData("+919876543210", "08045678901"), "08045678901", "+919876543210", "from", "lead_from"),
            (CallData("08045678901", "09876543210"), "08045678901", "+919876543210", "to", "lead_to"),
            (CallData("919876543210", "08045678901"), None, None, "none", "own_unknown"),
            (CallData("+919876543210", "+919123456789"), "08045678901", None, "none", "both_differ"),
            (CallData("08045678901", "08045678901"), "08045678901", None, "none", "neither_differs"),
        )
        for call_data, own, phone, field, reason in cases:
            with self.subTest(field=field, reason=reason):
                self.assertEqual(
                    commitments.pick_lead_phone(call_data, own), (phone, field, reason)
                )


class ToolBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def book(
        self,
        resources: tools.CallResources,
        preferred_date: str,
        preferred_time: str,
        *,
        worker=None,
        patch_clock: bool = True,
    ) -> ResultCapture:
        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": preferred_date, "preferred_time": preferred_time},
            resources,
            worker=worker,
        )
        with patch.dict(os.environ, FAKE_ENV, clear=True):
            if patch_clock:
                with patch.object(commitments, "now_ist", return_value=FIXED_NOW):
                    await tools.book_site_visit(params)
            else:
                await tools.book_site_visit(params)
        return capture

    async def wait_for_commitment_workflows(self) -> None:
        for _ in range(100):
            if not tools._IN_FLIGHT_COMMITMENTS:
                return
            await asyncio.sleep(0)
        self.fail("commitment workflow did not finish")

    async def test_t05_refusal_is_fixed_speech_without_second_llm(self) -> None:
        worker = FakeWorker()
        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": "bad", "preferred_time": "11:00"},
            tools.CallResources("call-1"),
            worker=worker,
        )
        await tools.book_site_visit(params)

        self.assertEqual(capture.result["status"], "error")
        self.assertFalse(capture.properties.run_llm)
        self.assertEqual(len(worker.frames), 1)
        self.assertIsInstance(worker.frames[0], TTSSpeakFrame)
        self.assertEqual(worker.frames[0].text, commitments.DATE_UNUSABLE)
        for sentence in (
            commitments.BOOKING_NOT_CONFIRMED,
            commitments.CALLBACK_NOT_PASSED_ON,
            commitments.PAST_TIME,
            commitments.PAST_DATE,
            commitments.TIME_UNUSABLE,
            commitments.OUTSIDE_HOURS,
            commitments.TOO_FAR,
            commitments.DATE_UNUSABLE,
        ):
            self.assertIsNone(__import__("re").search(r"\d", sentence))
            for phrase in ("shortly", "soon", "right away"):
                self.assertNotIn(phrase, sentence.lower())
        self.assertEqual((commitments.VISIT_OPEN.hour, commitments.VISIT_CLOSE.hour), (9, 19))
        self.assertIn("nine", commitments.OUTSIDE_HOURS)
        self.assertIn("seven", commitments.OUTSIDE_HOURS)
        self.assertEqual(commitments.BOOKING_HORIZON_DAYS, 90)
        self.assertIn("three months", commitments.TOO_FAR)

        with patch.object(tools.logger, "warning") as log_warning:
            no_worker_params, no_worker_capture = tool_params(
                "book_site_visit",
                {"preferred_date": "bad", "preferred_time": "11:00"},
                tools.CallResources("call-1"),
            )
            await tools.book_site_visit(no_worker_params)
        self.assertEqual(no_worker_capture.result["say"], commitments.DATE_UNUSABLE)
        self.assertTrue(any("no pipeline worker" in str(call) for call in log_warning.call_args_list))

    async def test_t06_booking_orders_store_alert_patch_before_success(self) -> None:
        session = ScriptedSession(
            [(201, [{"id": "a1b2c3d4-full"}]), (200, {"ok": True}), (204, None)]
        )
        redis = FakeRedis()
        resources = tools.CallResources(
            "call-1", redis=redis, http_session=session, lead_phone="+919876543210"
        )
        params, capture = tool_params(
            "book_site_visit",
            {
                "preferred_date": "2026-10-26",
                "preferred_time": "11:00",
                "notes": "quiet floor 98765 43210",
            },
            resources,
        )
        with (
            patch.dict(os.environ, FAKE_ENV, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            await tools.book_site_visit(params)

        self.assertEqual([call["method"] for call in session.calls], ["POST", "POST", "PATCH"])
        row = session.calls[0]["json"]
        self.assertEqual(row["project_slug"], "nxlyr-demo")
        self.assertEqual(row["call_sid"], "call-1")
        self.assertEqual(row["visit_date"], "2026-10-26")
        self.assertEqual(row["visit_time"], "11:00")
        self.assertEqual(row["phone_normalized"], "+919876543210")
        self.assertNotIn("98765 43210", row["notes"])
        self.assertFalse(any("end_call" in key for key in row))
        self.assertEqual(capture.result["status"], "booked")
        self.assertEqual(capture.result["reference"], "a1b2c3d4-full")
        self.assertIsNone(capture.properties)
        self.assertEqual(redis.values["site_visit_booked"], "true")

    async def test_t07_store_failure_never_claims_booked(self) -> None:
        for status in (400, 500):
            with self.subTest(status=status):
                session = ScriptedSession([(status, {"secret": "do-not-log"})])
                redis = FakeRedis()
                worker = FakeWorker()
                params, capture = tool_params(
                    "book_site_visit",
                    {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
                    tools.CallResources("call-1", redis=redis, http_session=session),
                    worker=worker,
                )
                with (
                    patch.dict(os.environ, FAKE_ENV, clear=True),
                    patch.object(commitments, "now_ist", return_value=FIXED_NOW),
                ):
                    await tools.book_site_visit(params)
                self.assertEqual(capture.result["status"], "not_confirmed")
                self.assertNotIn("booked", repr(capture.result).lower())
                self.assertFalse(capture.properties.run_llm)
                self.assertEqual(len(session.calls), 1)
                self.assertNotIn("site_visit_booked", redis.values)
                self.assertEqual(worker.frames[0].text, commitments.BOOKING_NOT_CONFIRMED)

        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-1", http_session=ScriptedSession([])),
            worker=FakeWorker(),
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            await tools.book_site_visit(params)
        self.assertEqual(capture.result["status"], "not_confirmed")

    async def test_t08_alert_failure_leaves_row_unmarked_and_flags_unset(self) -> None:
        session = ScriptedSession(
            [(201, [{"id": "a1b2c3d4-full"}]), (200, {"ok": False})]
        )
        redis = FakeRedis()
        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-1", redis=redis, http_session=session),
            worker=FakeWorker(),
        )
        with (
            patch.dict(os.environ, FAKE_ENV, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            await tools.book_site_visit(params)
        self.assertEqual(capture.result["status"], "not_confirmed")
        self.assertEqual([call["method"] for call in session.calls], ["POST", "POST"])
        self.assertNotIn("site_visit_booked", redis.values)

        missing_token_env = dict(FAKE_ENV)
        missing_token_env.pop("TELEGRAM_BOT_TOKEN")
        missing_session = ScriptedSession([(201, [{"id": "ref-2"}])])
        missing_params, missing_capture = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-2", http_session=missing_session),
            worker=FakeWorker(),
        )
        with (
            patch.dict(os.environ, missing_token_env, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            await tools.book_site_visit(missing_params)
        self.assertEqual(missing_capture.result["status"], "not_confirmed")
        self.assertEqual(len(missing_session.calls), 1)

        for alert_session, alert_timeout in (
            (ScriptedSession([(201, [{"id": "ref-3"}]), (400, {"ok": False})]), None),
            (SlowAlertSession(), 0.02),
        ):
            with self.subTest(alert_session=type(alert_session).__name__):
                failed_params, failed_capture = tool_params(
                    "book_site_visit",
                    {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
                    tools.CallResources("call-alert", http_session=alert_session),
                    worker=FakeWorker(),
                )
                timeout_patch = patch.object(
                    commitments,
                    "ALERT_TIMEOUT_S",
                    alert_timeout if alert_timeout is not None else commitments.ALERT_TIMEOUT_S,
                )
                with (
                    patch.dict(os.environ, FAKE_ENV, clear=True),
                    patch.object(commitments, "now_ist", return_value=FIXED_NOW),
                    timeout_patch,
                ):
                    await tools.book_site_visit(failed_params)
                self.assertEqual(failed_capture.result["status"], "not_confirmed")
                self.assertEqual(len(alert_session.calls), 2)

    async def test_t09_alert_marker_failure_does_not_retract_success(self) -> None:
        session = ScriptedSession(
            [(201, [{"id": "a1b2c3d4-full"}]), (200, {"ok": True}), (500, None)]
        )
        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-1", redis=FakeRedis(), http_session=session),
        )
        with patch.object(commitments.logger, "warning") as log_warning:
            with (
                patch.dict(os.environ, FAKE_ENV, clear=True),
                patch.object(commitments, "now_ist", return_value=FIXED_NOW),
            ):
                await tools.book_site_visit(params)
        self.assertEqual(capture.result["status"], "booked")
        self.assertEqual(
            sum("alert marker FAILED" in str(call) for call in log_warning.call_args_list),
            1,
        )

    async def test_slow_alert_marker_returns_booked_and_alerts_once(self) -> None:
        session = MemorySession()
        session.mark_release = asyncio.Event()
        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-1", http_session=session),
        )
        with (
            patch.dict(os.environ, FAKE_ENV, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
            patch.object(commitments, "COMMIT_TIMEOUT_S", 0.03),
            patch.object(commitments, "STORE_TIMEOUT_S", 0.06),
        ):
            await tools.book_site_visit(params)
        self.assertEqual(capture.result["status"], "booked")
        self.assertEqual(len(session.alerts), 1)
        self.assertIsNone(session.rows[0]["alert_sent_at"])

    async def test_t11_redis_failure_is_best_effort_after_real_success(self) -> None:
        session = ScriptedSession(
            [(201, [{"id": "a1b2c3d4-full"}]), (200, {"ok": True}), (204, None)]
        )
        with patch.object(tools.logger, "error") as log_error:
            params, capture = tool_params(
                "book_site_visit",
                {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
                tools.CallResources("call-1", redis=FakeRedis(fail=True), http_session=session),
            )
            with (
                patch.dict(os.environ, FAKE_ENV, clear=True),
                patch.object(commitments, "now_ist", return_value=FIXED_NOW),
            ):
                await tools.book_site_visit(params)
        self.assertEqual(capture.result["status"], "booked")
        self.assertEqual(
            sum("flags write FAILED" in str(call) for call in log_error.call_args_list),
            1,
        )

    async def test_success_result_precedes_a_hung_redis_write(self) -> None:
        class HangingPipeline(FakePipeline):
            async def execute(self):
                await asyncio.Event().wait()

        class HangingRedis(FakeRedis):
            def pipeline(self, transaction=True):
                return HangingPipeline(self)

        session = ScriptedSession(
            [(201, [{"id": "ref-1"}]), (200, {"ok": True}), (204, None)]
        )
        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-1", redis=HangingRedis(), http_session=session),
        )
        with (
            patch.dict(os.environ, FAKE_ENV, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
            patch.object(tools, "FLAGS_TIMEOUT_S", 0.05),
        ):
            task = asyncio.create_task(tools.book_site_visit(params))
            await asyncio.wait_for(capture.called.wait(), timeout=0.03)
            self.assertEqual(capture.result["status"], "booked")
            await task

    async def test_t12_booking_cannot_overwrite_a_completed_end_flag(self) -> None:
        for end_first in (True, False):
            with self.subTest(end_first=end_first):
                redis = FakeRedis()
                resources = tools.CallResources("call-1", redis=redis, http_session=object())
                release = asyncio.Event()
                started = asyncio.Event()

                async def controlled_visit(*args, **kwargs):
                    started.set()
                    await release.wait()
                    return commitments.CommitResult("ref-1")

                with (
                    patch.object(commitments, "commit_visit", controlled_visit),
                    patch.object(commitments, "now_ist", return_value=FIXED_NOW),
                ):
                    if end_first:
                        booking_task = asyncio.create_task(
                            self.book(resources, "2026-10-26", "11:00")
                        )
                        await started.wait()
                    else:
                        release.set()
                        await self.book(resources, "2026-10-26", "11:00")

                    worker = FakeWorker()
                    end_params, end_capture = tool_params(
                        "end_call",
                        {"outcome": "site_visit_booked"},
                        resources,
                        worker=worker,
                    )
                    await tools.end_call(end_params)
                    await end_capture.properties.on_context_updated()
                    if end_first:
                        release.set()
                        await booking_task

                self.assertEqual(redis.values["end_call_tool_invoked"], "true")

    async def test_t13_end_flag_is_written_only_when_stop_is_scheduled(self) -> None:
        redis = FakeRedis()
        worker = FakeWorker()
        params, capture = tool_params(
            "end_call",
            {"outcome": "qualified_interested"},
            tools.CallResources("call-1", redis=redis),
            worker=worker,
        )
        await tools.end_call(params)
        self.assertNotIn("end_call_tool_invoked", redis.values)
        await capture.properties.on_context_updated()
        self.assertEqual(redis.values["end_call_tool_invoked"], "true")
        self.assertTrue(worker.stopped)

    async def test_t14_cancelled_handlers_finish_their_commit(self) -> None:
        for handler_name in ("book_site_visit", "transfer_to_human"):
            with self.subTest(handler=handler_name):
                started = asyncio.Event()
                release = asyncio.Event()
                completed = asyncio.Event()

                async def controlled(*args, **kwargs):
                    started.set()
                    await release.wait()
                    completed.set()
                    return commitments.CommitResult("ref-1")

                target = (
                    commitments.commit_visit
                    if handler_name == "book_site_visit"
                    else commitments.commit_callback
                )
                arguments = (
                    {"preferred_date": "2026-10-26", "preferred_time": "11:00"}
                    if handler_name == "book_site_visit"
                    else {"reason": "manager", "context_summary": "question"}
                )
                params, _ = tool_params(
                    handler_name,
                    arguments,
                    tools.CallResources("call-1", http_session=object()),
                )
                with (
                    patch.object(commitments, target.__name__, controlled),
                    patch.object(commitments, "now_ist", return_value=FIXED_NOW),
                ):
                    task = asyncio.create_task(getattr(tools, handler_name)(params))
                    await started.wait()
                    task.cancel()
                    await asyncio.sleep(0)
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                await asyncio.wait_for(completed.wait(), timeout=0.1)

    async def test_s3a_cancel_after_alert_still_finalizes_correction(self) -> None:
        session = MemorySession()
        redis = FakeRedis()
        resources = tools.CallResources("call-s3a", redis=redis, http_session=session)
        await self.book(resources, "2026-11-01", "11:00")
        session.alert_delivered = asyncio.Event()
        session.alert_release = asyncio.Event()
        params, _ = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-31", "preferred_time": "11:00"},
            resources,
        )
        with (
            patch.dict(os.environ, FAKE_ENV, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            task = asyncio.create_task(tools.book_site_visit(params))
            await session.alert_delivered.wait()
            task.cancel()
            session.alert_release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await self.wait_for_commitment_workflows()
        self.assertEqual(len(session.alerts), 2)
        new_row = next(row for row in session.rows if row["visit_date"] == "2026-10-31")
        old_row = next(row for row in session.rows if row["visit_date"] == "2026-11-01")
        self.assertIsNotNone(new_row["alert_sent_at"])
        self.assertIsNotNone(old_row["superseded_at"])
        self.assertEqual(redis.values["site_visit_booked"], "true")

    async def test_s3b_cancel_when_result_callback_starts_still_finalizes(self) -> None:
        session = MemorySession()
        redis = FakeRedis()
        resources = tools.CallResources("call-s3b", redis=redis, http_session=session)
        await self.book(resources, "2026-11-01", "11:00")
        capture = CancellingResultCapture()
        params = FunctionCallParams(
            function_name="book_site_visit",
            tool_call_id="test-call",
            arguments={"preferred_date": "2026-10-31", "preferred_time": "11:00"},
            llm=None,
            pipeline_worker=None,
            context=None,
            result_callback=capture,
            app_resources=resources,
        )
        with (
            patch.dict(os.environ, FAKE_ENV, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            task = asyncio.create_task(tools.book_site_visit(params))
            with self.assertRaises(asyncio.CancelledError):
                await task
            await self.wait_for_commitment_workflows()
        self.assertEqual(capture.result["status"], "booked")
        self.assertEqual(len(session.alerts), 2)
        new_row = next(row for row in session.rows if row["visit_date"] == "2026-10-31")
        old_row = next(row for row in session.rows if row["visit_date"] == "2026-11-01")
        self.assertIsNotNone(new_row["alert_sent_at"])
        self.assertIsNotNone(old_row["superseded_at"])
        self.assertEqual(redis.values["site_visit_booked"], "true")

    async def test_s3c_cancel_during_marker_still_writes_flags(self) -> None:
        session = MemorySession()
        redis = FakeRedis()
        resources = tools.CallResources("call-s3c", redis=redis, http_session=session)
        await self.book(resources, "2026-11-01", "11:00")
        session.mark_release = asyncio.Event()
        capture = BlockingResultCapture()
        params = FunctionCallParams(
            function_name="book_site_visit",
            tool_call_id="test-call",
            arguments={"preferred_date": "2026-10-31", "preferred_time": "11:00"},
            llm=None,
            pipeline_worker=None,
            context=None,
            result_callback=capture,
            app_resources=resources,
        )
        with (
            patch.dict(os.environ, FAKE_ENV, clear=True),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            task = asyncio.create_task(tools.book_site_visit(params))
            await capture.called.wait()
            while not any(call.get("label") == "mark_alerted" for call in session.calls):
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            session.mark_release.set()
            await self.wait_for_commitment_workflows()
        self.assertEqual(len(session.alerts), 2)
        new_row = next(row for row in session.rows if row["visit_date"] == "2026-10-31")
        old_row = next(row for row in session.rows if row["visit_date"] == "2026-11-01")
        self.assertIsNotNone(new_row["alert_sent_at"])
        self.assertIsNotNone(old_row["superseded_at"])
        self.assertEqual(redis.values["site_visit_booked"], "true")

    async def test_t15_parallel_tools_keep_both_flags(self) -> None:
        async def visit(*args, **kwargs):
            await asyncio.sleep(0)
            return commitments.CommitResult("visit-ref")

        async def callback(*args, **kwargs):
            await asyncio.sleep(0)
            return commitments.CommitResult("callback-ref")

        with (
            patch.object(commitments, "commit_visit", visit),
            patch.object(commitments, "commit_callback", callback),
            patch.object(commitments, "now_ist", return_value=FIXED_NOW),
        ):
            for _ in range(200):
                redis = FakeRedis()
                resources = tools.CallResources("call-1", redis=redis, http_session=object())
                book_params, _ = tool_params(
                    "book_site_visit",
                    {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
                    resources,
                )
                transfer_params, _ = tool_params(
                    "transfer_to_human",
                    {"reason": "manager", "context_summary": "question"},
                    resources,
                )
                await asyncio.gather(
                    tools.book_site_visit(book_params),
                    tools.transfer_to_human(transfer_params),
                )
                self.assertEqual(redis.values["site_visit_booked"], "true")
                self.assertEqual(redis.values["transfer_requested"], "true")
                self.assertEqual(len(redis.pipelines), 2)
                self.assertTrue(all(pipeline.transaction for pipeline in redis.pipelines))
                self.assertTrue(
                    all(
                        sum(operation[0] in {"hset", "hsetnx"} for operation in pipeline.operations)
                        >= 1
                        and pipeline.operations[-1][0] == "expire"
                        for pipeline in redis.pipelines
                    )
                )

    async def test_t16_callback_requires_row_and_alert(self) -> None:
        session = ScriptedSession(
            [(201, [{"id": "callback-ref"}]), (200, {"ok": True}), (204, None)]
        )
        redis = FakeRedis()
        params, capture = tool_params(
            "transfer_to_human",
            {"reason": "manager", "context_summary": "x" * 600},
            tools.CallResources("call-1", redis=redis, http_session=session),
        )
        with patch.dict(os.environ, FAKE_ENV, clear=True):
            await tools.transfer_to_human(params)
        row = session.calls[0]["json"]
        self.assertEqual(row["kind"], "callback_request")
        self.assertEqual(len(row["notes"]), 500)
        self.assertTrue(session.calls[1]["json"]["text"].startswith("Callback request"))
        self.assertEqual(
            [call["method"] for call in session.calls], ["POST", "POST", "PATCH"]
        )
        self.assertEqual(capture.result["status"], "passed_on")
        self.assertIn("I've passed your question to a colleague", capture.result["next_step"])
        self.assertEqual(redis.values["transfer_requested"], "true")

        for responses in (
            [(500, {})],
            [(201, [{"id": "callback-ref"}]), (500, {"ok": False})],
        ):
            failed_redis = FakeRedis()
            worker = FakeWorker()
            failed_params, failed_capture = tool_params(
                "transfer_to_human",
                {"reason": "manager", "context_summary": "question"},
                tools.CallResources(
                    "call-1", redis=failed_redis, http_session=ScriptedSession(responses)
                ),
                worker=worker,
            )
            with patch.dict(os.environ, FAKE_ENV, clear=True):
                await tools.transfer_to_human(failed_params)
            self.assertEqual(failed_capture.result["status"], "not_passed_on")
            self.assertFalse(failed_capture.properties.run_llm)
            self.assertEqual(worker.frames[0].text, commitments.CALLBACK_NOT_PASSED_ON)
            self.assertNotIn("transfer_requested", failed_redis.values)

    async def test_t19_pre_call_log_reports_only_length_and_whole_done_words(self) -> None:
        cases = (
            ("Let me note that down.", "no"),
            ("I've booked that.", "yes"),
            ("All done.", "yes"),
            ("Confirmed.", "yes"),
            ("undone", "no"),
            ("Bookings", "no"),
        )
        for text, expected in cases:
            with patch.object(tools.logger, "info") as log_info:
                params, _ = tool_params(
                    "book_site_visit",
                    {"preferred_date": "bad", "preferred_time": "11:00"},
                    tools.CallResources("call-1"),
                    context=LLMContext(messages=[{"role": "assistant", "content": text}]),
                )
                await tools.book_site_visit(params)
            record = next(
                call
                for call in log_info.call_args_list
                if "pre_call_text_chars" in str(call)
            )
            self.assertIn(str(len(text)), str(record))
            self.assertIn(expected, str(record))
            self.assertNotIn(text, str(log_info.call_args_list))

        for context, chars, done in (
            (LLMContext(messages=[]), "0", "no"),
            (None, "unknown", "unknown"),
        ):
            with patch.object(tools.logger, "info") as log_info:
                params, _ = tool_params(
                    "book_site_visit",
                    {"preferred_date": "bad", "preferred_time": "11:00"},
                    tools.CallResources("call-1"),
                    context=context,
                )
                await tools.book_site_visit(params)
            record = next(
                call
                for call in log_info.call_args_list
                if "pre_call_text_chars" in str(call)
            )
            self.assertIn(chars, str(record))
            self.assertIn(done, str(record))

    async def test_t20_failure_logs_do_not_echo_sensitive_exception_text(self) -> None:
        with patch.object(tools.logger, "error") as log_error:
            params, capture = tool_params(
                "book_site_visit",
                {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
                tools.CallResources(
                    "call-1",
                    http_session=ExplodingSession(),
                    lead_phone="+919876543210",
                ),
                worker=FakeWorker(),
            )
            with (
                patch.dict(os.environ, FAKE_ENV, clear=True),
                patch.object(commitments, "now_ist", return_value=FIXED_NOW),
            ):
                await tools.book_site_visit(params)
        self.assertEqual(capture.result["status"], "not_confirmed")
        combined = str(log_error.call_args_list)
        for secret in FAKE_ENV.values():
            self.assertNotIn(secret, combined)
        self.assertNotIn("9876543210", combined)
        self.assertNotIn("token=", combined)

    async def test_all_tool_logs_exclude_model_free_text_and_error_strings(self) -> None:
        note = "note-private-marker"
        reason = "reason-private-marker"
        summary = "summary-private-marker"
        outcome = "outcome-private-marker"
        error_text = "aiohttp-error-private-marker"
        with patch.object(logger, "_log") as log_call:
            book_params, _ = tool_params(
                "book_site_visit",
                {"preferred_date": "2026-10-26", "preferred_time": "11:00", "notes": note},
                tools.CallResources(
                    "call-1",
                    http_session=AlertExplodingSession([(201, [{"id": "ref-1"}])]),
                ),
                worker=FakeWorker(),
            )
            transfer_params, _ = tool_params(
                "transfer_to_human",
                {"reason": reason, "context_summary": summary},
                tools.CallResources("call-2", http_session=ScriptedSession([(500, {})])),
                worker=FakeWorker(),
            )
            end_params, _ = tool_params(
                "end_call",
                {"outcome": outcome, "summary": summary},
                tools.CallResources("call-3"),
            )
            with (
                patch.dict(os.environ, FAKE_ENV, clear=True),
                patch.object(commitments, "now_ist", return_value=FIXED_NOW),
            ):
                await tools.book_site_visit(book_params)
                await tools.transfer_to_human(transfer_params)
                await tools.end_call(end_params)
        output = str(log_call.call_args_list)
        for private in (note, reason, summary, outcome, error_text):
            self.assertNotIn(private, output)

    async def test_missing_call_sid_refuses_without_writing_or_alerting(self) -> None:
        for handler, arguments, status in (
            (tools.book_site_visit, {"preferred_date": "2026-10-26", "preferred_time": "11:00"}, "not_confirmed"),
            (tools.transfer_to_human, {"reason": "manager", "context_summary": "question"}, "not_passed_on"),
        ):
            with self.subTest(handler=handler.__name__):
                session = MemorySession()
                params, capture = tool_params(
                    handler.__name__, arguments, tools.CallResources(None, http_session=session), worker=FakeWorker()
                )
                with (
                    patch.dict(os.environ, FAKE_ENV, clear=True),
                    patch.object(commitments, "now_ist", return_value=FIXED_NOW),
                ):
                    await handler(params)
                self.assertEqual(capture.result["status"], status)
                self.assertEqual(session.calls, [])

    async def test_failure_logs_real_elapsed_stage_timings(self) -> None:
        params, _ = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-1", http_session=SlowSession()),
            worker=FakeWorker(),
        )
        with patch.object(tools.logger, "error") as log_error:
            with (
                patch.dict(os.environ, FAKE_ENV, clear=True),
                patch.object(commitments, "now_ist", return_value=FIXED_NOW),
                patch.object(commitments, "STORE_TIMEOUT_S", 0.02),
                patch.object(commitments, "COMMIT_TIMEOUT_S", 0.1),
            ):
                await tools.book_site_visit(params)
        failure = next(call for call in log_error.call_args_list if "commitment FAILED" in str(call))
        self.assertGreater(failure.args[-2], 0)
        self.assertEqual(failure.args[-1], 0)

    async def test_t21_total_commit_timeout_is_bounded_and_logged(self) -> None:
        params, capture = tool_params(
            "book_site_visit",
            {"preferred_date": "2026-10-26", "preferred_time": "11:00"},
            tools.CallResources("call-1", http_session=SlowSession()),
            worker=FakeWorker(),
        )
        started = asyncio.get_running_loop().time()
        with patch.object(tools.logger, "error") as log_error:
            with (
                patch.dict(os.environ, FAKE_ENV, clear=True),
                patch.object(commitments, "now_ist", return_value=FIXED_NOW),
                patch.object(commitments, "COMMIT_TIMEOUT_S", 0.2),
            ):
                await tools.book_site_visit(params)
        elapsed = asyncio.get_running_loop().time() - started
        self.assertLess(elapsed, 0.5)
        self.assertEqual(capture.result["status"], "not_confirmed")
        failure = next(
            call
            for call in log_error.call_args_list
            if "commitment FAILED" in str(call)
        )
        self.assertIn("db_ms=", str(failure))
        self.assertIn("tg_ms=", str(failure))

    def test_t22_booking_schema_requires_date_and_time(self) -> None:
        self.assertEqual(
            tools.BOOK_SITE_VISIT_SCHEMA.required,
            ["preferred_date", "preferred_time"],
        )
        self.assertIn("does not end the call", tools.BOOK_SITE_VISIT_SCHEMA.description)

    def test_t23_prompt_uses_ist_date_and_shared_callback_rule(self) -> None:
        clock = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
        old_rule = (
            "- transfer_to_human only logs a request. It connects nobody and "
            "schedules nothing: say a colleague will follow up, with no time."
        )
        with patch.object(prompt, "now_ist", return_value=clock.astimezone(commitments.IST)):
            for version in ("v2", "v21"):
                with self.subTest(version=version):
                    text = prompt.build_system_prompt(project_kb={}, version=version)
                    self.assertIn("Today is Sunday, 25 October 2026", text)
                    self.assertEqual(text.count(prompt.TRANSFER_TO_HUMAN_RULE), 1)
                    self.assertNotIn(old_rule, text)

    async def test_t24_correction_keeps_one_live_row_and_orders_side_effects(self) -> None:
        session = MemorySession()
        resources = tools.CallResources("call-1", redis=FakeRedis(), http_session=session)
        first = await self.book(resources, "2026-11-01", "11:00")
        second = await self.book(resources, "2026-10-31", "11:00")

        self.assertEqual(first.result["status"], "booked")
        self.assertEqual(second.result["status"], "booked")
        live = [row for row in session.rows if row.get("superseded_at") is None]
        old = [row for row in session.rows if row.get("superseded_at") is not None]
        self.assertEqual([(row["visit_date"], row["visit_time"]) for row in live], [("2026-10-31", "11:00")])
        self.assertEqual([(row["visit_date"], row["visit_time"]) for row in old], [("2026-11-01", "11:00")])
        self.assertTrue(session.alerts[0].startswith("Site visit booked"))
        self.assertTrue(session.alerts[1].startswith("Updated booking"))
        self.assertIn("replaces Sun 1 Nov, 11:00", session.alerts[1])
        labels = [call["label"] for call in session.calls]
        self.assertEqual(labels[-5:], ["lookup", "insert", "alert", "mark_alerted", "supersede"])

    async def test_t25_flip_flop_revives_the_returned_booking(self) -> None:
        session = MemorySession()
        resources = tools.CallResources("call-1", http_session=session)
        await self.book(resources, "2026-11-01", "11:00")
        await self.book(resources, "2026-10-31", "11:00")
        third = await self.book(resources, "2026-11-01", "11:00")
        live = [row for row in session.rows if row.get("superseded_at") is None]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["visit_date"], "2026-11-01")
        self.assertIn("replaces Sat 31 Oct, 11:00", session.alerts[-1])
        self.assertIn("replaces", third.result)

    async def test_t26_failed_correction_leaves_first_booking_live(self) -> None:
        for fail_stage in ("insert", "alert"):
            with self.subTest(fail_stage=fail_stage):
                session = MemorySession()
                resources = tools.CallResources("call-1", http_session=session)
                await self.book(resources, "2026-11-01", "11:00")
                calls_before_second = len(session.calls)
                if fail_stage == "insert":
                    session.fail_next_insert = 500
                else:
                    session.fail_next_alert = 500
                second = await self.book(
                    resources, "2026-10-31", "11:00", worker=FakeWorker()
                )
                self.assertEqual(second.result["status"], "not_confirmed")
                first = next(row for row in session.rows if row["visit_date"] == "2026-11-01")
                self.assertIsNone(first.get("superseded_at"))
                self.assertFalse(
                    any(
                        call["label"] == "supersede"
                        for call in session.calls[calls_before_second:]
                    )
                )

    async def test_t27_unalerted_prior_row_is_superseded_without_update_claim(self) -> None:
        session = MemorySession()
        resources = tools.CallResources("call-1", http_session=session)
        await self.book(resources, "2026-11-01", "11:00")
        session.rows[0]["alert_sent_at"] = None
        await self.book(resources, "2026-10-31", "11:00")
        self.assertTrue(session.alerts[-1].startswith("Site visit booked"))
        self.assertNotIn("replaces", session.alerts[-1])
        self.assertIsNotNone(session.rows[0]["superseded_at"])

    async def test_t28_supersede_failure_keeps_truthful_success_and_warns(self) -> None:
        session = MemorySession()
        resources = tools.CallResources("call-1", http_session=session)
        await self.book(resources, "2026-11-01", "11:00")
        session.fail_supersede = True
        with patch.object(commitments.logger, "warning") as log_warning:
            second = await self.book(resources, "2026-10-31", "11:00")
        self.assertEqual(second.result["status"], "booked")
        self.assertTrue(session.alerts[-1].startswith("Updated booking"))
        self.assertEqual(
            sum(
                "supersede FAILED" in str(call)
                for call in log_warning.call_args_list
            ),
            1,
        )

    async def test_t29_lookup_repeat_concurrency_and_callback_boundaries(self) -> None:
        session = MemorySession()
        resources = tools.CallResources("call-1", http_session=session)
        await self.book(resources, "2026-11-01", "11:00")
        self.assertEqual(session.lookup_started, 0)
        await self.book(resources, "2026-11-01", "11:00")
        self.assertEqual(session.lookup_started, 1)
        self.assertTrue(session.alerts[-1].startswith("Site visit booked"))

        race_session = MemorySession()
        race_session.lookup_release = asyncio.Event()
        race_resources = tools.CallResources(
            "call-race", http_session=race_session, booking_attempts=1
        )
        with patch.object(commitments, "now_ist", return_value=FIXED_NOW):
            one = asyncio.create_task(
                self.book(
                    race_resources, "2026-10-31", "11:00", patch_clock=False
                )
            )
            two = asyncio.create_task(
                self.book(
                    race_resources, "2026-11-01", "11:00", patch_clock=False
                )
            )
            while race_session.lookup_started < 2:
                await asyncio.sleep(0)
            race_session.lookup_release.set()
            await asyncio.gather(one, two)
        self.assertEqual(
            len([row for row in race_session.rows if row.get("superseded_at") is None]),
            2,
        )

        callback_params, callback_capture = tool_params(
            "transfer_to_human",
            {"reason": "manager", "context_summary": "question"},
            resources,
        )
        with patch.dict(os.environ, FAKE_ENV, clear=True):
            await tools.transfer_to_human(callback_params)
        self.assertEqual(callback_capture.result["status"], "passed_on")
        self.assertEqual(session.lookup_started, 1)
        self.assertEqual(len([row for row in session.rows if row["kind"] == "callback_request"]), 1)


if __name__ == "__main__":
    unittest.main()
