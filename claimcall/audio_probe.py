"""Run one or more synthetic insurer turns through a local CPU voice stack."""
import argparse
import json
import subprocess
import sys
import wave
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from .reference_digits import DIGITS, positional_reference


class ReportedPayment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["paid", "pending", "denied", "unknown"]
    representative: str | None
    amount_usd: Decimal | None = Field(ge=0, allow_inf_nan=False)
    payment_date: date | None
    reference: str | None


CASES = {
    "paid": (
        "This is Maria. The claim was paid. We paid eight hundred and fifty dollars "
        "on March twentieth, twenty twenty six. The payment reference is eight eight four one.",
        ReportedPayment(status="paid", representative="Maria", amount_usd=850,
                        payment_date=date(2026, 3, 20), reference="8841"),
    ),
    "pending": (
        "This is Daniel. The claim is still pending. There is no payment information yet.",
        ReportedPayment(status="pending", representative="Daniel", amount_usd=None,
                        payment_date=None, reference=None),
    ),
}


def phone_fixture(case: str, directory: Path) -> Path:
    return insurer_audio(CASES[case][0], directory, "incoming")


def insurer_audio(text: str, directory: Path, stem: str) -> Path:
    # Use a different synthesizer for the representative and the caller.
    (directory / f"{stem}.txt").write_text(text, encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        f"flite=textfile={stem}.txt:voice=slt", "-ar", "8000", "-ac", "1",
        "-c:a", "pcm_mulaw", f"{stem}.wav",
    ], cwd=directory, check=True, timeout=30)
    return directory / f"{stem}.wav"


def transcribe(recognizer, audio, *, reference_turn=False):
    options = ({"beam_size": 3, "temperature": 0.0, "condition_on_previous_text": False}
               if reference_turn else {"beam_size": 1})
    segments, _ = recognizer.transcribe(str(audio), language="en", **options)
    return " ".join(segment.text.strip() for segment in segments).strip()


def speak(voice, text, path):
    with wave.open(str(path), "wb") as wav:
        voice.synthesize_wav(text, wav)


def verify_reference(initial, repeat_turn):
    # Two consecutive independent readings must agree. Never pad an identifier.
    previous = initial
    turns = []
    for attempt in (1, 2):
        transcript = repeat_turn(attempt)
        value = positional_reference(transcript)
        turns.append({"transcript": transcript, "value": value})
        if value is not None and value == previous:
            return value, turns
        previous = value
    return None, turns


def simulator_repeat(case, attempt, directory):
    # Private representative script. Caller and parser see only transcribed audio.
    if case == "paid":
        if attempt == 1:
            text = "First digit is eight. Second digit is eight. Third digit is four. Fourth digit is one."
        else:
            text = "Position one is eight. Position two is eight. Position three is four. Position four is one."
    else:
        text = "There is no payment reference available."
    return insurer_audio(text, directory, f"repeat-{attempt}")


