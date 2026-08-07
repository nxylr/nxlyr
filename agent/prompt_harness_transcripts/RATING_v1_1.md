# Prompt Harness Transcript Rating — v1.1

Re-rates scenarios **01, 03, 05 only** (the ones that failed, or contained the
reputational-claim pattern, in `RATING_v1.md`) against the updated `[RULES]`
block: a concrete too-long/correct-length example added to the 3-sentence
rule, and a new rule against unverifiable reputation/quality claims. 02 and
04 were not regenerated — they already passed cleanly in v1.

Same method as v1: sentence counts are programmatic (`[^.!?]+[.!?]` split,
re-verified below), bracket/list checks are grep-verified.

---

## Before / after on every line that failed in v1

| File | Line | v1 (before) | v1.1 (after) | Verdict |
|---|---|---|---|---|
| 01 | length | n/a — 01 passed length in v1 | n/a | — |
| 01 | list-reading | line 9: *"the value really comes from **the location, amenities, and quality of the homes**"* | line 9 (new content): *"Once I walk you through what's included — **the amenities, the location, the payment plan** — the value usually makes a lot more sense."* | **STILL FAILS** — different wording, same 3-item list pattern (see note below: this is verbatim from this repo's own `FEW_SHOT_EXAMPLES`) |
| 03 | length (line 9) | 4 sentences: *"Right, I hear you. While some projects might promise quicker possession, our timelines ensure the highest quality construction and attention to detail. Plus, the amenities and location really make the wait worthwhile. Would you be interested in visiting the site to get a better feel for what we're offering?"* | 3 sentences: *"Got it, and I understand the wait can seem long. The timeline ensures detailed attention to construction quality and amenities. Would you be interested in visiting the site to see the potential firsthand?"* | **FIXED** (4→3) |
| 03 | length (line 12) | 4 sentences: *"I get that. Sometimes seeing the project firsthand can make a big difference. It allows you to experience the quality and the community vibe that sets it apart. Would you like me to arrange a site visit for you?"* | 3 sentences: *"I understand. Seeing the project can often provide a clearer picture of its value. How about setting up a visit to explore what we offer?"* | **FIXED** (4→3) |
| 03 | list-reading (line 6) | *"This project offers a unique combination of **premium amenities, a prime location, and flexible payment options**"* | *"What often sets us apart are **the amenities, location, and flexible payment plans** we offer"* | **STILL FAILS** — same X/Y-and-Z pattern, different wording |
| 03 | reputational claim (line 9, was a PASS\* note in v1) | *"our timelines ensure the **highest quality construction** and attention to detail"* | *"The timeline **ensures detailed attention to construction quality** and amenities"* | **IMPROVED, still borderline** — the superlative ("highest") is gone, but it's still an assertion about construction-quality attention with no KB fact behind it, just softer-worded. Not a clean pass. |
| 05 | length (line 9) | 4 sentences: *"I apologize for any confusion. I'll make sure to check our records. If there's anything else you might be interested in, feel free to let us know. Have a great day!"* | 3 sentences: *"I'm sorry for the mix-up. I'll make sure to update our records. Have a great day!"* | **FIXED** (4→3), and cleaner — the soft residual pitch ("if there's anything else you might be interested in") is gone too, not just shortened |

**New issue, not present in v1 for this scenario:** 01, line 12. v1 deferred cleanly on GST: *"the total can vary... I can provide a detailed breakdown when we meet."* v1.1 states it more confidently: *"it includes all charges like GST"* — asserting what's included as settled fact, with no KB behind it. Not one of the four fact-types the check is scoped to (price/sqft/possession date/floor count), and not a reputation claim either, but the same underlying discipline (defer when you don't have the fact) slipped here. Flagged for visibility, not scored as a fail under either of the two existing criteria.

---

