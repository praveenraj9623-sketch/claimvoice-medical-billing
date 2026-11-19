"""Check the lab insurer's spoken menu against its approved claim-status route."""
import argparse
import json
from pathlib import Path
import re

EXPECTED = "2"
DIGITS = "zero one two three four five six seven eight nine".split()


def decide(transcript):
    # Only authorize a single, affirmative claim-status instruction.
    text = re.sub(r"[.,?!]", " ", transcript.casefold())
    match = re.fullmatch(r"for claims? status (?:please )?press ([a-z]+|[0-9])", " ".join(text.split()))
    digit = None
    if match:
        word = match.group(1)
        digit = str(DIGITS.index(word)) if word in DIGITS else word if word.isdecimal() else None
    reason = "unrecognized_menu"
    if digit is not None:
        reason = "menu_matches" if digit == EXPECTED else "menu_changed"
    return {"transcript": transcript, "expected_digit": EXPECTED, "heard_digit": digit,
            "decision": "authorized" if digit == EXPECTED else "review_required",
            "reason": reason}


def publish(path, value):
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, indent=2), encoding="utf-8")
    pending.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check an offline menu preflight transcript")
    parser.add_argument("reading", type=Path)
    parser.add_argument("--expect-digit", required=True, choices=("2", "3"))
    args = parser.parse_args()
    decision = decide(json.loads(args.reading.read_text())["transcript"])
    print(json.dumps(decision, indent=2))
    raise SystemExit(int(decision["heard_digit"] != args.expect_digit))
