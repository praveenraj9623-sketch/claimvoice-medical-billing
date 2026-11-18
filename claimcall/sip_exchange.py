"""Check one pending-claim exchange using audio recorded at each receiving endpoint."""
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .audio_probe import CASES, check_fields, extract, speak, transcribe

QUESTION = "Hello. This is the ambulance billing office. Could you tell me the status of this claim?"


def evaluate(question, reply, capture):
    if not reply.strip():
        raise ValueError("No insurer reply was transcribed")
    payment = capture(reply)
    mismatches = check_fields(payment, CASES["pending"][1])
    words = set(re.findall(r"[a-z]+", question.lower()))
    if not {"billing", "status"}.issubset(words):
        mismatches.append("caller question")
    return {"captured": payment.model_dump(mode="json"), "mismatches": mismatches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", required=True)
    args = parser.parse_args()
    directory = Path("artifacts/sip-exchange").resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    report = {"status": "failed"}
    stage = "question synthesis"
    try:
        from piper import PiperVoice
        speak(PiperVoice.load(args.voice), QUESTION, directory / "question-original.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(directory / "question-original.wav"),
                        "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", str(directory / "question.wav")], check=True)
        stage = "SIP call"
        subprocess.run(["bash", "scripts/run_sip_probe.sh", "--pending", str(directory)], check=True)
        stage = "recognition"
        from faster_whisper import WhisperModel
        recognizer = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
        for role, stem in (("caller", "question"), ("insurer", "reply")):
            report[role] = transcribe(recognizer, directory / f"{stem}-heard.wav")
        stage = "capture"
        report.update(evaluate(report["caller"], report["insurer"], extract))
        report["status"] = "mismatch" if report["mismatches"] else "passed"
    except Exception as exc:
        report.update(failed_stage=stage, error=str(exc))
    path = directory / "result.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['status']}: {path}", flush=True)
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