## 01_price_focused.txt

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | PASS | line 6: 2, line 9: 3, line 12: 2 |
| 2 | List-reading | **FAIL** | line 9: *"the amenities, the location, the payment plan"* — this is the repo's own `FEW_SHOT_EXAMPLES` entry for the "This sounds expensive" objection, echoed near-verbatim (`bot.py`'s conversation-examples block itself contains this 3-item list). The RULES fix didn't touch it because the model is pattern-matching the example, not violating the rule from scratch. |
| 3 | Ack variation | PASS | "Right" → "I understand" → (none). No repeats. |
| 4 | Fact invention | PASS\* (new note) | No price/sqft/possession date/floor count invented. **New:** line 12, *"it includes all charges like GST"* is stated as settled fact with nothing behind it — see before/after table above. Not one of the 4 listed fact-types, so not a strict fail, but worth watching. |
| 5 | AI self-disclosure | PASS | — |
| 6 | Bracket/template leakage | PASS | — |

## 03_objection_heavy.txt

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | **FIXED — now PASS** | line 6: 3, line 9: 3 (was 4), line 12: 3 (was 4) |
| 2 | List-reading | **FAIL** (unchanged) | line 6: *"the amenities, location, and flexible payment plans"* |
| 3 | Ack variation | PASS | "Right" → "Got it" (+ "I understand" embedded) → "I understand". No exact repeat of the *primary* ack word, though "I understand" appears as a phrase in both line 9 and line 12 — worth a light note, not a strict violation. |
| 4 | Fact invention / reputational claims | **IMPROVED, still borderline** | line 9: superlative dropped ("highest quality" → "detailed attention to... quality"), but still an unbacked quality assertion — see before/after table. |
| 5 | AI self-disclosure | PASS | — |
| 6 | Bracket/template leakage | PASS | — |

## 05_wrong_number.txt

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | **FIXED — now PASS** | line 6: 2, line 9: 3 (was 4), line 12: 2 |
| 2 | List-reading | PASS | none |
| 3 | Ack variation | PASS | (none) → "I'm sorry" → "Got it". No repeats. |
| 4 | Fact invention | PASS | nothing stated to invent |
| 5 | AI self-disclosure | PASS | — |
| 6 | Bracket/template leakage | PASS | — |
| — | **Scenario-specific (critical): disengages within 1–2 turns?** | **PASS, improved** | Wrong-number at line 8. Bot's next turn (line 9): *"I'm sorry for the mix-up. I'll make sure to update our records. Have a great day!"* — backs off in 1 turn, same as v1, but now also within the length limit **and** without v1's residual "if there's anything else you might be interested in" soft-pitch phrase. Cleaner disengagement than before, not just shorter. |

---

## Summary: what the RULES fix did and didn't fix

| Target | Result |
|---|---|
| 3-sentence limit under objection/apology pressure | **Fixed.** All 3 length failures from v1 (03 line 9, 03 line 12, 05 line 9) are now within limit. 9/9 bot turns across these 3 regenerated files are ≤3 sentences, versus 6/9 before. |
| Unverifiable reputational/quality claims | **Partially fixed.** The one instance directly re-tested (03 line 9) dropped its superlative ("highest quality" → softer phrasing) but still asserts an unbacked quality standard. Not a regression, but not a clean pass either — the new rule reduced the severity without eliminating the pattern. |
| List-reading (not targeted by this fix) | **Unchanged — still fails**, in both files that had it (01, 03). Notably, 01's violation traces directly to this repo's own `build_system_prompt()` `FEW_SHOT_EXAMPLES`, which contains a 3-item list itself (`bot.py`, the "This sounds expensive" example). The model is correctly imitating a bad example baked into the prompt, not violating the rule independently. Fixing the RULES text won't touch this — the example itself needs editing. |
| New side-observation | 01 line 12 now states a GST-inclusion detail with more confidence than v1's fully-deferred version — not scored as a failure under either existing criterion, but a small regression in the defer-when-unknown discipline, worth a future look. |
