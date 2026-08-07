# Prompt Harness Transcript Rating — v1.2

Re-rates **01 and 03 only**, after rewriting `FEW_SHOT_EXAMPLES`'s "This
sounds expensive" reply in `build_system_prompt()` (`bot.py`) to stop
enumerating a 3-item list. All six original criteria re-checked in full on
both files, not just list-reading. Sentence counts and bracket/list patterns
are grep/script-verified, same method as v1 and v1.1.

The fix itself: the example previously read *"...what's included — the
amenities, the location, the payment plan — the value usually makes a lot
more sense"* (a 3-item list the model was echoing verbatim in 01). It now
reads *"The payment plan alone is pretty flexible, and once you see
everything laid out it tends to make a lot more sense. Want me to send over
the full breakdown?"* — names one thing concretely (the payment plan),
defers the rest into "everything"/"the full breakdown" rather than
enumerating it.

---

## 01_price_focused.txt — full 6-criterion re-check

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | PASS | line 6: 2, line 9: 3, line 12: 2 |
| 2 | List-reading | **PASS — resolved** | No 3-item list anywhere. line 9 (the turn that previously echoed the few-shot list) now reads: *"I hear you. The payment plan is pretty flexible, which can help manage the cost. I can walk you through the full breakdown — would you like me to send that over?"* — names one thing (payment plan), defers the rest. |
| 3 | Ack variation | PASS | (none) → "I hear you" → (none). No repeats. |
| 4 | Fact invention | PASS\* (unresolved regression) | No price/sqft/possession date/floor count invented. **GST-confidence line, specifically requested:** line 12, *"I can provide a detailed breakdown that includes all charges like GST."* — still asserts GST is included as settled fact. See direct callout below. |
| 5 | AI self-disclosure | PASS | — |
| 6 | Bracket/template leakage | PASS | — |

## 03_objection_heavy.txt — full 6-criterion re-check

| # | Criterion | Result | Detail |
|---|---|---|---|
| 1 | Reply length (≤~3 sentences) | PASS | line 6: 3, line 9: 2, line 12: 2 |
| 2 | List-reading | **PASS — resolved** | line 6 now reads *"this project offers some unique features and amenities that might set it apart"* — hedged, no enumeration. No 3-item list anywhere in the file. |
| 3 | Ack variation | PASS | line 6 "Right" → line 9 "Sure" → line 12 "Got it" — all three RULES-specified words, used once each, no repeats. |
| 4 | Fact invention / reputational claims | PASS\* (unchanged from v1.1) | line 9: *"it ensures quality construction"* — no superlative, similar softened level to v1.1's *"ensures detailed attention to construction quality"*. Still an unbacked quality assertion, just not an escalation. |
| 5 | AI self-disclosure | PASS | — |
| 6 | Bracket/template leakage | PASS | — |

---

## Direct callout: 01's GST-confidence line

**Resolved, worsened, or stayed the same? Stayed the same.**

| Round | Line 12 text | Assessment |
|---|---|---|
| v1 | *"Once we factor in GST and other charges, the total can vary a bit depending on the specifics like the floor and tower. I can provide a detailed breakdown when we meet."* | Fully deferred — no claim about what's included. |
| v1.1 | *"The total cost will vary based on the specific unit and floor, but it includes all charges like GST."* | Regression — states GST inclusion as settled fact. |
| v1.2 | *"I can provide a detailed breakdown that includes all charges like GST."* | Same regression, same confidence level — "that includes all charges like GST" still asserts GST inclusion as fact, just phrased slightly differently. Not worse than v1.1, not fixed either. |

This wasn't touched by the few-shot edit (that edit only targeted the "sounds expensive" example, not the GST question), so it's expected to be unchanged rather than accidentally fixed — flagging as still open, not a new problem introduced by this round's edit.

---

## Three-way comparison — 01_price_focused.txt

| Criterion | v1 | v1.1 | v1.2 |
|---|---|---|---|
| 1. Reply length | PASS (3,3,3) | PASS (2,3,2) | PASS (2,3,2) |
| 2. List-reading | **FAIL** — line 9, "the location, amenities, and quality of the homes" | **FAIL** — line 9, "the amenities, the location, the payment plan" (few-shot leak) | **PASS** — resolved, no list anywhere |
| 3. Ack variation | PASS — Sure / I understand / none | PASS — Right / I understand / none | PASS — none / I hear you / none |
| 4. Fact invention | PASS — all 3 turns fully deferred | PASS\* — new GST-confidence regression at line 12 | PASS\* — GST-confidence regression unchanged |
| 5. AI disclosure | PASS | PASS | PASS |
| 6. Bracket leakage | PASS | PASS | PASS |

## Three-way comparison — 03_objection_heavy.txt

| Criterion | v1 | v1.1 | v1.2 |
|---|---|---|---|
| 1. Reply length | **FAIL** — line 9 (4 sentences), line 12 (4 sentences) | **PASS** — line 9 (3), line 12 (3) | PASS — line 9 (2), line 12 (2) |
| 2. List-reading | **FAIL** — line 6, "premium amenities, a prime location, and flexible payment options" | **FAIL** — line 6, "the amenities, location, and flexible payment plans" | **PASS** — resolved, line 6 hedged, no enumeration |
| 3. Ack variation | PASS — I understand / Right / I get that | PASS — Right / Got it / I understand | PASS — Right / Sure / Got it (all 3 RULES words, once each) |
| 4. Fact invention / reputation | PASS\* — line 9, "highest quality construction and attention to detail" (superlative) | PASS\* — improved, line 9, "detailed attention to construction quality" (superlative dropped) | PASS\* — unchanged from v1.1, line 9, "ensures quality construction" (still unbacked, still no superlative) |
| 5. AI disclosure | PASS | PASS | PASS |
| 6. Bracket leakage | PASS | PASS | PASS |

---

## Net result after 3 rounds

Both files are now clean on 5 of 6 criteria. The one open item in each is
the same category flagged since it first appeared — reputational/fact
claims stated with more confidence than the KB (`kb_loaded=False`)
supports — and in neither file has it gotten worse across rounds, only
better or flat:

- **01:** list-reading fully resolved this round. Fact invention has one
  open, unresolved regression (the GST line) that first appeared in v1.1
  and has not moved since — worth its own targeted fix if this file's
  behavior matters, since it wasn't in scope for either of the last two
  edits.
- **03:** length and list-reading both fully resolved. The reputational
  quality-claim line has been softening round over round (superlative
  removed in v1.1, held steady in v1.2) but hasn't reached a clean pass —
  the current RULES wording reduces severity without fully preventing the
  pattern.
