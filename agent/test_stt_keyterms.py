import asyncio
import inspect
import io
import json
import logging
import re
import socket
import sys
import unittest
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import deepgram
from deepgram import AsyncDeepgramClient, DeepgramClientEnvironment
from deepgram.core.api_error import ApiError
from deepgram.core.query_encoder import encode_query
from deepgram.listen.v1.types import (
    ListenV1Results,
    ListenV1ResultsChannel,
    ListenV1ResultsChannelAlternativesItem,
    ListenV1ResultsMetadata,
)
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
from pipecat.transcriptions.language import Language
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.legacy.exceptions import InvalidStatusCode
from websockets.asyncio.server import serve

import log_scrub
import stt_keyterms
from scripts import probe_deepgram_multi


REAL_SHAPE_KB = {
    "project_name": "Meridian Heights",
    "developer": "Aetheria Realty Group",
    "location": {
        "city": "Gurugram",
        "sector": "Sector 79B",
        "landmark": "Near Southern Peripheral Road (SPR) & NH-8 Junction",
    },
}

LOCAL_WEBSOCKET_LOGGER = logging.getLogger("nxlyr.test.websocket")
LOCAL_WEBSOCKET_LOGGER.addHandler(logging.NullHandler())
LOCAL_WEBSOCKET_LOGGER.propagate = False


