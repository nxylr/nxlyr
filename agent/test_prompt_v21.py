import re
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import prompt
from tools import CLOSING_PHRASE


FIXED_DATE = date(2026, 1, 2)
V2_BANNED = (
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
V21_BANNED = (
    "Great",
    "I see",
    "Sure thing",
    "Absolutely",
    "Sure",
    "I hear you",
    "Fair question",
    "I appreciate you sharing",
    "Got it",
    "Understood",
)

ON_ASK_DISCLOSURE = (
    "AI DISCLOSURE (switch: AI_DISCLOSURE_MODE in prompt.py): Do not mention "
    "that you are an AI unless asked. If the caller asks whether you are an "
    "AI, a bot, a machine, a recording or a real person, answer at once and "
    "truthfully: \"I'm an AI assistant calling for Next Layer.\" Then carry "
    "on. Never deny it, never dodge, never claim to be human."
)
UPFRONT_DISCLOSURE = (
    "AI DISCLOSURE (switch: AI_DISCLOSURE_MODE in prompt.py): You told the "
    "caller in your greeting that you are an AI assistant. If they ask again, "
    "confirm in a few words. Never deny it and never claim to be human."
)

GOLDEN_V2_TEMPLATE = """[CORE RULES]
This is a live phone call. Everything you write is spoken aloud.
- Say one or two short sentences, about twenty-five words. Make one point, then stop and let the caller lead. Never recite everything you know.
- Start with the answer itself, not a reaction. Never open a reply with: Great, I see, Sure thing, Absolutely, Sure, I hear you, Fair question, I appreciate you sharing, Got it, Right.
- End with a question only when the answer moves the conversation forward. Most replies end with a statement.
- Do not echo a one-word answer such as "yes" or "okay". Carry on with the next useful thing.
- Say each fact once. No lists. No lecturing, long reassurance, or praise for the caller's questions.
- Write for the ear. Amounts, percentages, dates and times are words: "one point two crore rupees", "twenty-five percent", "Saturday the fifteenth", "eleven in the morning". Never digits, "Rs", a rupee sign, "Cr", or a dash between numbers. Function arguments are the one exception.
- You do not know the caller's name. Never use a name for the caller, and never say "sir" or "ma'am", even if they tell you their name.
- If you are not sure you heard a name or a number, check it as a question first. Never repeat a name you are unsure of.
- Use only facts in the knowledge base; if you lack one, say so in one sentence. Never invent a price, date, distance, name, reputation or track record. No discounts.
- Never say when anything will happen: no "shortly", "soon", "right away", "today".
- You have three real functions. Call one only when its condition is met, in the same turn you speak about it. Never say something is done unless you called the function that does it.
- end_call hangs up on the caller. Call it only when the caller's latest message says goodbye, says they are finished, asks to end the call or stop calling, or says it is a wrong number. A booking, a passed-on question or a finished answer is not the end. Never call end_call in the same turn as another function, or in the turn after a function result unless the caller's latest message already said goodbye. If unsure, stay on the line.
- transfer_to_human passes your question to a colleague by message. It connects nobody. Say only what its result tells you, with no time.

[REAL ESTATE PACK]
- Say the project's full name once. If the greeting already said it, say "the project" or "it" from then on, unless asked.
- If the caller says a project name close to the sample project but not the same, ask "Did you mean the sample project?" before answering.
- Answer what was asked with one or two facts.
- Price: give the figure asked for, in words, once, with no build-up. If the caller says it is expensive, ask what range they had in mind. Do not defend the price.
- Say a payment plan as one plain sentence, using the knowledge base's "spoken" line if there is one. Never read it out as a ratio; say it as a sentence.
- Suggest a site visit once, after the caller shows interest. If they agree, ask which day and time suit them, then call book_site_visit as soon as they give one; preferred_date is a real future date worked out from [CURRENT DATE]. After booking, confirm the day and time in one sentence and let the caller lead. The call carries on.

[COMPANY]
You are Aarya, a woman, and you work for Next Layer.
This is a demo call. The caller asked for a demo of how you would speak to a buyer, using a sample project, the sample project. Treat them as that buyer. If they ask what this is, say it is a demo.
Your greeting has already been spoken: it is the first assistant message. Never greet or introduce yourself again. If the caller only says hello, answer in five words or fewer and wait. Only if they ask who you are or why you called, say your name, Next Layer and the reason, once. If they ask which company, say Next Layer.
You cannot send brochures, WhatsApp messages, emails or links, and you never offer to.
<DISCLOSURE>

[CURRENT DATE]
Today is Friday, 02 January 2026 (2026-01-02).
Work out every date the caller mentions relative to this, and never emit a date earlier than it.

[PROJECT KNOWLEDGE BASE]
(none loaded yet)

[HOW IT SOUNDS]
Caller: Yes, go ahead.
You: So, is this for your own family, or as an investment?

Caller: This sounds expensive.
You: What range were you thinking of?

Caller: Hello?
You: Yes, I can hear you.

Caller: Saturday at eleven works for me.
You: I've put you down for Saturday at eleven in the morning."""


NEW_QUESTION_RULE = (
    "- Most replies end with a statement. End a reply with a question only when the call cannot move on without the answer: whether the home is for them or an investment, a choice between two things, or a day and time. Never ask more than one question in a reply, never end two replies in a row with a question, and never ask a question after a goodbye. After you answer a question, stop. Never end with a general offer such as \"Would you like to know more?\", \"Anything else you'd like to know?\", \"Is there anything else?\", \"How can I help you?\" or \"What would you like to know?\"."
)
NEW_BOOKING_RULE = (
    "- Never say a visit is booked, put down, noted or passed on unless you call the function in that same reply, or a function result has just told you it is done. If neither, ask for what is missing instead."
)


def render(version: str = "v21") -> str:
    return prompt.build_system_prompt(project_kb={}, today=FIXED_DATE, version=version)


def strip_tags(text: str) -> str:
    return " ".join(re.sub(r"\[[^]]+\]", "", text).split())


class PromptV21Tests(unittest.TestCase):
    def test_n00_v2_default_is_the_stored_golden_in_both_disclosure_modes(self) -> None:
        self.assertEqual(prompt.BANNED_OPENERS, V2_BANNED)
        for mode, disclosure in (
            ("on_ask", ON_ASK_DISCLOSURE),
            ("upfront", UPFRONT_DISCLOSURE),
        ):
            with self.subTest(mode=mode), patch.object(prompt, "AI_DISCLOSURE_MODE", mode):
                expected = GOLDEN_V2_TEMPLATE.replace("<DISCLOSURE>", disclosure)
                self.assertEqual(
                    prompt.build_system_prompt(project_kb={}, today=FIXED_DATE),
                    expected,
                )
                self.assertEqual(
                    prompt.build_system_prompt(
                        project_kb={}, today=FIXED_DATE, version="v2"
                    ),
                    expected,
                )
                messages = prompt.build_initial_messages({}, today=FIXED_DATE)
                self.assertEqual(messages[0]["content"], expected)

    def test_n01_v21_blocks_are_ordered_once(self) -> None:
        text = render()
        blocks = (
            "[CORE RULES]",
            "[REAL ESTATE PACK]",
            "[HOW THE CALL GOES]",
            "[COMPANY]",
            "[CURRENT DATE]",
        )
        header_positions = [text.index(f"\n{block}\n") if not text.startswith(block) else 0 for block in blocks]
        self.assertEqual(
            [text.count(f"\n{block}\n") + int(text.startswith(block)) for block in blocks],
            [1] * len(blocks),
        )
        self.assertEqual(header_positions, sorted(header_positions))

    def test_n02_v21_banned_openers_are_pinned_and_only_in_ban_line(self) -> None:
        self.assertEqual(prompt.BANNED_OPENERS_V21, V21_BANNED)
        text = render()
        ban_line = next(line for line in text.splitlines() if "Never open a reply with:" in line)
        without_ban_line = text.replace(ban_line, "")
        for phrase in V21_BANNED:
            if phrase == "Sure":
                self.assertNotRegex(without_ban_line, r"(?mi)^You:\s*Sure(?:\b|[.!?,])")
            else:
                self.assertNotIn(phrase, without_ban_line)
        self.assertIn('"Right, so"', text)
        for greeting in (
            prompt.build_greeting(prompt.LEAD_SOURCE_DEMO_FORM, "Test Heights"),
            prompt.build_greeting(prompt.LEAD_SOURCE_LEAD, "Test Heights"),
            CLOSING_PHRASE,
        ):
            for phrase in V21_BANNED:
                self.assertNotIn(phrase, greeting)

    def test_n03_samples_obey_every_sample_rule(self) -> None:
        samples = [line.removeprefix("You: ") for line in render().splitlines() if line.startswith("You: ")]
        self.assertEqual(len(samples), 8)
        banned_pattern = re.compile("|".join(re.escape(value) for value in V21_BANNED), re.I)
        forbidden = re.compile(r"\d|\bRs\b|\[|\bsend\b|WhatsApp|shortly|soon", re.I)
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertIsNone(forbidden.search(sample))
                self.assertIsNone(banned_pattern.search(sample))
                first_sentence = re.split(r"(?<=[.!?])(?:\s|$)", sample, maxsplit=1)[0]
                self.assertLessEqual(len(re.findall(r"\b[\w']+\b", first_sentence)), 8)
        self.assertEqual(sum(sample.endswith("?") for sample in samples), 4)
        self.assertEqual(sum(sample.startswith("So") for sample in samples), 1)
        self.assertEqual(sum(sample.startswith("Okay so") for sample in samples), 1)
        self.assertIn("Hi, yes, I'm here.", samples)
        self.assertNotIn("Aarya", next(sample for sample in samples if sample.startswith("Hi,")))
        self.assertNotIn("Next Layer", next(sample for sample in samples if sample.startswith("Hi,")))
        self.assertIn("Yes, I can hear you.", samples)
        self.assertEqual(render().count("These show the style, not lines to repeat."), 1)
        self.assertNotIn("Caller: Saturday at eleven works for me.", render())
        self.assertNotIn("You're down for Saturday, eleven in the morning.", render())

    def test_n04_each_new_rule_exists_once(self) -> None:
        text = render()
        markers = (
            "Make your first sentence short, eight words or fewer",
            "Use one in about one reply out of three",
            "Right before you call book_site_visit or transfer_to_human",
            'Never say "um" or "uh".',
            "connect your answer to it in a few words",
            "If the caller corrects you",
            "If what the caller said does not make sense or sounds cut off",
            "below half the lowest price or above double the highest",
            "Just to check, forty lakhs?",
            'When a knowledge-base field has a "spoken" version',
            NEW_BOOKING_RULE,
            NEW_QUESTION_RULE,
            "Then learn what matters most to them by asking about one thing at a time, such as which size suits them. Never offer a list of topics to choose from. Spread your questions across the call.",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertEqual(text.count(marker), 1)
        self.assertEqual(text.count('"um"'), 1)
        self.assertEqual(text.count('"uh"'), 1)
        for phrase in (
            'Would you like to know more?',
            "Anything else you'd like to know?",
            'Is there anything else?',
            'How can I help you?',
            'What would you like to know?',
        ):
            with self.subTest(closer=phrase):
                self.assertIn(phrase, text)
        self.assertNotIn("size, budget, location or timing", text)

    def test_n05_near_miss_rule_embeds_the_correction(self) -> None:
        text = prompt.build_system_prompt(
            project_kb={"project_name": "Meridian Heights"},
            today=FIXED_DATE,
            version="v21",
        )
        self.assertNotIn('ask "Did you mean', text)
        self.assertIn("Never ask whether they meant it", text)
        near_miss_line = next(line for line in text.splitlines() if "sounds like Meridian Heights" in line)
        self.assertIn("Meridian Heights", near_miss_line)

    def test_n06_company_block_separates_greeting_presence_and_identity_questions(self) -> None:
        text = render()
        company = text.split("[COMPANY]\n", 1)[1].split("\n\n[CURRENT DATE]", 1)[0]
        self.assertIn('say "Hi, yes, I\'m here." and wait', company)
        self.assertIn('say "Yes." or "Yes, I can hear you." and carry on', company)
        self.assertIn("unless the caller asks who you are, which company, or why you called; then say it once", company)
        self.assertNotIn("Never greet or introduce yourself again", company)
        messages = prompt.build_initial_messages({}, today=FIXED_DATE, version="v21")
        self.assertEqual(len(messages), 2)
        greeting = messages[-1]["content"]
        self.assertEqual(sum(message["content"].count(greeting) for message in messages), 1)

    def test_n07_carried_rules_and_closing_phrase_are_unchanged(self) -> None:
        text = render()
        carried = (
            ON_ASK_DISCLOSURE,
            prompt.END_CALL_RULE,
            prompt.TRANSFER_TO_HUMAN_RULE,
            '- You do not know the caller\'s name. Never use a name for the caller, and never say "sir" or "ma\'am", even if they tell you their name.',
            "You cannot send brochures, WhatsApp messages, emails or links, and you never offer to.",
            '- Say a payment plan as one plain sentence, using the knowledge base\'s "spoken" line if there is one. Never read it out as a ratio; say it as a sentence.',
        )
        for line in carried:
            self.assertIn(line, text)
        self.assertEqual(CLOSING_PHRASE, "Thanks for your time. Have a good day.")

    def test_n10_builder_3_rules_appear_once_in_v21_and_not_in_v2(self) -> None:
        for rule in (NEW_BOOKING_RULE, NEW_QUESTION_RULE):
            with self.subTest(rule=rule[:40]):
                self.assertEqual(render().count(rule), 1)
                self.assertNotIn(rule, render("v2"))
        self.assertEqual(render().count("Never ask more than one question in a reply"), 1)

    def test_n08_empty_kb_v21_size_is_capped(self) -> None:
        size = len(render())
        print(f"v21 empty-KB prompt size: {size}")
        self.assertLessEqual(size, 9063)

    def test_n09_plain_greetings_are_unchanged_and_tags_never_enter_context(self) -> None:
        cases = (
            (prompt.LEAD_SOURCE_DEMO_FORM, None),
            (prompt.LEAD_SOURCE_DEMO_FORM, "Test Heights"),
            (prompt.LEAD_SOURCE_LEAD, None),
            (prompt.LEAD_SOURCE_LEAD, "Test Heights"),
        )
        for mode in ("on_ask", "upfront"):
            with patch.object(prompt, "AI_DISCLOSURE_MODE", mode):
                for lead_source, project_name in cases:
                    with self.subTest(mode=mode, lead_source=lead_source, project=project_name):
                        plain = prompt.build_greeting(lead_source, project_name, tags=False)
                        tagged = prompt.build_greeting(lead_source, project_name, tags=True)
                        self.assertEqual(strip_tags(tagged), plain)
                        self.assertNotRegex(plain, r"\[[^]]+\]")
        messages = prompt.build_initial_messages(
            {"project_name": "Test Heights"}, version="v21"
        )
        self.assertNotRegex("\n".join(message["content"] for message in messages), r"\[[a-z ]+\]")
        for version in ("v2", "v21"):
            text = prompt.build_system_prompt(project_kb={}, version=version, today=FIXED_DATE)
            self.assertNotRegex(text, r"\{[^}]+\}")


if __name__ == "__main__":
    unittest.main()
