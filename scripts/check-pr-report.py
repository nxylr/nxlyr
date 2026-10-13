#!/usr/bin/env python3
"""Fail if a PR body is missing any of the 10 required headings or leaves one empty.

Usage:
  python3 scripts/check-pr-report.py < body.md
  PR_BODY="..." python3 scripts/check-pr-report.py
"""
import os
import re
import sys

REQUIRED = [
    "Summary",
    "What changed",
    "How it fits",
    "Tools and skills used",
    "Evidence",
    "Cross-model review",
    "Shortcuts and debt",
    "Risk and rollback",
    "Memory updates",
    "Not verified",
]


def main() -> int:
    body = os.environ.get("PR_BODY")
    if body is None:
        body = sys.stdin.read()

    # strip HTML comments (template guidance) before judging content
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)

    parts = re.split(r"^##\s+(.+?)\s*$", body, flags=re.M)
    # parts = [preamble, h1, text1, h2, text2, ...]
    sections = {}
    for i in range(1, len(parts) - 1, 2):
        sections[parts[i].strip().lower()] = parts[i + 1].strip()

    problems = []
    for name in REQUIRED:
        key = name.lower()
        if key not in sections:
            problems.append(f"missing heading: ## {name}")
        elif len(sections[key]) < 3:
            problems.append(f"empty section: ## {name}")

    if problems:
        print("PR report check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("PR report check passed: all 10 sections present and non-empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
