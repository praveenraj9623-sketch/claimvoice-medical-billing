"""Check the lab insurer's spoken menu against its approved claim-status route."""
import argparse
import json
import os
from pathlib import Path
import re
from time import monotonic, sleep

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


def run(directory):
    os.environ.setdefault("CT2_USE_MKL", "0")
    from faster_whisper import WhisperModel

    model = WhisperModel(os.environ.get("CLAIMCALL_WHISPER_MODEL", "small.en"), device="cpu",
                         compute_type="int8", cpu_threads=4, local_files_only=True)
    (directory / "ready").touch()
    wav = directory / "menu-heard.wav"
    deadline = monotonic() + 120
    while not wav.exists():
        if monotonic() >= deadline:
            raise TimeoutError("No complete received menu WAV")
        sleep(0.1)
    segments, _ = model.transcribe(str(wav), language="en", beam_size=5, temperature=0,
                                   condition_on_previous_text=False)
    transcript = " ".join(segment.text.strip() for segment in segments).strip()
    publish(directory / "menu-decision.json", decide(transcript))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    directory = parser.parse_args().directory
    try:
        run(directory)
    except Exception as exc:
        publish(directory / "menu-decision.json", {"decision": "review_required", "reason": "recognition_error",
                                                    "error": str(exc), "expected_digit": EXPECTED, "heard_digit": None})
        raise
