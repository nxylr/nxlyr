import io
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import deepgram
from deepgram.core.query_encoder import encode_query
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings

import log_scrub
import stt_keyterms


REAL_SHAPE_KB = {
    "project_name": "Meridian Heights",
    "developer": "Aetheria Realty Group",
    "location": {
        "city": "Gurugram",
        "sector": "Sector 79B",
        "landmark": "Near Southern Peripheral Road (SPR) & NH-8 Junction",
    },
}


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


if __name__ == "__main__":
    unittest.main()
