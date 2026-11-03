import hashlib
import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

import commitments
import prompt


FIXED_DATE = date(2026, 1, 2)
FIXED_KB = {
    "project_name": "Test Heights",
    "pricing": {"spoken": "two point two crore rupees"},
}
EN_PROMPT_HASHES = {
    "v2": "3751c76b760fdb5ef3e1a0b30533f3d7b602768f10720ecad3a0247a8e6ae094",
    "v21": "20cc35fb089d03ccb63e19d27c30b6cb42239554ab72bb881544e9f453d31b56",
}
EN_V21_MESSAGES_HASH = (
    "6b40d0b02d613c3bd1cafe4bb99af76cf5614b382eb3e8fb2b5f7b1f036f0499"
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _aggregate(text: str, chunk_sizes: tuple[int, ...]) -> tuple[list[str], str | None]:
    aggregator = SimpleTextAggregator()
    released: list[str] = []
    offset = 0
    index = 0
    while offset < len(text):
        size = chunk_sizes[index % len(chunk_sizes)]
        async for item in aggregator.aggregate(text[offset : offset + size]):
            released.append(item.text)
        offset += size
        index += 1
    tail = await aggregator.flush()
    return released, tail.text if tail else None


class LanguagePromptTests(unittest.IsolatedAsyncioTestCase):
    def test_l03_english_prompt_and_messages_are_byte_identical(self) -> None:
        for version, expected_hash in EN_PROMPT_HASHES.items():
            with self.subTest(version=version):
                text = prompt.build_system_prompt(
                    project_kb=FIXED_KB,
                    today=FIXED_DATE,
                    version=version,
                    language_mode="en",
                )
                self.assertEqual(_sha(text), expected_hash)
                self.assertNotIn("[LANGUAGE]", text)
                self.assertIsNone(re.search(r"[\u0900-\u097f]", text))

        messages = prompt.build_initial_messages(
            FIXED_KB,
            today=FIXED_DATE,
            version="v21",
            language_mode="en",
        )
        rendered = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.assertEqual(_sha(rendered), EN_V21_MESSAGES_HASH)

    def test_l05_hinglish_addendum_is_exact_last_once_and_greeting_stays_english(self) -> None:
        self.assertEqual(len(prompt.HINGLISH_ADDENDUM), 3710)
        self.assertEqual(len(prompt.HINGLISH_ADDENDUM.splitlines()), 15)
        self.assertEqual(
            _sha(prompt.HINGLISH_ADDENDUM),
            "defe07b9fee66c7b5622ea35a831c3be6d5fea2ff339422963ede23253ca8ac8",
        )
        for version in ("v2", "v21"):
            with self.subTest(version=version):
                messages = prompt.build_initial_messages(
                    FIXED_KB,
                    today=FIXED_DATE,
                    version=version,
                    language_mode="hinglish",
                )
                system = messages[0]["content"]
                self.assertTrue(system.endswith(prompt.HINGLISH_ADDENDUM))
                self.assertEqual(system.count("[LANGUAGE]"), 1)
                self.assertLess(system.index('"project_name": "Test Heights"'), system.index("[LANGUAGE]"))
                self.assertEqual(
                    messages[-1]["content"],
                    prompt.build_greeting(prompt.LEAD_SOURCE_DEMO_FORM, "Test Heights"),
                )

    def test_l06_addendum_has_approved_gender_fixed_lines_and_never_rules(self) -> None:
        text = prompt.HINGLISH_ADDENDUM
        for required in (
            "मैं बता सकती हूँ",
            "जी, मैं यहाँ हूँ।",
            "जी, आपकी आवाज़ आ रही है।",
            "माफ़ कीजिए, मुझे ठीक से सुनाई नहीं दिया।",
            "जी, मैं एक AI assistant हूँ, Next Layer की तरफ़ से call कर रही हूँ।",
            "Never switch on your own",
            "Never write Hindi in Latin letters",
            "Never write an English word in Devanagari",
            "Never use the masculine form",
            'Never "तुम" or "तू"',
            "Never digits",
            "Never convert, round or recompute a figure",
            "Never invent one",
            "Never end a reply without punctuation",
            "Never deny it",
            "Never say a visit is booked",
        ):
            with self.subTest(required=required):
                self.assertEqual(text.count(required), 1)
        for romanised in (
            "hai",
            "hain",
            "hoon",
            "aap",
            "kya",
            "nahi",
            "haan",
            "theek",
            "bataiye",
            "sakti",
            "chahiye",
            "baje",
        ):
            with self.subTest(romanised=romanised):
                self.assertIsNone(re.search(rf"\b{romanised}\b", text, re.I))

    async def test_l07_devanagari_sentence_splitting_matches_pipecat_150(self) -> None:
        two_sentences = "जी, जानकारी यहाँ है। कीमत वहाँ है। आगे"
        question = "आप कब आएँगे? Saturday ठीक है। आगे"
        for sizes in ((1,), (3,), (1, 4, 2, 3)):
            with self.subTest(sizes=sizes, case="danda"):
                released, tail = await _aggregate(two_sentences, sizes)
                self.assertEqual(released[:2], ["जी, जानकारी यहाँ है।", "कीमत वहाँ है।"])
                self.assertEqual(tail, "आगे")
            with self.subTest(sizes=sizes, case="question"):
                released, tail = await _aggregate(question, sizes)
                self.assertEqual(released[:2], ["आप कब आएँगे?", "Saturday ठीक है।"])
                self.assertEqual(tail, "आगे")

            released, tail = await _aggregate("जी हाँ जानकारी यहाँ है", sizes)
            self.assertEqual(released, [])
            self.assertEqual(tail, "जी हाँ जानकारी यहाँ है")

            released, tail = await _aggregate("आप आएँगे?हाँ, बोलिए।", sizes)
            self.assertEqual(released, [])
            self.assertEqual(tail, "आप आएँगे?हाँ, बोलिए।")

    def test_l14_fixed_failure_and_closing_sentences_are_unchanged(self) -> None:
        self.assertEqual(
            {
                "BOOKING_NOT_CONFIRMED": commitments.BOOKING_NOT_CONFIRMED,
                "CALLBACK_NOT_PASSED_ON": commitments.CALLBACK_NOT_PASSED_ON,
                "PAST_TIME": commitments.PAST_TIME,
                "PAST_DATE": commitments.PAST_DATE,
                "TIME_UNUSABLE": commitments.TIME_UNUSABLE,
                "OUTSIDE_HOURS": commitments.OUTSIDE_HOURS,
                "TOO_FAR": commitments.TOO_FAR,
                "DATE_UNUSABLE": commitments.DATE_UNUSABLE,
                "CLOSING_PHRASE": prompt.CLOSING_PHRASE,
            },
            {
                "BOOKING_NOT_CONFIRMED": "Sorry, I couldn't confirm that visit just now, so please don't count on it yet.",
                "CALLBACK_NOT_PASSED_ON": "I couldn't pass that on just now.",
                "PAST_TIME": "That time has already gone. What time later today, or which other day, suits you?",
                "PAST_DATE": "That day has already gone. Which day suits you?",
                "TIME_UNUSABLE": "I didn't get a time I can book. Could you tell me the time again?",
                "OUTSIDE_HOURS": "Site visits are between nine in the morning and seven in the evening. What time in that window suits you?",
                "TOO_FAR": "I can only book within the next three months. Which date in that time suits you?",
                "DATE_UNUSABLE": "I didn't get a date I can book. Which day suits you?",
                "CLOSING_PHRASE": "Thanks for your time. Have a good day.",
            },
        )


if __name__ == "__main__":
    unittest.main()
