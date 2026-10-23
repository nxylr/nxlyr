import asyncio
import importlib
import inspect
import json
import os
import re
import sys
import unittest
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch


AGENT_DIRECTORY = str(Path(__file__).parent)
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)

import prompt
import tools
from pipecat.services.llm_service import FunctionCallParams


FIXED_KB = {
    "project_name": "Test Heights",
    "developer": "Test Developer",
    "payment_plan": {
        "name": "Construction Linked Plan",
        "spoken": "A quarter at booking.",
    },
}
FIXED_TODAY = date(2026, 10, 23)
SECTION_HEADERS = {
    "CORE RULES",
    "REAL ESTATE PACK",
    "COMPANY",
    "CURRENT DATE",
    "PROJECT KNOWLEDGE BASE",
    "HOW IT SOUNDS",
}


def build_prompt(**kwargs: Any) -> str:
    return prompt.build_system_prompt(
        project_kb=FIXED_KB,
        today=FIXED_TODAY,
        **kwargs,
    )


def greetings() -> list[str]:
    return [
        prompt.build_greeting(prompt.LEAD_SOURCE_DEMO_FORM, "Test Heights"),
        prompt.build_greeting(prompt.LEAD_SOURCE_LEAD, "Test Heights"),
        prompt.build_greeting(prompt.LEAD_SOURCE_LEAD),
    ]


def you_lines(system_prompt: str) -> list[str]:
    sounds = system_prompt.split("[HOW IT SOUNDS]\n", 1)[1]
    return [line.removeprefix("You: ") for line in sounds.splitlines() if line.startswith("You: ")]


def import_bot() -> ModuleType:
    sys.modules.pop("bot", None)
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("dotenv.load_dotenv"),
    ):
        return importlib.import_module("bot")