class LocalUpgradeServer:
    def __init__(self, name, rule) -> None:
        self.name = name
        self.rule = rule
        self.attempts: list[tuple[str, str | None, bool]] = []
        self.server = None
        self.port: int | None = None

    async def start(self, port: int = 0) -> None:
        async def handler(websocket) -> None:
            await websocket.wait_closed()

        def process_request(connection, request):
            query = parse_qs(urlparse(request.path).query)
            attempt = (
                self.name,
                query.get("language", [None])[0],
                "keyterm" in query,
            )
            self.attempts.append(attempt)
            status = self.rule(len(self.attempts), attempt)
            return (
                connection.respond(HTTPStatus(status), "rejected\n")
                if status
                else None
            )

        self.server = await serve(
            handler,
            "127.0.0.1",
            port,
            process_request=process_request,
            logger=LOCAL_WEBSOCKET_LOGGER,
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()


def local_deepgram_client(port: int) -> AsyncDeepgramClient:
    websocket_url = f"ws://127.0.0.1:{port}"
    http_url = f"http://127.0.0.1:{port}"
    environment_args = {
        "base": http_url,
        "production": websocket_url,
        "agent": websocket_url,
    }
    if "agent_rest" in inspect.signature(DeepgramClientEnvironment).parameters:
        environment_args["agent_rest"] = http_url
    return AsyncDeepgramClient(
        api_key="local-test-key",
        environment=DeepgramClientEnvironment(**environment_args),
    )


def reserve_local_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def result_message(transcript: str, languages: list[str] | None) -> ListenV1Results:
    alternative = ListenV1ResultsChannelAlternativesItem(
        transcript=transcript,
        confidence=1.0,
        languages=languages,
        words=[],
    )
    return ListenV1Results(
        channel_index=[0, 1],
        duration=1.0,
        start=0.0,
        is_final=True,
        speech_final=True,
        channel=ListenV1ResultsChannel(alternatives=[alternative]),
        metadata=ListenV1ResultsMetadata.model_construct(
            request_id="request",
            model_info=None,
            model_uuid="model",
        ),
    )


class KeytermTests(unittest.IsolatedAsyncioTestCase):
    def test_k01_real_shape_returns_only_expected_plain_unique_terms(self) -> None:
        terms = stt_keyterms.build_keyterms(REAL_SHAPE_KB)
        self.assertEqual(
            terms,
            [
                "Meridian Heights",
                "Aetheria Realty Group",
                "Gurugram",
                "Sector 79B",
                "crore",
                "crores",
                "lakh",
                "lakhs",
                "rupees",
                "BHK",
            ],
        )
        self.assertNotIn(REAL_SHAPE_KB["location"]["landmark"], terms)
        self.assertTrue(all(isinstance(term, str) and term and ":" not in term for term in terms))
        self.assertEqual(len({term.casefold() for term in terms}), len(terms))

    def test_k02_missing_non_string_and_duplicate_values_are_skipped(self) -> None:
        kb = {
            "project_name": " crore ",
            "developer": 42,
            "location": {"city": None, "sector": "bad:term"},
        }
        terms = stt_keyterms.build_keyterms(kb)
        self.assertEqual(terms.count("crore"), 1)
        self.assertNotIn(42, terms)
        self.assertNotIn("bad:term", terms)
        self.assertEqual(stt_keyterms.build_keyterms({}), list(stt_keyterms.FIXED_TERMS))

    def test_k03_term_and_estimated_token_caps_warn_without_logging_terms(self) -> None:
        huge = " ".join(f"private{i}" for i in range(500))
        kb = {"project_name": huge, "developer": huge, "location": {"city": huge, "sector": huge}}
        with patch.object(stt_keyterms.logger, "warning") as warning:
            terms = stt_keyterms.build_keyterms(kb)
        self.assertLessEqual(len(terms), 40)
        self.assertLessEqual(sum(len(term.split()) * 2 for term in terms), 400)
        warning.assert_called_once()
        self.assertNotIn("private", str(warning.call_args.args[0]))

    def test_k05_keyterms_and_numerals_reach_the_sdk_query_as_repeated_pairs(self) -> None:
        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            sample_rate=8000,
            settings=DeepgramSTTSettings(
                model="nova-3",
                language="en-IN",
                smart_format=True,
                interim_results=True,
                endpointing=300,
                keyterm=stt_keyterms.build_keyterms(REAL_SHAPE_KB),
                numerals=True,
            ),
            conn_id="abcdef",
            region="global",
            project_name="Meridian Heights",
        )
        kwargs = service._build_connect_kwargs()
        self.assertIsInstance(kwargs["keyterm"], list)
        self.assertEqual(kwargs["numerals"], "true")
        self.assertEqual(kwargs["language"], "en-IN")
        self.assertEqual(kwargs["model"], "nova-3")
        pairs = encode_query(kwargs)
        self.assertEqual(sum(key == "keyterm" for key, _ in pairs), len(kwargs["keyterm"]))

    def test_r1_f2_probe_uses_production_connect_parameters_and_live_kb_shape(self) -> None:
        params = probe_deepgram_multi.build_connect_params(
            REAL_SHAPE_KB,
            api_key="test",
            region="eu",
            keyterms=True,
            numerals=False,
        )
        self.assertEqual(params["keyterm"], stt_keyterms.build_keyterms(REAL_SHAPE_KB))
        production_service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            sample_rate=8000,
            settings=stt_keyterms.build_stt_settings(
                REAL_SHAPE_KB,
                language_mode="hinglish",
                keyterms=True,
                numerals=False,
            ),
            region="eu",
            hinglish=True,
            base_url="api.eu.deepgram.com",
        )
        production_service._sample_rate = 8000
        self.assertEqual(
            params,
            production_service._build_connect_kwargs(),
        )
        self.assertEqual(params["language"], "multi")
        self.assertEqual(params["sample_rate"], "8000")
        for name in (
            "punctuate",
            "profanity_filter",
            "numerals",
            "diarize",
            "detect_entities",
            "dictation",
            "multichannel",
        ):
            self.assertIn(name, params)

    async def test_r1_f2_probe_reports_connection_transcript_and_script_separately(self) -> None:
        class FakeSocket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> None:
                pass

            async def send(self, _payload) -> None:
                pass

            async def recv(self) -> str:
                return json.dumps(
                    {
                        "type": "Results",
                        "is_final": True,
                        "channel": {
                            "alternatives": [
                                {"transcript": "यह हिंदी है", "languages": ["hi"]}
                            ]
                        },
                    }
                )

        with patch.object(
            probe_deepgram_multi.websockets,
            "connect",
            return_value=FakeSocket(),
        ), patch.object(
            probe_deepgram_multi.asyncio, "sleep", new=AsyncMock()
        ), patch("builtins.print") as printed:
            await probe_deepgram_multi.probe_row(
                api_key="test",
                audio=b"audio",
                project_kb=REAL_SHAPE_KB,
                region="global",
                keyterms=True,
                numerals=False,
            )
        lines = [str(call.args[0]) for call in printed.call_args_list]
        self.assertTrue(any("connected=yes" in line for line in lines))
        self.assertTrue(
            any("transcript_received=yes" in line and "script=deva" in line for line in lines)
        )
        self.assertFalse(any("keyterm=" in line for line in lines))

    def test_r2_probe_defaults_to_harness_kb_and_live_kb_is_opt_in(self) -> None:
        parser = probe_deepgram_multi.build_arg_parser()
        defaults = parser.parse_args(["sample.wav"])
        self.assertEqual(defaults.kb_file, probe_deepgram_multi.DEFAULT_KB_PATH)
        self.assertFalse(defaults.live_kb)
        live = parser.parse_args(["sample.wav", "--live-kb"])
        self.assertTrue(live.live_kb)
        kb = probe_deepgram_multi.load_kb_file(defaults.kb_file)
        self.assertEqual(kb["project_name"], "Meridian Heights")

    def test_k06_eu_host_fallback_mismatch_and_unknown_path_are_visible(self) -> None:
        eu = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            base_url="api.eu.deepgram.com",
            conn_id="abcdef",
            region="eu",
            project_name="Meridian Heights",
        )
        production = eu._client._client_wrapper._environment.production
        self.assertEqual(production, "wss://api.eu.deepgram.com")

        with patch.object(
            deepgram, "DeepgramClientEnvironment", side_effect=RuntimeError("no")
        ), patch.object(stt_keyterms.logger, "info") as info, patch.object(
            stt_keyterms.logger, "warning"
        ) as warning:
            stt_keyterms.STTCheckingDeepgramService(
                api_key="test",
                base_url="api.eu.deepgram.com",
                conn_id="abcdef",
                region="eu",
                project_name="Meridian Heights",
            )
        self.assertIn("host=api.deepgram.com", str(info.call_args.args[0]))
        self.assertTrue(any("mismatch" in str(call.args[0]).lower() for call in warning.call_args_list))

        with patch.object(
            stt_keyterms.STTCheckingDeepgramService,
            "_endpoint_host",
            return_value="unknown",
        ), patch.object(stt_keyterms.logger, "info") as info:
            stt_keyterms.STTCheckingDeepgramService(
                api_key="test",
                conn_id="abcdef",
                region="global",
                project_name="Meridian Heights",
            )
        self.assertIn("host=unknown", str(info.call_args.args[0]))

        with patch.object(
            stt_keyterms.STTCheckingDeepgramService,
            "_endpoint_host",
            return_value="unknown",
        ), patch.object(stt_keyterms.logger, "warning") as warning:
            stt_keyterms.STTCheckingDeepgramService(
                api_key="test",
                conn_id="abcdef",
                region="eu",
                project_name="Meridian Heights",
            )
        self.assertTrue(
            any("mismatch" in str(call.args[0]).lower() for call in warning.call_args_list)
        )

    def test_k06_service_name_contains_capital_stt_for_latency_report(self) -> None:
        self.assertIn("STT", stt_keyterms.STTCheckingDeepgramService.__name__)

    async def test_k07_to_k09_sanitiser_examples_and_frame_forwarding(self) -> None:
        cases = {
            "tell me about Eridian Heights": 'project=near:"Eridian Heights" amount=none',
            "Meridian Heights": "project=exact amount=none",
            "my number is 98765 43210": "project=none amount=none",
            "my name is Rahul Verma and I live at 12 MG Road": "project=none amount=none",
            "1.2 crore": 'project=none amount="1.2 crore"',
            "about two": "project=none amount=none",
            "2": 'project=none amount="2 [no unit]"',
            "forty lakhs": 'project=none amount="forty lakhs"',
            "Meridian Rahul Verma": "project=near amount=none",
            "98 76 54 32 10 rupees": 'project=none amount="[number] rupees"',
            "my number is 98765 43210 lakh": 'project=none amount="[number] lakh"',
        }
        for transcript, expected in cases.items():
            with self.subTest(transcript=transcript):
                summary = stt_keyterms.summarize_transcript(transcript, "Meridian Heights")
                self.assertIn(expected, summary)
                self.assertIsNone(re.search(r"\d{5,}", summary))
                self.assertNotIn("Rahul", summary)
                self.assertNotIn("MG Road", summary)

        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            conn_id="abcdef",
            region="global",
            project_name="Meridian Heights",
        )
        final = TranscriptionFrame("1.2 crore", "u", "now")
        interim = InterimTranscriptionFrame("1.2", "u", "now")
        with patch.object(DeepgramSTTService, "push_frame", new=AsyncMock()) as push, patch.object(
            stt_keyterms.logger, "info"
        ) as info:
            await service.push_frame(final, FrameDirection.DOWNSTREAM)
            await service.push_frame(interim, FrameDirection.DOWNSTREAM)
        self.assertEqual(push.await_count, 2)
        self.assertIs(push.await_args_list[0].args[0], final)
        self.assertIs(push.await_args_list[1].args[0], interim)
        self.assertEqual(info.call_count, 1)

    async def test_l08_unknown_language_codes_never_drop_a_transcript(self) -> None:
        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            conn_id="abcdef",
            region="global",
            project_name="Meridian Heights",
            hinglish=True,
        )
        for languages, expected in (
            (["hi", "en"], Language.HI),
            (["hi-Latn"], None),
            (["xx"], None),
            (["bho"], None),
            (None, None),
        ):
            with self.subTest(languages=languages):
                message = result_message("private transcript", languages)
                with patch.object(
                    service, "push_frame", new=AsyncMock()
                ) as push, patch.object(
                    service, "_handle_transcription", new=AsyncMock()
                ), patch.object(
                    service, "stop_processing_metrics", new=AsyncMock()
                ):
                    await service._on_message(message)
                frame = push.await_args.args[0]
                self.assertIsInstance(frame, TranscriptionFrame)
                self.assertEqual(frame.text, "private transcript")
                self.assertEqual(frame.language, expected)

    def test_l09_hinglish_summary_reports_only_count_script_and_language(self) -> None:
        english = stt_keyterms.summarize_transcript(
            "Meridian Heights costs forty lakhs", "Meridian Heights"
        )
        self.assertEqual(
            english,
            'words=5 project=exact amount="forty lakhs"',
        )
        cases = (
            ("यह जानकारी यहाँ है", "hi", "words=4", "script=deva", "lang=hi"),
            ("this is private text", None, "words=4", "script=latin", "lang=none"),
            ("यह private जानकारी text", "hi-Latn", "words=4", "script=mixed", "lang=hi-Latn"),
            ("यह निजी जानकारी है", "private transcript", "words=4", "script=deva", "lang=other"),
        )
        for transcript, language, words, script, lang in cases:
            with self.subTest(transcript=transcript):
                summary = stt_keyterms.summarize_transcript(
                    transcript,
                    "Meridian Heights",
                    hinglish=True,
                    language_code=language,
                )
                self.assertIn(words, summary)
                self.assertIn(script, summary)
                self.assertIn(lang, summary)
                self.assertNotIn(transcript, summary)
                for word in transcript.split():
                    self.assertNotIn(word, summary)

    async def test_l09_hinglish_log_never_contains_transcript_text(self) -> None:
        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            conn_id="abcdef",
            region="global",
            project_name="Meridian Heights",
            hinglish=True,
        )
        service._nxlyr_language_code = "hi"
        transcript = "यह बहुत निजी जानकारी है"
        with patch.object(
            DeepgramSTTService, "push_frame", new=AsyncMock()
        ), patch.object(stt_keyterms.logger, "info") as info:
            await service.push_frame(TranscriptionFrame(transcript, "u", "now"))
        line = str(info.call_args.args[0])
        self.assertIn("script=deva", line)
        self.assertIn("lang=hi", line)
        self.assertNotIn(transcript, line)
        for word in transcript.split():
            self.assertNotIn(word, line)

    def test_l10_endpoint_line_includes_requested_language(self) -> None:
        for language, hinglish in (("en-IN", False), ("multi", True)):
            with self.subTest(language=language), patch.object(
                stt_keyterms.logger, "info"
            ) as info:
                stt_keyterms.STTCheckingDeepgramService(
                    api_key="test",
                    settings=DeepgramSTTSettings(
                        model="nova-3",
                        language=language,
                        endpointing=300,
                    ),
                    conn_id="abcdef",
                    region="global",
                    project_name="Meridian Heights",
                    hinglish=hinglish,
                )
            endpoint = next(
                str(call.args[0])
                for call in info.call_args_list
                if str(call.args[0]).startswith("stt endpoint:")
            )
            self.assertIn(f"language={language}", endpoint)

    async def _run_fallback_scenario(self, outcomes: list[Exception | None]):
        attempts: list[tuple[str, dict]] = []
        connected = asyncio.Event()
        pending = list(outcomes)

        class FakeConnection:
            def on(self, *_args) -> None:
                pass

            async def start_listening(self) -> None:
                connected.set()
                await asyncio.Event().wait()

        class FakeContext:
            def __init__(self, host: str, kwargs: dict) -> None:
                self.host = host
                self.kwargs = kwargs

            async def __aenter__(self):
                attempts.append((self.host, dict(self.kwargs)))
                outcome = pending.pop(0)
                if outcome is not None:
                    raise outcome
                return FakeConnection()

            async def __aexit__(self, *_args) -> None:
                pass

        class FakeV1:
            def __init__(self, host: str) -> None:
                self.host = host

            def connect(self, **kwargs):
                return FakeContext(self.host, kwargs)

        class FakeClient:
            def __init__(self, host: str) -> None:
                self.listen = SimpleNamespace(v1=FakeV1(host))

        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test-secret",
            sample_rate=8000,
            settings=DeepgramSTTSettings(
                model="nova-3",
                language="multi",
                smart_format=True,
                interim_results=True,
                endpointing=300,
                keyterm=["private project term"],
            ),
            conn_id="abcdef",
            region="eu",
            project_name="Meridian Heights",
            hinglish=True,
            base_url="api.eu.deepgram.com",
        )
        eu_client = FakeClient("eu")
        service._client = eu_client
        service._nxlyr_initial_client = eu_client

        async def cancel_task(task) -> None:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        service.create_task = lambda coro, *_args: asyncio.create_task(coro)
        service.cancel_task = cancel_task
        with patch.object(
            stt_keyterms, "AsyncDeepgramClient", return_value=FakeClient("global")
        ), patch.object(stt_keyterms, "sleep", new=AsyncMock()) as retry_sleep, patch.object(
            stt_keyterms.logger, "warning"
        ) as warning, patch.object(
            stt_keyterms.logger, "info"
        ) as info:
            task = asyncio.create_task(service._connection_handler())
            await asyncio.wait_for(connected.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        return attempts, retry_sleep, warning, info

    def test_r2_rejection_status_matches_installed_websockets_exceptions(self) -> None:
        self.assertEqual(
            stt_keyterms._websocket_rejection_status(
                InvalidStatusCode(400, Headers())
            ),
            400,
        )
        self.assertEqual(
            stt_keyterms._websocket_rejection_status(
                InvalidStatus(SimpleNamespace(status_code=422))
            ),
            422,
        )
        self.assertEqual(
            stt_keyterms._websocket_rejection_status(
                ApiError(
                    status_code=400,
                    headers={"Authorization": "Token private"},
                    body="rejected",
                )
            ),
            400,
        )
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.assertIsNone(
                    stt_keyterms._websocket_rejection_status(
                        ApiError(status_code=status)
                    )
                )
        self.assertIsNone(
            stt_keyterms._websocket_rejection_status(
                InvalidStatusCode(500, Headers())
            )
        )
        self.assertIsNone(stt_keyterms._websocket_rejection_status(OSError("dns")))

    async def test_r2_six_network_failures_keep_hinglish_settings(self) -> None:
        attempts, retry_sleep, _warning, info = await self._run_fallback_scenario(
            [OSError("network blip")] * 6 + [None]
        )
        self.assertEqual(
            [(host, kwargs["language"], "keyterm" in kwargs) for host, kwargs in attempts],
            [("eu", "multi", True)] * 7,
        )
        self.assertEqual(
            [call.args[0] for call in retry_sleep.await_args_list],
            [0.5, 1.0, 2.0, 2.0, 2.0, 2.0],
        )
        self.assertFalse(
            any(
                str(call.args[0]).startswith("stt fallback:")
                for call in info.call_args_list
            )
        )

    async def test_r2_one_400_advances_exactly_to_global_with_keyterms(self) -> None:
        attempts, _sleep, _warning, info = await self._run_fallback_scenario(
            [InvalidStatusCode(400, Headers()), None]
        )
        self.assertEqual(
            [(host, kwargs["language"], "keyterm" in kwargs) for host, kwargs in attempts],
            [("eu", "multi", True), ("global", "multi", True)],
        )
        fallback_lines = [
            str(call.args[0])
            for call in info.call_args_list
            if str(call.args[0]).startswith("stt fallback:")
        ]
        self.assertEqual(
            fallback_lines,
            ["stt fallback: step=global_host http_status=400"],
        )

    async def test_r2_400_then_network_blips_do_not_skip_steps(self) -> None:
        attempts, retry_sleep, _warning, info = await self._run_fallback_scenario(
            [InvalidStatusCode(400, Headers())] + [OSError("blip")] * 6 + [None]
        )
        self.assertEqual(
            [(host, kwargs["language"], "keyterm" in kwargs) for host, kwargs in attempts],
            [("eu", "multi", True)] + [("global", "multi", True)] * 7,
        )
        self.assertEqual(retry_sleep.await_count, 6)
        self.assertEqual(
            sum(
                str(call.args[0]).startswith("stt fallback:")
                for call in info.call_args_list
            ),
            1,
        )

    async def test_r2_fallback_order_uses_only_real_400_rejections(self) -> None:
        attempts, retry_sleep, warning, info = await self._run_fallback_scenario(
            [InvalidStatusCode(400, Headers())] * 3 + [None]
        )
        self.assertEqual(
            [(host, kwargs["language"], "keyterm" in kwargs) for host, kwargs in attempts],
            [
                ("eu", "multi", True),
                ("global", "multi", True),
                ("global", "multi", False),
                ("eu", "en-IN", True),
            ],
        )
        retry_sleep.assert_not_awaited()
        fallback_lines = [
            str(call.args[0])
            for call in info.call_args_list
            if str(call.args[0]).startswith("stt fallback:")
        ]
        self.assertEqual(
            fallback_lines,
            [
                "stt fallback: step=global_host http_status=400",
                "stt fallback: step=without_keyterms http_status=400",
                "stt fallback: step=english http_status=400",
            ],
        )
        warning_lines = "\n".join(str(call.args[0]) for call in warning.call_args_list)
        self.assertNotIn("private", warning_lines)

    async def test_r2_loop_survives_twenty_consecutive_failures(self) -> None:
        attempts, retry_sleep, _warning, _info = await self._run_fallback_scenario(
            [ConnectionResetError("reset")] * 20 + [None]
        )
        self.assertEqual(len(attempts), 21)
        self.assertEqual(retry_sleep.await_count, 20)
        self.assertTrue(
            all(
                host == "eu" and kwargs["language"] == "multi" and "keyterm" in kwargs
                for host, kwargs in attempts
            )
        )

    async def test_r1_f1_english_uses_pipecat_connection_handler_unchanged(self) -> None:
        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            settings=DeepgramSTTSettings(language="en-IN"),
            hinglish=False,
        )
        with patch.object(
            DeepgramSTTService, "_connection_handler", new=AsyncMock()
        ) as parent:
            await service._connection_handler()
        parent.assert_awaited_once_with()

    async def test_k09_real_scrub_sink_never_emits_phone_name_or_street(self) -> None:
        cases = {
            "Rahul Verma lives at 12 MG Road and uses 9876543210": (
                "Rahul",
                "Verma",
                "MG Road",
                "9876543210",
            ),
            "Meridian Rahul Verma": ("Rahul", "Verma"),
            "98 76 54 32 10 rupees": ("98", "76", "54", "32", "10"),
            "my number is 98765 43210 lakh": ("98765", "43210"),
        }
        for transcript, private_values in cases.items():
            with self.subTest(transcript=transcript):
                output = io.StringIO()
                log_scrub.configure_logging("INFO", stream=output)
                try:
                    service = stt_keyterms.STTCheckingDeepgramService(
                        api_key="test",
                        conn_id="abcdef",
                        region="global",
                        project_name="Meridian Heights",
                    )
                    frame = TranscriptionFrame(transcript, "u", "now")
                    with patch.object(
                        DeepgramSTTService, "push_frame", new=AsyncMock()
                    ):
                        await service.push_frame(frame)
                finally:
                    log_scrub.configure_logging("DEBUG")
                logged = output.getvalue()
                self.assertIn("stt check:", logged)
                check_payload = logged.split("stt check:", 1)[1]
                for private in private_values:
                    self.assertNotIn(private, check_payload)

    async def test_r1_05_check_failure_never_blocks_frame_forwarding(self) -> None:
        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            conn_id="abcdef",
            region="global",
            project_name=123,
        )
        frame = TranscriptionFrame("hello", "u", "now")
        with patch.object(
            stt_keyterms,
            "summarize_transcript",
            side_effect=TypeError("private transcript detail"),
        ), patch.object(
            DeepgramSTTService, "push_frame", new=AsyncMock()
        ) as push, patch.object(stt_keyterms.logger, "warning") as warning:
            await service.push_frame(frame)
        push.assert_awaited_once_with(frame, FrameDirection.DOWNSTREAM)
        warning.assert_called_once()
        rendered = str(warning.call_args.args[0])
        self.assertIn("TypeError", rendered)
        self.assertNotIn("private transcript detail", rendered)

    async def test_k10_missing_connection_id_logs_dash(self) -> None:
        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="test",
            conn_id=None,
            region="global",
            project_name="Meridian Heights",
        )
        frame = TranscriptionFrame("hello", "u", "now")
        with patch.object(DeepgramSTTService, "push_frame", new=AsyncMock()), patch.object(
            stt_keyterms.logger, "info"
        ) as info:
            await service.push_frame(frame)
        self.assertIn("conn=-", str(info.call_args.args[0]))
        self.assertIn("final=1", str(info.call_args.args[0]))


class RealSdkFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def _run_real_sdk_scenario(
        self,
        eu_rule,
        global_rule,
        *,
        attempt_limit: int = 12,
        eu_starts_closed: bool = False,
    ) -> dict:
        eu = LocalUpgradeServer("eu", eu_rule)
        global_server = LocalUpgradeServer("global", global_rule)
        await global_server.start()
        if eu_starts_closed:
            eu.port = reserve_local_port()
        else:
            await eu.start()

        service = stt_keyterms.STTCheckingDeepgramService(
            api_key="local-test-key",
            sample_rate=8000,
            settings=DeepgramSTTSettings(
                model="nova-3",
                language="multi",
                smart_format=True,
                interim_results=True,
                endpointing=300,
                keyterm=["local project term"],
            ),
            conn_id="abcdef",
            region="eu",
            project_name="Local Project",
            hinglish=True,
            base_url=f"http://127.0.0.1:{eu.port}",
        )
        service._sample_rate = 8000

        async def cancel_task(task) -> None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        retry_delays: list[float] = []

        async def retry_sleep(delay: float) -> None:
            retry_delays.append(delay)
            if eu_starts_closed and eu.server is None:
                await eu.start(eu.port)
            await asyncio.sleep(0)

        service.create_task = lambda coro, *_args: asyncio.create_task(coro)
        service.cancel_task = cancel_task
        warning_lines: list[str] = []
        info_lines: list[str] = []
        task = None
        try:
            with patch.object(
                stt_keyterms,
                "AsyncDeepgramClient",
                side_effect=lambda **_kwargs: local_deepgram_client(global_server.port),
            ), patch.object(
                stt_keyterms, "sleep", side_effect=retry_sleep
            ), patch.object(
                stt_keyterms.logger,
                "warning",
                side_effect=lambda message, *_args, **_kwargs: warning_lines.append(
                    str(message)
                ),
            ), patch.object(
                stt_keyterms.logger,
                "info",
                side_effect=lambda message, *_args, **_kwargs: info_lines.append(
                    str(message)
                ),
            ):
                task = asyncio.create_task(service._connection_handler())
                for _ in range(400):
                    total_attempts = len(eu.attempts) + len(global_server.attempts)
                    if service._connection_ready.is_set() or total_attempts >= attempt_limit:
                        break
                    if task.done():
                        break
                    await asyncio.sleep(0.005)

                connected = service._connection_ready.is_set()
                task_alive = not task.done()
                result = {
                    "connected": connected,
                    "task_alive": task_alive,
                    "eu": list(eu.attempts),
                    "global": list(global_server.attempts),
                    "region": service._nxlyr_region,
                    "language": service._build_connect_kwargs().get("language"),
                    "keyterms": "keyterm" in service._build_connect_kwargs(),
                    "fallbacks": [
                        line for line in info_lines if line.startswith("stt fallback:")
                    ],
                    "warnings": list(warning_lines),
                    "retry_delays": retry_delays,
                }
        finally:
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await eu.stop()
            await global_server.stop()

        logged = "\n".join([*result["fallbacks"], *result["warnings"]])
        self.assertNotIn("local-test-key", logged)
        self.assertNotIn("Authorization", logged)
        self.assertNotIn("Token ", logged)
        return result

    async def test_r3_scenario_a_eu_400_moves_to_global_with_keyterms(self) -> None:
        result = await self._run_real_sdk_scenario(
            lambda _n, _attempt: 400,
            lambda _n, _attempt: None,
        )
        self.assertTrue(result["connected"])
        self.assertEqual(result["region"], "global")
        self.assertEqual(result["language"], "multi")
        self.assertTrue(result["keyterms"])
        self.assertEqual(
            result["fallbacks"],
            ["stt fallback: step=global_host http_status=400"],
        )
        self.assertTrue(all("ApiError" in line for line in result["warnings"]))

    async def test_r3_scenario_b_second_400_drops_keyterms_on_global(self) -> None:
        result = await self._run_real_sdk_scenario(
            lambda _n, _attempt: 400,
            lambda _n, attempt: 400 if attempt[2] else None,
        )
        self.assertTrue(result["connected"])
        self.assertEqual((result["region"], result["language"], result["keyterms"]), ("global", "multi", False))
        self.assertEqual(
            result["fallbacks"],
            [
                "stt fallback: step=global_host http_status=400",
                "stt fallback: step=without_keyterms http_status=400",
            ],
        )

    async def test_r3_scenario_c_multi_400_reaches_english_settings(self) -> None:
        reject_multi = lambda _n, attempt: 400 if attempt[1] == "multi" else None
        result = await self._run_real_sdk_scenario(reject_multi, reject_multi)
        self.assertTrue(result["connected"])
        self.assertEqual((result["region"], result["language"], result["keyterms"]), ("eu", "en-IN", True))
        self.assertEqual(
            result["fallbacks"],
            [
                "stt fallback: step=global_host http_status=400",
                "stt fallback: step=without_keyterms http_status=400",
                "stt fallback: step=english http_status=400",
            ],
        )

    async def test_r3_scenario_d_six_503_blips_keep_initial_settings(self) -> None:
        result = await self._run_real_sdk_scenario(
            lambda number, _attempt: 503 if number <= 6 else None,
            lambda _n, _attempt: None,
        )
        self.assertTrue(result["connected"])
        self.assertEqual(len(result["eu"]), 7)
        self.assertEqual((result["region"], result["language"], result["keyterms"]), ("eu", "multi", True))
        self.assertEqual(result["fallbacks"], [])

    async def test_r3_scenario_e_closed_port_recovers_without_fallback(self) -> None:
        result = await self._run_real_sdk_scenario(
            lambda _n, _attempt: None,
            lambda _n, _attempt: None,
            eu_starts_closed=True,
        )
        self.assertTrue(result["connected"])
        self.assertEqual((result["region"], result["language"], result["keyterms"]), ("eu", "multi", True))
        self.assertEqual(result["fallbacks"], [])
        self.assertTrue(
            any("ConnectionRefusedError" in line for line in result["warnings"])
        )

    async def test_r3_scenario_f_400_then_six_503_blips_takes_one_step(self) -> None:
        result = await self._run_real_sdk_scenario(
            lambda _n, _attempt: 400,
            lambda number, _attempt: 503 if number <= 6 else None,
        )
        self.assertTrue(result["connected"])
        self.assertEqual((result["region"], result["language"], result["keyterms"]), ("global", "multi", True))
        self.assertEqual(
            result["fallbacks"],
            ["stt fallback: step=global_host http_status=400"],
        )

    async def test_r3_scenario_g_all_400_keeps_loop_alive_after_three_steps(self) -> None:
        result = await self._run_real_sdk_scenario(
            lambda _n, _attempt: 400,
            lambda _n, _attempt: 400,
            attempt_limit=7,
        )
        self.assertFalse(result["connected"])
        self.assertTrue(result["task_alive"])
        self.assertEqual((result["region"], result["language"], result["keyterms"]), ("eu", "en-IN", True))
        self.assertEqual(
            result["fallbacks"],
            [
                "stt fallback: step=global_host http_status=400",
                "stt fallback: step=without_keyterms http_status=400",
                "stt fallback: step=english http_status=400",
            ],
        )

    async def test_r3_401_403_and_429_never_advance_a_step(self) -> None:
        for status in (401, 403, 429):
            with self.subTest(status=status):
                result = await self._run_real_sdk_scenario(
                    lambda number, _attempt, status=status: status if number == 1 else None,
                    lambda _n, _attempt: None,
                )
                self.assertTrue(result["connected"])
                self.assertEqual((result["region"], result["language"], result["keyterms"]), ("eu", "multi", True))
                self.assertEqual(result["fallbacks"], [])


if __name__ == "__main__":
    unittest.main()
