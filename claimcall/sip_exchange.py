"""Check a synthetic claim exchange using audio recorded at each receiving endpoint."""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .reference_audit import audit_files
from .audio_probe import CASES, check_fields, extract, positional_reference

RECOGNITION_WORKER = Path(__file__).resolve().with_name("recognize_exchange.py")
SYNTHESIS_WORKER = Path(__file__).resolve().with_name("synthesize_question.py")
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
STARTUP_ENV_KEYS = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "LD_PRELOAD",
                    "LD_AUDIT", "CT2_USE_MKL", "MKL_THREADING_LAYER", "MKL_SERVICE_FORCE_INTEL",
                    "OMP_NUM_THREADS", "KMP_DUPLICATE_LIB_OK", "CLAIMCALL_WHISPER_MODEL")

QUESTION = "Hello. This is the ambulance billing office. Could you tell me the status of this claim?"


PAID_PROMPTS = {
    "question": QUESTION + " If paid, please give the amount, payment date, and payment reference.",
    "clarify-1": "Please repeat the payment reference digit by digit. Say first digit, second digit, and so on.",
    "clarify-2": "Please confirm the reference once more. Say position one and its digit, then position two, and so on.",
}


def evaluate(question, reply, capture, *, case="pending", reference_readings=()):
    if not reply.strip():
        raise ValueError("No insurer reply was transcribed")
    payment = capture(reply)
    evidence = {}
    if case == "paid":
        readings = [{"transcript": text, "value": positional_reference(text)} for text in reference_readings]
        reference = None
        if (payment.status == "paid" and len(readings) == 2
                and readings[0]["value"] == readings[1]["value"]):
            reference = readings[0]["value"]
        evidence = {"initial_capture": payment.model_dump(mode="json"), "reference_turns": readings,
                    "reference_needs_review": reference is None}
        payment = payment.model_copy(update={"reference": reference})
    mismatches = check_fields(payment, CASES[case][1])
    words = set(re.findall(r"[a-z]+", question.lower()))
    if not {"billing", "status"}.issubset(words):
        mismatches.append("caller question")
    return {"captured": payment.model_dump(mode="json"), "mismatches": mismatches, **evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--voice")
    mode.add_argument("--replay", type=Path, help="Directory containing both received WAVs")
    parser.add_argument("--case", choices=("pending", "paid"), default="pending")
    args = parser.parse_args()
    directory = Path("artifacts/sip-exchange").resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    recordings = args.replay.resolve() if args.replay else directory
    report = {"status": "failed", "case": args.case, "recordings": str(recordings), "replay": bool(args.replay)}
    # Snapshot operator settings before synthesis or the SIP subprocess can run.
    recognition_env = os.environ.copy()
    recognition_env.setdefault("CT2_USE_MKL", "0")
    stage = "input recordings"
    try:
        if args.voice:
            stage = "question synthesis"
            # Keep Piper/ONNX Runtime out of the long-lived parent, as in replay mode.
            prompts = PAID_PROMPTS if args.case == "paid" else {"question": QUESTION}
            for stem, text in prompts.items():
                original = directory / f"{stem}-original.wav"
                with (directory / "synthesis.log").open("a", encoding="utf-8") as out:
                    subprocess.run([sys.executable, str(SYNTHESIS_WORKER), "--voice", args.voice,
                                    "--text", text, "--output", str(original)],
                                   stdout=out, stderr=subprocess.STDOUT, check=True)
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(original),
                                "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", str(directory / f"{stem}.wav")],
                               check=True)
            stage = "SIP call"
            subprocess.run(["bash", "scripts/run_sip_probe.sh", f"--{args.case}", str(directory)], check=True)
        for filename in ("question-heard.wav", "reply-heard.wav"):
            if not (recordings / filename).is_file():
                raise FileNotFoundError(recordings / filename)
        stage = "recognition"
        transcripts = directory / "transcripts.json"
        log = directory / "recognition.log"
        command = [sys.executable, str(RECOGNITION_WORKER), str(recordings), str(transcripts)]
        if args.case == "paid":
            command.append("--paid")
        startup = {"command": command, "executable": sys.executable,
                   "resolved_executable": str(Path(sys.executable).resolve()),
                   "cwd": str(REPOSITORY_ROOT),
                   "environment": {key: recognition_env.get(key) for key in STARTUP_ENV_KEYS},
                   "parent_native_modules": {name: name in sys.modules for name in ("piper", "onnxruntime")}}
        startup_path = directory / "recognition-startup.json"
        startup_path.write_text(json.dumps(startup, indent=2), encoding="utf-8")
        with log.open("w", encoding="utf-8") as out:
            worker = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT,
                                    cwd=REPOSITORY_ROOT, env=recognition_env)
        startup["worker_exit_code"] = worker.returncode
        startup_path.write_text(json.dumps(startup, indent=2), encoding="utf-8")
        if worker.returncode:
            report["recognition_exit_code"] = worker.returncode
            raise RuntimeError(f"Recognition worker exited {worker.returncode}. See {log}")
        report.update(json.loads(transcripts.read_text(encoding="utf-8")))
        stage = "capture"
        report.update(evaluate(report["caller"], report["insurer"], extract, case=args.case,
                               reference_readings=report.get("reference_readings", ())))
        report["status"] = "mismatch" if report["mismatches"] else "passed"
    except Exception as exc:
        report.update(failed_stage=stage, error=str(exc))
    path = directory / "result.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['status']}: {path}", flush=True)
    if args.case == "paid" and "captured" in report:
        audit = audit_files(path, directory / "transcripts.json")
        audit_path = directory / "reference-audit.json"
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        print(f"Payment reference {audit['decision']}: {audit_path}", flush=True)
        if audit["review_required"]:
            return 1
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
