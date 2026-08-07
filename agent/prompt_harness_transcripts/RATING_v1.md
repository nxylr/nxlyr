# Prompt Harness Transcript Rating — v1

Rates the 5 transcripts in `agent/prompt_harness_transcripts/` against structural,
checkable criteria only (no "sounds natural" judgment — that's for real-call
testing). All 5 ran with `kb_loaded=False`. Line numbers refer to the `.txt`
files as saved.

Sentence counts were verified programmatically (naive `[^.!?]+[.!?]` split),
not just eyeballed.

Scoring key: **PASS** / **FAIL**. Where a claim doesn't meet the strict letter
of a criterion but shares its underlying risk, it's marked **PASS\*** with a
note — a qualitative judgment call flagged for visibility, not silently folded
into either bucket.

---

## 01_price_focused.txt

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | PASS | line 6: 3, line 9: 3, line 12: 3 |
| 2 | List-reading (3+ items in a row) | **FAIL** | line 9: *"the value really comes from **the location, amenities, and quality of the homes**"* — 3 items, X/Y/and-Z pattern |
| 3 | Acknowledgement variation | PASS | line 6 "Sure" → line 9 "I understand" → line 12 (none). No exact repeats. Note: 2 of 3 turns don't use the RULES-specified {Right/Sure/Got it} set at all. |
| 4 | Fact invention (most important) | PASS | No price, sqft, possession date, or floor count stated. All three price questions gracefully deferred ("can vary depending on the tower and floor," "I can provide a detailed breakdown when we meet"). |
| 5 | AI self-disclosure | PASS | Never breaks character. |
| 6 | Bracket/template leakage | PASS | None (grep-verified across the whole file). |

---

## 02_timeline_focused.txt

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | PASS | line 6: 3, line 9: 3, line 12: 3 |
| 2 | List-reading (3+ items in a row) | PASS | No 3-item lists found. |
| 3 | Acknowledgement variation | PASS | line 6 "Sure" → line 9 "I understand" → line 12 (none). No exact repeats. |
| 4 | Fact invention (most important) | PASS\* | No possession date, sqft, price, or floor count stated — timeline questions deferred ("can vary based on the specific phase," "let me check the availability... get back to you"). **Note:** line 12, *"Our developer has a strong track record of delivering projects on time"* is a confident, unverifiable reputational claim — not one of the four listed fact-types (price/sqft/possession date/floor count), so not a strict fail, but the same underlying problem (nothing backs this when `kb_loaded=False`). |
| 5 | AI self-disclosure | PASS | Never breaks character. |
| 6 | Bracket/template leakage | PASS | None. |

---

## 03_objection_heavy.txt

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | **FAIL** | line 9: 4 sentences ("Right, I hear you." / "While some projects..." / "Plus, the amenities..." / "Would you be interested..."). line 12: 4 sentences ("I get that." / "Sometimes seeing..." / "It allows you..." / "Would you like me..."). |
| 2 | List-reading (3+ items in a row) | **FAIL** | line 6: *"This project offers a unique combination of **premium amenities, a prime location, and flexible payment options**"* — 3 items, X/Y/and-Z pattern |
| 3 | Acknowledgement variation | PASS | line 6 "I understand" → line 9 "Right" → line 12 "I get that". No exact repeats — but note "I understand" (line 6) and "I get that" (line 12) are near-synonyms in different wording; not an exact-string repeat, so passes the letter of the check. |
| 4 | Fact invention (most important) | PASS\* | No price/sqft/possession date/floor count stated. **Note:** line 9, *"our timelines ensure the highest quality construction and attention to detail"* is another confident, unverifiable quality claim, same class of issue as 02's track-record line. |
| 5 | AI self-disclosure | PASS | Never breaks character. |
| 6 | Bracket/template leakage | PASS | None. |

---

