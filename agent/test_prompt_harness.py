import asyncio
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

with patch("dotenv.load_dotenv"):
    import prompt_harness


class FakeCompletions:
    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = iter(replies or ["Okay."] * 100)
        self.histories: list[list[dict]] = []

    async def create(self, **kwargs):
        self.histories.append([dict(message) for message in kwargs["messages"]])
        message = SimpleNamespace(content=next(self.replies), tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")]
        )


class FakeClient:
    def __init__(self, replies: list[str] | None = None) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(replies))


class PromptHarnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = FakeClient()

    async def test_h01_script_splits_ignores_comments_and_feeds_seeded_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "script.txt"
            script.write_text(
                "# heading\nhello # inline note\nsecond line\n---\n# next\ngoodbye\n"
            )
            args = prompt_harness.build_arg_parser().parse_args(
                ["--script", str(script), "--no-timing", "--prompt-version", "v21"]
            )
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), patch.object(
                prompt_harness, "make_redis_client", new=AsyncMock(return_value=None)
            ):
                await prompt_harness.run_harness(
                    args, client=self.client, output_stream=output
                )
        user_lines = [
            history[-1]["content"] for history in self.client.chat.completions.histories
        ]
        self.assertEqual(user_lines, ["hello", "second line", "goodbye"])
        first_histories = (
            self.client.chat.completions.histories[0],
            self.client.chat.completions.histories[2],
        )
        for history in first_histories:
            self.assertEqual([item["role"] for item in history[:2]], ["system", "assistant"])
            self.assertIn("[HOW THE CALL GOES]", history[0]["content"])

    async def test_h02_runs_three_passes_and_prompt_version_selects_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "script.txt"
            script.write_text("hello\n---\nbye\n")
            args = prompt_harness.build_arg_parser().parse_args(
                [
                    "--script",
                    str(script),
                    "--runs",
                    "3",
                    "--prompt-version",
                    "v2",
                    "--no-timing",
                ]
            )
            with patch.dict(os.environ, {}, clear=True), patch.object(
                prompt_harness, "make_redis_client", new=AsyncMock(return_value=None)
            ):
                await prompt_harness.run_harness(
                    args, client=self.client, output_stream=io.StringIO()
                )
        self.assertEqual(len(self.client.chat.completions.histories), 6)
        for history in self.client.chat.completions.histories:
            self.assertNotIn("[HOW THE CALL GOES]", history[0]["content"])

    async def test_h03_all_reply_flags_match_the_approved_examples(self) -> None:
        flag = prompt_harness.reply_flags
        self.assertTrue(flag("my name is Aarya", "hello", 2)["reintro"])
        self.assertFalse(flag("my name is Aarya", "who is this?", 2)["reintro"])
        self.assertFalse(flag("Hi, yes, I'm here.", "Hi Aarya", 2)["reintro"])
        self.assertTrue(flag("Great, it starts there.", "price?", 1)["banned"])
        self.assertTrue(flag("Right.", "price?", 1)["banned"])
        self.assertFalse(flag("Right, so it starts there.", "price?", 1)["banned"])
        self.assertTrue(flag("Did you mean Meridian Heights?", "project?", 1)["didyoumean"])
        self.assertTrue(flag("Rs 12 thousand", "price?", 1)["digits"])
        self.assertTrue(flag("[warm] Hi", "hello", 1)["tag_in_reply"])
        self.assertTrue(flag("Which size? What budget?", "hello", 1)["two_questions"])
        self.assertTrue(flag(" ".join(["word"] * 46), "hello", 1)["over45"])
        for claim in (
            "The visit is booked.",
            "I've put you down.",
            "You're down for Saturday.",
            "It is confirmed.",
            "I've noted that.",
            "The question was passed on.",
            "I've passed that on.",
            "I have passed it on.",
            "I\u2019ve noted that.",
        ):
            with self.subTest(claim=claim):
                self.assertTrue(flag(claim, "Saturday", 1)["claimed_without_tool"])
                self.assertFalse(
                    flag(claim, "Saturday", 1, function_called=True)[
                        "claimed_without_tool"
                    ]
                )
        for closer in (
            "Would you like to know more?",
            "Anything else you'd like to know?",
            "Is there anything else?",
            "How can I help you?",
            "What would you like to know?",
            "HOW CAN I ASSIST YOU!",
            "How can I assist you today?",
            "Anything else you\u2019d like to know?",
        ):
            with self.subTest(closer=closer):
                self.assertTrue(
                    flag(f"The price starts there. {closer}", "price?", 1)[
                        "generic_closer"
                    ]
                )
        for timing_word in ("shortly", "soon", "right away", "today"):
            with self.subTest(timing_word=timing_word):
                self.assertTrue(
                    flag(f"A colleague will call {timing_word}.", "hello", 1)[
                        "timing_word"
                    ]
                )
        clean = flag(
            "So, it starts at two point two crore. That is for the three bedroom.",
            "price?",
            1,
        )
        self.assertFalse(any(clean[name] for name in prompt_harness.BOOLEAN_FLAGS))

    async def test_h04_text_beside_tool_call_is_printed_before_the_tool(self) -> None:
        tool_call = SimpleNamespace(
            id="tool-1",
            function=SimpleNamespace(name="transfer_to_human", arguments="{}"),
        )
        messages = [
            prompt_harness.ReplyResult(
                SimpleNamespace(content="One second.", tool_calls=[tool_call]), 2, 4
            ),
            prompt_harness.ReplyResult(
                SimpleNamespace(content="A colleague will follow up.", tool_calls=None),
                5,
                6,
            ),
        ]
        output = io.StringIO()
        with patch.object(
            prompt_harness, "get_reply", new=AsyncMock(side_effect=messages)
        ), patch.object(
            prompt_harness, "run_tool_call", new=AsyncMock(return_value=None)
        ):
            ended = await prompt_harness.handle_turn(
                self.client,
                [{"role": "user", "content": "can I talk to someone?"}],
                SimpleNamespace(),
                output=prompt_harness.HarnessOutput(output),
                timing=False,
                caller_line="can I talk to someone?",
                stats=prompt_harness.HarnessStats(),
                run_id=1,
                reply_index=1,
            )
        self.assertFalse(ended)
        self.assertIn("Bot (before tool): One second.", output.getvalue())

    async def test_h04_claim_beside_tool_is_not_flagged_without_tool(self) -> None:
        tool_call = SimpleNamespace(
            id="tool-1",
            function=SimpleNamespace(name="book_site_visit", arguments="{}"),
        )
        messages = [
            prompt_harness.ReplyResult(
                SimpleNamespace(content="You're booked.", tool_calls=[tool_call]), 2, 4
            ),
            prompt_harness.ReplyResult(
                SimpleNamespace(content="Saturday works.", tool_calls=None), 2, 3
            ),
        ]
        output = io.StringIO()
        stats = prompt_harness.HarnessStats()
        with patch.object(
            prompt_harness, "get_reply", new=AsyncMock(side_effect=messages)
        ), patch.object(
            prompt_harness, "run_tool_call", new=AsyncMock(return_value=None)
        ):
            await prompt_harness.handle_turn(
                self.client,
                [{"role": "user", "content": "Saturday"}],
                SimpleNamespace(),
                output=prompt_harness.HarnessOutput(output),
                timing=False,
                caller_line="Saturday",
                stats=stats,
                run_id=1,
                reply_index=1,
            )
        self.assertEqual(stats.flag_counts["claimed_without_tool"], 0)

    async def test_h05_summary_counts_repeats_connectives_process_phrases_and_questions(self) -> None:
        stats = prompt_harness.HarnessStats()
        replies = (
            "So, let me check. One second.",
            "So, let me check. Would Saturday work?",
            "Right, so it starts there. Let me note that down.",
            "The visit is booked. A colleague will call soon. How can I assist you?",
        )
        for index, text in enumerate(replies, 1):
            stats.add(text, prompt_harness.reply_flags(text, "caller", index), run_id=1)
        summary = stats.render_summary()
        self.assertIn("replies=4", summary)
        self.assertIn("repeated_sentences=1", summary)
        self.assertIn("connectives=3", summary)
        self.assertIn("process_phrases=4", summary)
        self.assertIn("ending_in_question=2/4", summary)
        for flag_name in ("claimed_without_tool", "generic_closer", "timing_word"):
            self.assertIn(f"{flag_name}=1", summary)

    async def test_h06_default_and_live_kb_paths_and_checked_in_file(self) -> None:
        with patch.object(prompt_harness, "load_project_kb") as live:
            default = prompt_harness.load_harness_kb(None)
        live.assert_not_called()
        expected_keys = {
            "pricing",
            "location",
            "overview",
            "amenities",
            "developer",
            "fictional",
            "objections",
            "unit_types",
            "payment_plan",
            "project_name",
        }
        self.assertEqual(set(default), expected_keys)
        for key in ("pricing", "overview", "amenities", "payment_plan"):
            self.assertIn("spoken", default[key])
        self.assertTrue(all("spoken" in unit for unit in default["unit_types"]))
        self.assertNotIn("competitors", default)
        kb_path = AGENT_DIR / "prompt_scripts" / "kb_meridian_heights.json"
        self.assertEqual(
            hashlib.sha256(kb_path.read_bytes()).hexdigest(),
            "3ef75fff6e93b60d9323ca02b2fb44e007018018502af294492f4266a2ffeb92",
        )
        with patch.object(
            prompt_harness, "load_project_kb", return_value={"project_name": "Live"}
        ) as live:
            self.assertEqual(prompt_harness.load_harness_kb("live"), {"project_name": "Live"})
        live.assert_called_once_with()

    async def test_h07_fake_client_needs_no_key_and_stdout_and_out_never_contain_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "script.txt"
            out = Path(directory) / "transcript.txt"
            script.write_text("hello\n")
            args = prompt_harness.build_arg_parser().parse_args(
                ["--script", str(script), "--out", str(out), "--no-timing"]
            )
            stdout = io.StringIO()
            fake_key = "sk-fake-secret-value-that-must-not-appear"
            with patch.dict(os.environ, {"OPENAI_API_KEY": fake_key}, clear=True), patch.object(
                prompt_harness, "make_redis_client", new=AsyncMock(return_value=None)
            ):
                await prompt_harness.run_harness(
                    args, client=self.client, output_stream=stdout
                )
            self.assertNotIn(fake_key, stdout.getvalue())
            self.assertNotIn(fake_key, out.read_text())

    async def test_h08_partial_greeting_seeds_exactly_six_words(self) -> None:
        kb = {"project_name": "Meridian Heights"}
        full = prompt_harness.seed_history(kb, "v21", partial_greeting=False)
        partial = prompt_harness.seed_history(kb, "v21", partial_greeting=True)
        self.assertEqual(len(partial[-1]["content"].split()), 6)
        self.assertEqual(
            partial[-1]["content"], " ".join(full[-1]["content"].split()[:6])
        )

    async def test_l11_hinglish_flags_have_true_and_false_cases(self) -> None:
        flag = prompt_harness.reply_flags

        for text in ("मैं बता सकता हूँ।", "मैं कर रहा हूँ।", "मैं करूँगा।", "मैं समझ गया।"):
            with self.subTest(flag="masc_verb", text=text):
                self.assertTrue(
                    flag(text, "बताइए", 1, language_mode="hinglish")["masc_verb"]
                )
        for text in ("मैं बता सकती हूँ।", "मैं कर रही हूँ।", "मैं करूँगी।", "मैं समझ गई।"):
            with self.subTest(flag="masc_verb_clean", text=text):
                self.assertFalse(
                    flag(text, "मैं देख रहा हूँ", 1, language_mode="hinglish")["masc_verb"]
                )

        cases = (
            ("digits", "कीमत 2 crore है।", "कीमत two crore है।"),
            ("wrong_script", "price two crore hai।", "price two crore है।"),
            ("wrong_script", "साइट विज़िट available है।", "site visit available है।"),
            ("english_to_hindi", "The project is in Gurugram.", "यह project Gurugram में है।"),
            ("hindi_to_english", "यह project यहाँ है।", "The project is here."),
            ("no_final_punct", "यह project यहाँ है", "यह project यहाँ है।"),
            ("hindi_calendar", "शनिवार को आइए।", "Saturday को आइए।"),
            ("hindi_number", "दो BHK उपलब्ध हैं।", "three BHK उपलब्ध हैं।"),
        )
        callers = {
            "english_to_hindi": "मुझे बताइए",
            "hindi_to_english": "tell me about it",
        }
        for name, bad, good in cases:
            caller = callers.get(name, "मुझे बताइए")
            with self.subTest(flag=name, result=True):
                self.assertTrue(
                    flag(bad, caller, 1, language_mode="hinglish")[name]
                )
            with self.subTest(flag=name, result=False):
                self.assertFalse(
                    flag(good, caller, 1, language_mode="hinglish")[name]
                )

        kb_text = json.dumps(prompt_harness.load_harness_kb(None), ensure_ascii=False)
        self.assertTrue(
            flag(
                "कीमत two point three crore rupees है।",
                "price?",
                1,
                language_mode="hinglish",
                kb_text=kb_text,
            )["figure_not_in_kb"]
        )
        self.assertFalse(
            flag(
                "कीमत two point two crore है।",
                "price?",
                1,
                language_mode="hinglish",
                kb_text=kb_text,
            )["figure_not_in_kb"]
        )
        self.assertTrue(
            flag(
                "यह वाक्य अधूरा है",
                "बताइए",
                1,
                language_mode="hinglish",
                finish_reason="length",
            )["truncated"]
        )
        self.assertFalse(
            flag(
                "यह वाक्य पूरा है।",
                "बताइए",
                1,
                language_mode="hinglish",
                finish_reason="stop",
            )["truncated"]
        )

    async def test_r1_f3_figure_runs_stop_at_hindi_and_punctuation(self) -> None:
        kb = prompt_harness.load_harness_kb(None)
        kb_text = json.dumps(kb, ensure_ascii=False)
        cases = (
            "तीन BHK में कीमत two point two crore rupees से शुरू होती है।",
            "Starts at two point two crore rupees, three BHK available.",
            "three BHK में two point two crore rupees मिलते हैं।",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(prompt_harness._figure_not_in_kb(text, kb_text))
        self.assertTrue(
            prompt_harness._figure_not_in_kb(
                "कीमत two point five crore rupees है।", kb_text
            )
        )

    async def test_r1_f3_every_harness_spoken_sentence_matches_its_kb(self) -> None:
        kb = prompt_harness.load_harness_kb(None)
        kb_text = json.dumps(kb, ensure_ascii=False)
        spoken = [
            value["spoken"]
            for value in kb.values()
            if isinstance(value, dict) and "spoken" in value
        ]
        spoken.extend(
            unit["spoken"] for unit in kb["unit_types"] if "spoken" in unit
        )
        self.assertEqual(len(spoken), 6)
        for sentence in spoken:
            with self.subTest(sentence=sentence):
                self.assertFalse(
                    prompt_harness._figure_not_in_kb(sentence, kb_text)
                )

    async def test_r1_minor_nfd_normalises_both_sides_of_devanagari_matches(self) -> None:
        flag = prompt_harness.reply_flags
        for spelling in ("फ़रवरी", "\u095eरवरी"):
            with self.subTest(calendar=spelling):
                self.assertTrue(
                    flag(
                        f"{spelling} में आइए।",
                        "बताइए",
                        1,
                        language_mode="hinglish",
                    )["hindi_calendar"]
                )
        for spelling in ("हज़ार", "ह\u095bार", "करोड़", "करो\u095c"):
            with self.subTest(number=spelling):
                self.assertTrue(
                    flag(
                        f"कीमत {spelling} rupees है।",
                        "बताइए",
                        1,
                        language_mode="hinglish",
                    )["hindi_number"]
                )

    async def test_r2_missing_hindi_number_spellings_are_flagged(self) -> None:
        for spelling in ("चौवालीस", "उन्यासी", "सत्तासी"):
            with self.subTest(spelling=spelling):
                self.assertTrue(
                    prompt_harness.reply_flags(
                        f"{spelling} lakh rupees।",
                        "बताइए",
                        1,
                        language_mode="hinglish",
                    )["hindi_number"]
                )

    async def test_l11_claim_patterns_cover_english_and_hindi_without_substrings(self) -> None:
        flag = prompt_harness.reply_flags
        for claim in (
            "Your visit is set for Thursday.",
            "Your visit is fixed for Thursday.",
            "Your visit is scheduled for Thursday.",
            "आपकी visit बुक कर दी।",
            "आपकी visit सेट कर दी।",
            "आपकी visit बुक हो गई है।",
            "आपकी visit सेट कर दिया।",
            "आपकी request आगे बढ़ा दी।",
            "आपका समय नोट हो गया।",
        ):
            with self.subTest(claim=claim):
                self.assertTrue(flag(claim, "Thursday", 1)["claimed_without_tool"])
                self.assertFalse(
                    flag(claim, "Thursday", 1, function_called=True)[
                        "claimed_without_tool"
                    ]
                )
        for clean in (
            "Please reset for Thursday.",
            "That schedule is for Thursday.",
            "Thursday could work.",
            "आप बुक कर दीजिए।",
            "मैं पक्का करना चाहूँगी।",
            "क्या आप कन्फ़र्म करना चाहेंगे?",
        ):
            with self.subTest(clean=clean):
                self.assertFalse(flag(clean, "Thursday", 1)["claimed_without_tool"])

    async def test_l11_hindi_timing_and_generic_closer_are_flagged(self) -> None:
        flags = prompt_harness.reply_flags(
            "मैं अभी तुरंत बताती हूँ। और कुछ जानना चाहेंगे?",
            "बताइए",
            1,
            language_mode="hinglish",
        )
        self.assertTrue(flags["timing_word"])
        self.assertTrue(flags["generic_closer"])

    async def test_l11_stream_finish_reason_length_is_recorded(self) -> None:
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="अधूरा जवाब", tool_calls=[]),
                        finish_reason=None,
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None, tool_calls=[]),
                        finish_reason="length",
                    )
                ]
            ),
        ]

        class FakeStream:
            def __aiter__(self):
                self.items = iter(chunks)
                return self

            async def __anext__(self):
                try:
                    return next(self.items)
                except StopIteration as error:
                    raise StopAsyncIteration from error

        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=FakeStream())
                )
            )
        )
        result = await prompt_harness.get_reply(
            client,
            [{"role": "user", "content": "बताइए"}],
            timing=True,
        )
        self.assertEqual(result.finish_reason, "length")
        self.assertEqual(result.message.content, "अधूरा जवाब")

    async def test_l12_english_summary_stays_byte_identical_and_devanagari_counts_spaces(self) -> None:
        stats = prompt_harness.HarnessStats()
        text = "The project is in Gurugram."
        stats.add(text, prompt_harness.reply_flags(text, "where?", 1), run_id=1)
        self.assertEqual(
            stats.render_summary(),
            "[summary]\n"
            "replies=1 p50_first_sentence_words=5 p50_first_sentence_ms=0\n"
            "reintro=0 banned=0 didyoumean=0 digits=0 tag_in_reply=0 two_questions=0 over45=0 claimed_without_tool=0 generic_closer=0 timing_word=0\n"
            "replies_with_two_questions=0 repeated_sentences=0 replies_over_45=0\n"
            "connective_share=0.000 connectives=0 connective_counts={} process_phrases=0\n"
            "ending_in_question=0/1",
        )
        flags = prompt_harness.reply_flags(
            "जी, यह project यहाँ उपलब्ध है।",
            "बताइए",
            1,
            language_mode="hinglish",
        )
        self.assertEqual(flags["first_sentence_words"], 6)

        hinglish_stats = prompt_harness.HarnessStats(language_mode="hinglish")
        hinglish_stats.add(
            "यह उत्तर पूरा है।",
            prompt_harness.reply_flags(
                "यह उत्तर पूरा है।",
                "बताइए",
                1,
                language_mode="hinglish",
            ),
            run_id=1,
        )
        self.assertRegex(
            hinglish_stats.render_summary().splitlines()[-1],
            r"^masc_verb=0 digits=0 .* truncated=0$",
        )

        script = AGENT_DIR / "prompt_scripts" / "hinglish_v21.txt"
        scenarios = prompt_harness.parse_script(script)
        self.assertEqual(len(scenarios), 8)
        self.assertTrue(all(scenarios))

    async def test_l12_hinglish_seed_adds_language_block_but_keeps_greeting(self) -> None:
        kb = {"project_name": "Meridian Heights"}
        english = prompt_harness.seed_history(
            kb,
            "v21",
            partial_greeting=False,
            language_mode="en",
        )
        hinglish = prompt_harness.seed_history(
            kb,
            "v21",
            partial_greeting=False,
            language_mode="hinglish",
        )
        self.assertNotIn("[LANGUAGE]", english[0]["content"])
        self.assertTrue(hinglish[0]["content"].endswith(prompt_harness.HINGLISH_ADDENDUM))
        self.assertEqual(english[-1], hinglish[-1])


if __name__ == "__main__":
    unittest.main()