class PromptV2Tests(unittest.TestCase):
    def test_p01_three_blocks(self) -> None:
        headers = ["[CORE RULES]", "[REAL ESTATE PACK]", "[COMPANY]"]

        for disclosure_mode in ("on_ask", "upfront"):
            with patch.object(prompt, "AI_DISCLOSURE_MODE", disclosure_mode):
                for lead_source in (
                    prompt.LEAD_SOURCE_DEMO_FORM,
                    prompt.LEAD_SOURCE_LEAD,
                ):
                    with self.subTest(
                        disclosure_mode=disclosure_mode,
                        lead_source=lead_source,
                    ):
                        system_prompt = build_prompt(
                            lead_source=lead_source,
                            lead_project_name="Test Heights",
                        )
                        self.assertTrue(
                            all(system_prompt.count(header) == 1 for header in headers)
                        )
                        self.assertLess(
                            system_prompt.index(headers[0]),
                            system_prompt.index(headers[1]),
                        )
                        self.assertLess(
                            system_prompt.index(headers[1]),
                            system_prompt.index(headers[2]),
                        )
                        current_date_header = system_prompt.index("\n[CURRENT DATE]\n")
                        self.assertLess(
                            system_prompt.index(headers[2]), current_date_header
                        )
                        for removed in (
                            "[ROLE]",
                            "[PERSONA CONTEXT]",
                            "[CONVERSATION EXAMPLES]",
                        ):
                            self.assertNotIn(removed, system_prompt)

    def test_p02_banned_phrases(self) -> None:
        expected_openers = (
            "Great",
            "I see",
            "Sure thing",
            "Absolutely",
            "Sure",
            "I hear you",
            "Fair question",
            "I appreciate you sharing",
            "Got it",
            "Right",
        )
        self.assertEqual(prompt.BANNED_OPENERS, expected_openers)

        for disclosure_mode in ("on_ask", "upfront"):
            with patch.object(prompt, "AI_DISCLOSURE_MODE", disclosure_mode):
                spoken_strings = greetings() + [prompt.CLOSING_PHRASE]
                for lead_source in (
                    prompt.LEAD_SOURCE_DEMO_FORM,
                    prompt.LEAD_SOURCE_LEAD,
                ):
                    system_prompt = re.sub(
                        r"^- Start with the answer itself, not a reaction\. Never open a reply with:.*$",
                        "",
                        build_prompt(
                            lead_source=lead_source,
                            lead_project_name="Test Heights",
                        ),
                        flags=re.MULTILINE,
                    )
                    for phrase in expected_openers:
                        pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
                        self.assertIsNone(re.search(pattern, system_prompt))
                        for spoken in spoken_strings:
                            self.assertIsNone(re.search(pattern, spoken))

    def test_p03_samples(self) -> None:
        samples = you_lines(build_prompt())
        self.assertEqual(len(samples), 4)
        forbidden = list(prompt.BANNED_OPENERS) + [
            "Rs",
            "₹",
            "send",
            "WhatsApp",
            "brochure",
            "shortly",
            "soon",
        ]
        for sample in samples:
            self.assertIsNone(re.search(r"\d", sample))
            for phrase in forbidden:
                self.assertNotIn(phrase, sample)
        self.assertLessEqual(sum(sample.endswith("?") for sample in samples), 3)
        self.assertLessEqual(len(samples[2].split()), 5)

    def test_p04_disclosure(self) -> None:
        with patch.object(prompt, "AI_DISCLOSURE_MODE", "on_ask"):
            system_prompt = build_prompt()
            self.assertEqual(system_prompt.count("AI DISCLOSURE"), 1)
            for text in (
                "answer at once and truthfully",
                "Never deny it",
                "never claim to be human",
            ):
                self.assertIn(text, system_prompt)
            self.assertNotIn("Never reveal", system_prompt)
            self.assertNotIn("not an AI", system_prompt)
            disclosure_answer = "I'm an AI assistant calling for Next Layer."
            self.assertIn(f'"{disclosure_answer}"', system_prompt)
            self.assertNotIn(f'"Yes, {disclosure_answer}"', system_prompt)
            disclosure_paragraph = next(
                line
                for line in system_prompt.splitlines()
                if line.startswith("AI DISCLOSURE")
            )
            for caller_question in (
                "are you a bot?",
                "are you a real person?",
                "is this a recording?",
            ):
                with self.subTest(caller_question=caller_question):
                    trigger = caller_question.removeprefix("are you ").removeprefix(
                        "is this "
                    ).removesuffix("?")
                    self.assertIn(trigger, disclosure_paragraph.lower())
                    self.assertTrue(disclosure_answer.startswith("I'm an AI assistant"))
            self.assertTrue(all("AI" not in greeting for greeting in greetings()))

        with patch.object(prompt, "AI_DISCLOSURE_MODE", "upfront"):
            system_prompt = build_prompt()
            self.assertEqual(system_prompt.count("AI DISCLOSURE"), 1)
            self.assertIn("Never deny it", system_prompt)
            self.assertIn(
                "You told the caller in your greeting that you are an AI assistant.",
                system_prompt,
            )
            self.assertTrue(all("AI assistant" in greeting for greeting in greetings()))

        with patch.object(prompt, "AI_DISCLOSURE_MODE", "invalid"):
            with self.assertRaises(ValueError):
                build_prompt()
            with self.assertRaises(ValueError):
                prompt.build_greeting(prompt.LEAD_SOURCE_DEMO_FORM)

    def test_p05_greeting_templates(self) -> None:
        demo = prompt.build_greeting(prompt.LEAD_SOURCE_DEMO_FORM, "Test Heights")
        for text in ("Aarya", "Next Layer", "demo call"):
            self.assertIn(text, demo)
        self.assertEqual(demo.count("Test Heights"), 1)
        self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", demo)), 3)

        lead = prompt.build_greeting(prompt.LEAD_SOURCE_LEAD, "Test Heights")
        self.assertEqual(lead.count("Test Heights"), 1)
        unnamed_lead = prompt.build_greeting(prompt.LEAD_SOURCE_LEAD)
        self.assertNotIn("Test Heights", unnamed_lead)
        self.assertIn("the enquiry you sent in", unnamed_lead)
        with self.assertRaises(ValueError):
            prompt.build_greeting("unknown")

    def test_p06_no_end_after_booking_text(self) -> None:
        booking_rule = (
            "A booking, a passed-on question or a finished answer is not the end."
        )
        system_prompt = build_prompt()
        self.assertIn(booking_rule, system_prompt)
        system_prompt = system_prompt.replace(booking_rule, "")
        for pattern in (
            r"(book|visit)[^.\n]{0,80}end_call",
            r"end_call[^.\n]{0,80}(book|visit)",
        ):
            self.assertIsNone(re.search(pattern, system_prompt, flags=re.IGNORECASE))
        for removed in (
            "naturally complete",
            "Do not wait for the caller to hang up",
            "clear next step",
        ):
            self.assertNotIn(removed, system_prompt)
        self.assertIn("latest message", system_prompt)
        self.assertIn(
            "Never call end_call in the same turn as another function",
            system_prompt,
        )
        self.assertIn("in the turn after a function result", system_prompt)
        self.assertIn("If unsure, stay on the line", system_prompt)

    def test_p07_tool_strings(self) -> None:
        end_description = tools.END_CALL_SCHEMA.description
        self.assertNotIn("clear outcome", end_description)
        for text in ("goodbye", "latest message", "same turn"):
            self.assertIn(text, end_description)
        self.assertIn("after a function result", end_description)
        self.assertIn("does not end the call", tools.BOOK_SITE_VISIT_SCHEMA.description)
        self.assertIn("description", tools.END_CALL_SCHEMA.properties["outcome"])
        self.assertEqual(
            tools.END_CALL_OUTCOMES,
            [
                "site_visit_booked",
                "qualified_interested",
                "follow_up_needed",
                "not_interested",
                "wrong_number",
            ],
        )

    def test_p08_booking_result(self) -> None:
        captured: dict[str, Any] = {}

        async def result_callback(
            result: dict[str, Any], *, properties: Any | None = None
        ) -> None:
            captured["result"] = result

        async def run() -> None:
            await tools.book_site_visit(
                FunctionCallParams(
                    function_name="book_site_visit",
                    tool_call_id="test-call",
                    arguments={"preferred_date": date.today().isoformat()},
                    llm=None,
                    pipeline_worker=None,
                    context=None,
                    result_callback=result_callback,
                    app_resources=None,
                )
            )

        asyncio.run(run())
        self.assertEqual(captured["result"]["status"], "booked")
        self.assertIn("not over", captured["result"]["next_step"])
        self.assertNotIn("end_call", captured["result"]["next_step"])

    def test_p09_closing_phrase(self) -> None:
        self.assertIs(tools.CLOSING_PHRASE, prompt.CLOSING_PHRASE)
        self.assertIsNone(re.search(r"\d", prompt.CLOSING_PHRASE))
        for phrase in ("shortly", "soon", "right away", "send", "follow up"):
            self.assertNotIn(phrase, prompt.CLOSING_PHRASE.lower())

    def test_p10_names(self) -> None:
        system_prompt = build_prompt()
        rule = (
            "Never use a name for the caller, and never say \"sir\" or \"ma'am\", "
            "even if they tell you their name."
        )
        self.assertEqual(system_prompt.count("Never use a name for the caller"), 1)
        self.assertIn(rule, system_prompt)
        self.assertEqual(system_prompt.count("sir"), 1)
        self.assertEqual(system_prompt.count("ma'am"), 1)
        parameters = inspect.signature(prompt.build_system_prompt).parameters
        self.assertNotIn("lead_name", parameters)
        self.assertNotIn("agent_name", parameters)

    def test_p11_speech_and_gender_rules(self) -> None:
        system_prompt = build_prompt()
        self.assertIn("Amounts, percentages, dates and times are words", system_prompt)
        self.assertIn("using the knowledge base's \"spoken\" line", system_prompt)
        self.assertNotIn("25:25:25:25", system_prompt)
        self.assertIn(
            "Never read it out as a ratio; say it as a sentence.", system_prompt
        )
        self.assertIn("You are Aarya, a woman", system_prompt)
        for hindi in ("rahi", "karungi", "raha", "karunga"):
            self.assertNotIn(hindi, system_prompt.lower())

    def test_p12_size(self) -> None:
        system_prompt = prompt.build_system_prompt(
            project_kb={},
            today=FIXED_TODAY,
        )
        self.assertLessEqual(len(system_prompt), 4900)

    def test_p13_greeting_appears_once(self) -> None:
        for disclosure_mode in ("on_ask", "upfront"):
            with patch.object(prompt, "AI_DISCLOSURE_MODE", disclosure_mode):
                for lead_source in (
                    prompt.LEAD_SOURCE_DEMO_FORM,
                    prompt.LEAD_SOURCE_LEAD,
                ):
                    with self.subTest(
                        disclosure_mode=disclosure_mode,
                        lead_source=lead_source,
                    ):
                        messages = prompt.build_initial_messages(
                            FIXED_KB,
                            lead_source=lead_source,
                            lead_project_name="Test Heights",
                            today=FIXED_TODAY,
                        )
                        self.assertEqual(
                            [message["role"] for message in messages],
                            ["system", "assistant"],
                        )
                        greeting = messages[-1]["content"]
                        company_block = messages[0]["content"].split(
                            "[COMPANY]\n", 1
                        )[1].split("[CURRENT DATE]", 1)[0]
                        self.assertIn(
                            "Your greeting has already been spoken",
                            company_block,
                        )
                        self.assertIn(
                            "Never greet or introduce yourself again",
                            company_block,
                        )
                        self.assertEqual(
                            sum(message["content"].count(greeting) for message in messages),
                            1,
                        )

    def test_p14_no_unresolved_placeholders(self) -> None:
        kb_without_project = {"developer": "Test Developer"}
        system_prompt = prompt.build_system_prompt(
            project_kb=kb_without_project,
            today=FIXED_TODAY,
        )
        without_kb = system_prompt.replace(json.dumps(kb_without_project, indent=2), "")
        self.assertIsNone(re.search(r"\{[^}]+\}", without_kb))
        self.assertIsNone(re.search(r"<[^>]+>", without_kb))
        self.assertNotIn("None", without_kb)
        self.assertIsNone(re.search(r"\[(?:Name|Developer|Company)[^]]*\]", without_kb))
        self.assertTrue(
            set(re.findall(r"\[([^]]+)\]", without_kb)).issubset(SECTION_HEADERS)
        )
        self.assertIn("the sample project", system_prompt)

    def test_p15_names_that_must_not_be_spoken(self) -> None:
        for disclosure_mode in ("on_ask", "upfront"):
            with patch.object(prompt, "AI_DISCLOSURE_MODE", disclosure_mode):
                for lead_source in (
                    prompt.LEAD_SOURCE_DEMO_FORM,
                    prompt.LEAD_SOURCE_LEAD,
                ):
                    system_prompt = build_prompt(
                        lead_source=lead_source,
                        lead_project_name="Test Heights",
                    )
                    spoken_strings = (
                        [system_prompt, prompt.CLOSING_PHRASE]
                        + greetings()
                        + you_lines(system_prompt)
                    )
                    for spoken in spoken_strings:
                        self.assertNotIn("nxlyr", spoken.lower())
                        self.assertNotIn("neha", spoken.lower())
                    self.assertIn("Next Layer", system_prompt)
                    company_block = system_prompt.split("[COMPANY]\n", 1)[1].split(
                        "[CURRENT DATE]", 1
                    )[0]
                    self.assertIn(
                        "If they ask which company, say Next Layer", company_block
                    )

    def test_p16_persona_gone(self) -> None:
        self.assertNotIn("persona", build_prompt().lower())
        self.assertNotIn(
            "persona_context",
            inspect.signature(prompt.build_system_prompt).parameters,
        )

    def test_p17_greeting_frame(self) -> None:
        bot = import_bot()
        source = Path(bot.__file__).read_text()
        self.assertIn("TTSSpeakFrame(greeting, append_to_context=False)", source)
        self.assertRegex(
            source,
            r"messages = build_initial_messages\(\s*project_kb, "
            r"lead_source=LEAD_SOURCE_DEMO_FORM\s*\)",
        )
        self.assertIn("LLMContext(messages=messages, tools=TOOL_SCHEMAS)", source)
        self.assertNotIn("lead_source=LEAD_SOURCE_LEAD", source)

    def test_p18_lead_template_unreachable(self) -> None:
        bot = import_bot()
        self.assertNotIn("lead_source", inspect.signature(bot.run_bot).parameters)

    def test_p19_no_promise_to_send(self) -> None:
        allowed_prompt_phrases = (
            "You cannot send brochures, WhatsApp messages, emails or links, and you never offer to.",
            "The caller sent us an enquiry about Test Heights.",
            "The caller sent us an enquiry.",
        )
        allowed_greeting_phrases = ("the enquiry you sent in",)
        forbidden = (
            r"brochures?",
            r"whatsapp",
            r"e-?mails?",
            r"links?",
            r"send",
            r"sends",
            r"sending",
            r"sent",
        )
        for disclosure_mode in ("on_ask", "upfront"):
            with patch.object(prompt, "AI_DISCLOSURE_MODE", disclosure_mode):
                prompt_cases = (
                    build_prompt(),
                    build_prompt(
                        lead_source=prompt.LEAD_SOURCE_LEAD,
                        lead_project_name="Test Heights",
                    ),
                    build_prompt(lead_source=prompt.LEAD_SOURCE_LEAD),
                )
                for system_prompt in prompt_cases:
                    self.assertIn(allowed_prompt_phrases[0], system_prompt)
                    without_allowed = system_prompt.replace(
                        json.dumps(FIXED_KB, indent=2), ""
                    )
                    for phrase in allowed_prompt_phrases:
                        without_allowed = without_allowed.replace(phrase, "")
                    for word in forbidden:
                        self.assertIsNone(
                            re.search(
                                rf"\b(?:{word})\b",
                                without_allowed,
                                re.IGNORECASE,
                            )
                        )

                spoken_strings = (
                    greetings() + [prompt.CLOSING_PHRASE] + you_lines(prompt_cases[0])
                )
                for spoken in spoken_strings:
                    for phrase in allowed_greeting_phrases:
                        spoken = spoken.replace(phrase, "")
                    for word in forbidden:
                        self.assertIsNone(
                            re.search(rf"\b(?:{word})\b", spoken, re.IGNORECASE)
                        )


if __name__ == "__main__":
    unittest.main()
