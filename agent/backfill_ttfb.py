"""
One-time backfill: recover STT/LLM/TTS TTFB columns in week2_latency.csv from
week2_latency_events.log — for data collected before the regex-parsing fix.

roundtrip_ms and user_turn_secs were already correct and are left untouched.
This only fills in the three columns that were blank.

v2: matches log entries to CSV rows by POSITION in the file, not by the
printed "[turn N]" label. The label is NOT a unique key across multiple
`python test_pipeline.py` invocations — each run restarts its own turn
counter at 1 — so if you appended several runs into one CSV (as the Week 2
protocol asks you to), label-based matching silently stamps one run's
values onto every row sharing that label. Both the CSV and the log are
written strictly in chronological append order within a single continuous
session of runs, so matching the i-th log block to the i-th CSV row is
correct regardless of label collisions.

Usage:
    python backfill_ttfb.py
    python backfill_ttfb.py week2_latency.csv week2_latency_events.log
"""

import csv
import re
import shutil
import sys

_LOG_LINE_RE = re.compile(r"^\[turn (?P<turn>\d+)\]\s*(?P<proc>.+?):\s*TTFB\s+(?P<val>[\d.]+)s\s*$")
_LOG_BLOCK_RE = re.compile(r"^\[turn (?P<turn>\d+)\]")


def _classify(name: str):
    # Check specific provider names first (unambiguous). Falling back to the
    # generic stt/llm/tts abbreviations is collision-prone: "DeepgramSTTService"
    # and "ElevenLabsTTSService" each accidentally contain "tts"/"stt" as a
    # substring where the abbreviation runs into "...Service".
    n = (name or "").lower()
    if "deepgram" in n:
        return "stt_ttfb_ms"
    if "openai" in n or "gpt" in n:
        return "llm_ttfb_ms"
    if "elevenlabs" in n:
        return "tts_ttfb_ms"
    if "stt" in n:
        return "stt_ttfb_ms"
    if "llm" in n:
        return "llm_ttfb_ms"
    if "tts" in n:
        return "tts_ttfb_ms"
    return None


def parse_log_blocks(log_path):
    """Group log lines into ordered blocks by contiguous '[turn N]' label,
    where ANY change in the label (including a reset like 20 -> 1) starts a
    new block. Returns an ordered list of {col: value_ms} dicts, one per
    block, in true chronological file order — this is the sequence that
    matters, not the label itself."""
    blocks = []
    current_label = None
    current = None

    with open(log_path) as fh:
        for raw_line in fh:
            line = raw_line.strip()
            bm = _LOG_BLOCK_RE.match(line)
            if not bm:
                continue
            label = bm.group("turn")
            if label != current_label:
                if current is not None:
                    blocks.append(current)
                current = {}
                current_label = label

            m = _LOG_LINE_RE.match(line)
            if m:
                col = _classify(m.group("proc"))
                if col:
                    current[col] = round(float(m.group("val")) * 1000.0, 1)

    if current is not None:
        blocks.append(current)
    return blocks


def backfill(csv_path, blocks):
    with open(csv_path) as fh:
        rows = list(csv.DictReader(fh))
    fields = ["turn", "stt_ttfb_ms", "llm_ttfb_ms", "tts_ttfb_ms", "roundtrip_ms", "user_turn_secs"]

    if len(rows) != len(blocks):
        print(
            f"  !  WARNING: {len(rows)} CSV rows but {len(blocks)} log blocks — "
            f"counts don't match, so position-based mapping may be off by however "
            f"many rows differ. Check for partial/interrupted runs before trusting "
            f"the result."
        )

    filled = 0
    n = min(len(rows), len(blocks))
    for i in range(n):
        row, block = rows[i], blocks[i]
        for col in ("stt_ttfb_ms", "llm_ttfb_ms", "tts_ttfb_ms"):
            if (row.get(col, "") in ("", None)) and col in block:
                row[col] = block[col]
                filled += 1

    backup = csv_path + ".bak"
    shutil.copy(csv_path, backup)
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})

    return filled, len(rows), backup


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "week2_latency.csv"
    log_path = sys.argv[2] if len(sys.argv) > 2 else "week2_latency_events.log"

    try:
        blocks = parse_log_blocks(log_path)
    except FileNotFoundError:
        sys.exit(f"No log file at {log_path}.")

    if not blocks:
        sys.exit(f"No '[turn N]' blocks found in {log_path}.")

    try:
        filled, n_rows, backup = backfill(csv_path, blocks)
    except FileNotFoundError:
        sys.exit(f"No CSV at {csv_path}.")

    print(f"\nFound {len(blocks)} chronological turn-blocks in {log_path}.")
    print(f"Filled {filled} blank cells across {n_rows} CSV rows (matched by position).")
    print(f"Original backed up to {backup}.")
    print(f"\nNow run:  python analyze_week2.py {csv_path}\n")


if __name__ == "__main__":
    main()
