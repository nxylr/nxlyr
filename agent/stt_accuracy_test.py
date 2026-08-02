"""
Indian-English STT accuracy check for the NXLYR pipeline (Week 2 gate).

Record yourself (natural Indian accent, normal pace) saying each reference
phrase below, save each as a 16 kHz mono WAV, then point this script at the
files. It sends each to Deepgram (nova-3, en-IN, smart_format) via the REST
API and reports:
  - Word Error Rate (WER) per phrase and averaged
  - Key-term recall: did the numbers / sectors / property terms survive?

The key-term recall is the number that matters most: a buyer saying
"1.5 crore for a 3 BHK in Sector 63A" is useless if the STT drops the digits.

Requires:  pip install requests

Usage:
    export DEEPGRAM_API_KEY=your_key
    python stt_accuracy_test.py p1.wav p2.wav p3.wav p4.wav p5.wav

The file order must match PHRASES below.
"""

import os
import re
import sys

import requests

DEEPGRAM_URL = (
    "https://api.deepgram.com/v1/listen"
    "?model=nova-3&language=en-IN&smart_format=true&punctuate=true"
)

# (reference sentence, key terms that MUST survive transcription)
PHRASES = [
    ("My budget is around 1.5 crore for a 3 BHK in Sector 63A.",
     ["1.5 crore", "3 bhk", "sector 63a"]),
    ("What is the carpet area and the price per square foot for the 4 BHK?",
     ["carpet area", "square foot", "4 bhk"]),
    ("We are looking for possession within 2 to 3 years, ready to move in.",
     ["possession", "2 to 3 years", "ready to move"]),
    ("Is the 30-40-30 payment plan applicable, and what about the IFMS charges?",
     ["30 40 30", "payment plan", "ifms"]),
    ("I want to shift with my family, need good school and hospital connectivity.",
     ["shift", "family", "school", "hospital"]),
]


def normalize(t):
    t = t.lower().replace("-", " ")          # 30-40-30 -> "30 40 30"
    t = re.sub(r"[^\w\s.]", " ", t)          # keep digits and decimal points
    return re.sub(r"\s+", " ", t).strip()


def wer(ref, hyp):
    r, h = normalize(ref).split(), normalize(hyp).split()
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    return d[len(r)][len(h)] / max(len(r), 1)


def transcribe(path, key):
    with open(path, "rb") as f:
        audio = f.read()
    resp = requests.post(
        DEEPGRAM_URL,
        headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
        data=audio,
        timeout=60,
    )
    resp.raise_for_status()
    j = resp.json()
    return j["results"]["channels"][0]["alternatives"][0]["transcript"]


def main():
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        sys.exit("Set DEEPGRAM_API_KEY first.")
    files = sys.argv[1:]
    if len(files) != len(PHRASES):
        sys.exit(f"Provide {len(PHRASES)} wav files, in the order of PHRASES.")

    total_wer = 0.0
    total_terms = hit_terms = 0
    print()
    for (ref, terms), path in zip(PHRASES, files):
        try:
            hyp = transcribe(path, key)
        except Exception as e:
            print(f"ERROR on {path}: {e}\n" + "-" * 72)
            continue
        w = wer(ref, hyp)
        total_wer += w
        nhyp = normalize(hyp)
        missed = [t for t in terms if normalize(t) not in nhyp]
        total_terms += len(terms)
        hit_terms += len(terms) - len(missed)
        print(f"REF : {ref}")
        print(f"HYP : {hyp}")
        print(f"WER : {w * 100:.1f}%    key-terms missed: {missed or 'none'}")
        print("-" * 72)

    n = len(PHRASES)
    print(f"\nAverage WER      : {total_wer / n * 100:.1f}%")
    if total_terms:
        print(f"Key-term recall  : {hit_terms}/{total_terms} "
              f"({hit_terms / total_terms * 100:.0f}%)")
    print(
        "\nGate: aim for WER < ~15% and 100% key-term recall on the numbers "
        "(crore, BHK, sector). Those misses are the ones that break a real "
        "qualification call.\n"
    )


if __name__ == "__main__":
    main()
