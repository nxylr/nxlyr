"""
Summarise week2_latency.csv into a pass/fail scorecard.

    python analyze_week2.py                 # reads week2_latency.csv
    python analyze_week2.py somefile.csv

Gate logic: a stage PASSES if its p95 is within the TRD §5 target.
We gate on p95 (worst-case), not the average, because in a live phone
call the slow turns are what the buyer actually notices.
"""

import csv
import sys

# Targets in milliseconds, straight from TRD §5.
THRESHOLDS = {
    "stt_ttfb_ms": 200,
    "llm_ttfb_ms": 400,
    "tts_ttfb_ms": 200,
    "roundtrip_ms": 800,
}


def pctl(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def load(path):
    cols = {k: [] for k in THRESHOLDS}
    n = 0
    with open(path) as fh:
        for row in csv.DictReader(fh):
            n += 1
            for k in THRESHOLDS:
                v = row.get(k, "")
                if v not in ("", None):
                    try:
                        cols[k].append(float(v))
                    except ValueError:
                        pass
    return n, cols


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "week2_latency.csv"
    try:
        n, cols = load(path)
    except FileNotFoundError:
        sys.exit(f"No file at {path}. Run the pipeline with the observer first.")

    print(f"\nWeek 2 latency scorecard  —  {n} turns recorded  ({path})\n")
    if n < 20:
        print(f"  !  Only {n} turns. Target is 20+ for a stable p95 — keep testing.\n")

    header = (f"{'stage':<14}{'count':>6}{'p50':>9}{'p95':>9}"
              f"{'max':>9}{'target':>9}  verdict")
    print(header)
    print("-" * len(header))

    all_pass = True
    for k, tgt in THRESHOLDS.items():
        v = cols[k]
        if not v:
            print(f"{k:<14}{0:>6}{'-':>9}{'-':>9}{'-':>9}{tgt:>9}  NO DATA")
            all_pass = False
            continue
        p50, p95, mx = pctl(v, 50), pctl(v, 95), max(v)
        ok = p95 <= tgt
        all_pass = all_pass and ok
        print(f"{k:<14}{len(v):>6}{p50:>9.1f}{p95:>9.1f}"
              f"{mx:>9.1f}{tgt:>9}  {'PASS' if ok else 'FAIL'}")

    print()
    print("Gate = p95 within target. STT 'NO DATA' can be normal (STT TTFB is")
    print("sparse); the round-trip number is the authoritative one.")
    print()
    if all_pass:
        print("RESULT: PASS — latency gate met. See exit criteria in the runbook.")
    else:
        print("RESULT: FAIL — see the decision table in WEEK2_TEST_RUNBOOK.md.")
    print()
    if cols["roundtrip_ms"]:
        rt95 = pctl(cols["roundtrip_ms"], 95)
        if 760 <= rt95 <= 800:
            print(f"  Heads-up: round-trip p95 is {rt95:.0f}ms locally. Exotel adds")
            print("  ~180-250ms in Week 3 (C-19), so this leaves little headroom.\n")


if __name__ == "__main__":
    main()