def extract(transcript: str) -> ReportedPayment:
    payload = {
        "model": "claimcall", "temperature": 0, "max_tokens": 256,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": "Capture facts from the insurer transcript. "
             "Use null for missing facts. Use ISO dates, USD numeric values and digits for "
             "spoken numeric references. Never invent a value. Use the record_payment tool."},
            {"role": "user", "content": transcript},
        ],
        "tools": [{"type": "function", "function": {
            "name": "record_payment", "description": "Record the representative's reported facts.",
            "parameters": ReportedPayment.model_json_schema(),
        }}],
        "tool_choice": {"type": "function", "function": {"name": "record_payment"}},
    }
    for attempt in range(2):
        request = Request("http://127.0.0.1:8080/v1/chat/completions",
                          data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=90) as response:
            body = json.load(response)
        try:
            choice = body["choices"][0]
            calls = choice["message"]["tool_calls"]
            if (choice["finish_reason"] == "length" or len(calls) != 1
                    or calls[0]["function"]["name"] != "record_payment"):
                raise ValueError("Expected one complete record_payment call")
            return ReportedPayment.model_validate_json(calls[0]["function"]["arguments"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            if attempt:
                raise ValueError("Invalid tool response on both attempts") from exc
            payload["messages"].append({"role": "user", "content": "Return one complete, valid record_payment call."})


def check_fields(actual: ReportedPayment, expected: ReportedPayment) -> list[str]:
    return [name for name in ReportedPayment.model_fields
            if getattr(actual, name) != getattr(expected, name)]


def run_case(case, directory, recognizer, voice, threads_report):
    stage = "input_audio"
    started = perf_counter()
    report = {"case": case, "status": "failed", "timings_seconds": {}, **threads_report}
    timings = report["timings_seconds"]
    try:
        incoming = phone_fixture(case, directory)
        stage = "recognition"
        before = perf_counter()
        transcript = transcribe(recognizer, incoming)
        timings["recognition"] = perf_counter() - before
        report["transcript"] = transcript
        if not transcript:
            raise ValueError("Empty transcript")
        stage = "tool_call"
        before = perf_counter()
        payment = extract(transcript)
        timings["tool_call"] = perf_counter() - before
        report["initial_capture"] = payment.model_dump(mode="json")
        if payment.status == "paid":
            stage = "reference_check"
            before = perf_counter()

            def repeat_turn(attempt):
                prompt = ("Please repeat the payment reference, one digit at a time, "
                          "saying first digit, second digit, and so on.")
                if attempt == 2:
                    prompt = ("Please read the reference again. Say position one and its digit, "
                              "then position two and its digit, and continue to the end.")
                speak(voice, prompt, directory / f"request-{attempt}.wav")
                return transcribe(recognizer, simulator_repeat(case, attempt, directory), reference_turn=True)

            reference, turns = verify_reference(payment.reference, repeat_turn)
            report["reference_turns"] = turns
            report["reference_needs_review"] = reference is None
            payment = payment.model_copy(update={"reference": reference})
            timings["reference_check_including_fixture"] = perf_counter() - before
        report["captured"] = payment.model_dump(mode="json")
        report["mismatches"] = check_fields(payment, CASES[case][1])
        stage = "synthesis"
        reply = f"I heard the claim status as {payment.status}."
        if payment.amount_usd is not None:
            reply += f" The reported amount is {payment.amount_usd} dollars."
        if payment.reference is not None and payment.status == "paid":
            reply += " The payment reference is " + ", ".join(DIGITS[int(d)] for d in payment.reference) + "."
        elif report.get("reference_needs_review"):
            reply += " The payment reference needs review."
        reply += " Is that correct?"
        before = perf_counter()
        speak(voice, reply, directory / "reply.wav")
        with wave.open(str(directory / "reply.wav"), "rb") as wav:
            if not wav.getnframes() or not any(wav.readframes(wav.getnframes())):
                raise ValueError("Empty or silent reply audio")
        timings["synthesis"] = perf_counter() - before
        report["status"] = "mismatch" if report["mismatches"] else "passed"
    except Exception as exc:
        report.update(failed_stage=stage, error=str(exc))
    timings["total_including_fixture"] = perf_counter() - started
    (directory / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", type=Path, required=True, help="Piper ONNX voice with adjacent .onnx.json")
    parser.add_argument("--whisper", default="base.en", help="Model name or downloaded local model directory")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("artifacts/voice"))
    args = parser.parse_args()
    from faster_whisper import WhisperModel
    from piper import PiperVoice

    root = args.out / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root.mkdir(parents=True)
    try:
        model = WhisperModel(args.whisper, device="cpu", compute_type="int8", cpu_threads=args.threads)
        voice = PiperVoice.load(str(args.voice))
    except Exception as exc:
        (root / "startup-error.txt").write_text(str(exc), encoding="utf-8")
        sys.exit(f"Voice model startup failed. See {root}")
    passed = True
    for case in CASES:
        directory = root / case
        directory.mkdir()
        result = run_case(case, directory, model, voice, {"whisper_cpu_threads": args.threads})
        print(f"{case}: {result['status']} ({directory / 'result.json'})", flush=True)
        passed &= result["status"] == "passed"
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