## 04_site_visit.txt

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | PASS | line 6: 3, line 9: 2, line 12: 3 |
| 2 | List-reading (3+ items in a row) | PASS | No 3-item lists found. |
| 3 | Acknowledgement variation | PASS | line 6 "Absolutely" → line 9 "Sure" → line 12 "Great". No exact repeats. |
| 4 | Fact invention (most important) | PASS | No price/sqft/possession date/floor count invented. The Saturday-3pm detail in line 12 is the caller's own stated time being confirmed back, not something the bot invented. |
| 5 | AI self-disclosure | PASS | Never breaks character. |
| 6 | Bracket/template leakage | PASS | None. |
| — | **Scenario-specific: moves toward booking without being pushy?** | **PASS** | line 9, responding to the caller's own request to visit: *"Sure, I'd be happy to arrange a visit for you. Do you have a specific day in mind, or should I suggest a few available times?"* — takes the caller's lead rather than pushing. line 12 confirms the booking cleanly with no extra upsell attempt. |

---

## 05_wrong_number.txt

**This is the most important file in the batch — quoted in full below.**

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | **FAIL** | line 9: 4 sentences ("I apologize for any confusion." / "I'll make sure to check our records." / "If there's anything else you might be interested in, feel free to let us know." / "Have a great day!") |
| 2 | List-reading (3+ items in a row) | PASS | An automated grep initially flagged line 12 for a comma+"and" pattern, but on inspection it spans two separate sentences ("...removed from our list. Thank you for your time, **and** take care!"), not a 3-item list. No real violation. |
| 3 | Acknowledgement variation | PASS | line 6 (none / "Hi there!") → line 9 "I apologize" → line 12 "Absolutely". No exact repeats. |
| 4 | Fact invention (most important) | PASS | No facts of any kind stated — nothing to invent in a call this short. |
| 5 | AI self-disclosure | PASS | Never breaks character. |
| 6 | Bracket/template leakage | PASS | None. |
| — | **Scenario-specific (critical): recognizes disinterest and disengages within 1–2 turns, or keeps pitching?** | **PASS** | Caller states wrong-number at line 8: *"I never filled out any form about a property. I think you have the wrong number."* Bot's very next turn (line 9, the 1st turn after the signal): *"I apologize for any confusion. I'll make sure to check our records. If there's anything else you might be interested in, feel free to let us know. Have a great day!"* — apologizes, does not reassert the project or ask another qualifying question, offers only a generic low-pressure "if there's anything else" rather than repitching. Backs off in **1 turn**, not 2. (Note: this same turn is the one flagged for length above — the backing-off is correct, but it takes 4 sentences to do it.) |

---

## Summary across all 5

| File | 1. Length | 2. List-reading | 3. Ack variation | 4. Fact invention | 5. AI disclosure | 6. Bracket leakage |
|---|---|---|---|---|---|---|
| 01_price_focused | PASS | **FAIL** (L9) | PASS | PASS | PASS | PASS |
| 02_timeline_focused | PASS | PASS | PASS | PASS\* (L12 note) | PASS | PASS |
| 03_objection_heavy | **FAIL** (L9, L12) | **FAIL** (L6) | PASS | PASS\* (L9 note) | PASS | PASS |
| 04_site_visit | PASS | PASS | PASS | PASS | PASS | PASS |
| 05_wrong_number | **FAIL** (L9) | PASS | PASS | PASS | PASS | PASS |

**Scenario-specific:**

| File | Check | Result |
|---|---|---|
| 04_site_visit | Moves toward booking without being pushy | PASS |
| 05_wrong_number | Recognizes disinterest, disengages within 1–2 turns (critical) | **PASS** — backs off in 1 turn (line 9) |

**Structural pass rate:** 2/5 files (02, 04) clean on all 6 criteria. 01 has one list-reading violation. 03 has both a length and a list-reading violation — the weakest file structurally. 05 has one length violation on the turn that otherwise correctly disengages — the content of that turn is right, it's just too long.

**The single most important result:** the wrong-number scenario passes its critical check — the bot recognizes disinterest and disengages immediately rather than continuing to pitch, and no transcript in this batch invents a specific price, sqft figure, possession date, or floor count anywhere. The two flagged "adjacent" notes (02 line 12, 03 line 9) are unverifiable qualitative claims ("strong track record," "highest quality construction"), not the numeric/date fact-invention this check is primarily guarding against — worth watching, not a failure of the primary criterion.
