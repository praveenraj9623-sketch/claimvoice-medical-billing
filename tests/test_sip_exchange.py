import pytest

from claimcall.audio_probe import CASES
from claimcall.sip_exchange import evaluate


def test_capture_only_sees_the_received_reply():
    reply = "Daniel here. The claim is pending."
    inputs = []

    def capture(text):
        inputs.append(text)
        return CASES["pending"][1]

    result = evaluate("Calling from billing. What is the status?", reply, capture)
    assert inputs == [reply]
    assert result["mismatches"] == []
    assert result["captured"]["reference"] is None


def test_missing_outbound_speech_and_invented_payment_fail():
    def capture(text):
        return CASES["pending"][1].model_copy(update={"reference": "8841"})

    result = evaluate("", "The claim is pending.", capture)
    assert set(result["mismatches"]) == {"reference", "caller question"}


def test_missing_reply_stops_before_extraction():
    with pytest.raises(ValueError, match="No insurer reply"):
        evaluate("billing status", " ", lambda _: pytest.fail("Unexpected model call"))


def test_replay_native_worker_failure_is_reported(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    from claimcall import sip_exchange

    monkeypatch.chdir(tmp_path)
    recordings = tmp_path / "original"
    recordings.mkdir()
    for name in ("question-heard.wav", "reply-heard.wav"):
        (recordings / name).write_bytes(b"untouched source")
    monkeypatch.setattr(sys, "argv", ["sip_exchange", "--replay", str(recordings)])

    def crash(command, stdout, stderr, cwd, env):
        assert command[:2] == [sys.executable, str(sip_exchange.RECOGNITION_WORKER)]
        assert command[2] == str(recordings)
        assert cwd == sip_exchange.REPOSITORY_ROOT
        assert env["CT2_USE_MKL"] == "0"
        stdout.write("native library load failed")
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(subprocess, "run", crash)
    assert sip_exchange.main() == 1
    path, = tmp_path.glob("artifacts/sip-exchange/*/result.json")
    result = json.loads(path.read_text())
    assert result["failed_stage"] == "recognition"
    assert result["recognition_exit_code"] == 2
    assert (path.parent / "recognition.log").read_text() == "native library load failed"
    startup = json.loads((path.parent / "recognition-startup.json").read_text())
    assert startup["worker_exit_code"] == 2
    assert startup["executable"] == sys.executable
    assert {item.read_bytes() for item in recordings.iterdir()} == {b"untouched source"}


def test_reported_mishearing_remains_a_mismatch():
    payment = CASES["pending"][1].model_copy(update={"representative": "manual"})
    result = evaluate("Ambill in Spilling Office. Could you tell me the status of this claim?",
                      "This is manual. The claim is still pending.", lambda _: payment)
    assert set(result["mismatches"]) == {"caller question", "representative"}
    assert result["captured"]["representative"] == "manual"


def test_worker_launches_from_outside_checkout(tmp_path, monkeypatch):
    import json
    import sys
    from claimcall import sip_exchange

    # Only the speech model is stubbed. The child interpreter, CLI and I/O are real.
    (tmp_path / "faster_whisper.py").write_text(
        "from pathlib import Path\n"
        "from types import SimpleNamespace\n"
        "class WhisperModel:\n"
        "    def __init__(self, *args, **kwargs): pass\n"
        "    def transcribe(self, path, **kwargs):\n"
        "        return [SimpleNamespace(text=Path(path).read_text())], None\n"
    )
    (tmp_path / "question-heard.wav").write_text("Billing office asking for claim status.")
    (tmp_path / "reply-heard.wav").write_text("This is Daniel. The claim is pending.")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    monkeypatch.delenv("CLAIMCALL_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(sys, "argv", ["sip_exchange", "--replay", str(tmp_path)])
    monkeypatch.setattr(sip_exchange, "extract", lambda _: CASES["pending"][1])
    assert sip_exchange.main() == 0
    path, = tmp_path.glob("artifacts/sip-exchange/*/result.json")
    result = json.loads(path.read_text())
    assert result["model"] == "small.en"
    assert result["insurer"] == "This is Daniel. The claim is pending."
    assert result["mismatches"] == []


def test_fresh_startup_keeps_synthesis_out_of_parent_and_freezes_worker_env(tmp_path, monkeypatch):
    import json
    import os
    import shutil
    import subprocess
    import sys
    from claimcall import sip_exchange

    # Use real child interpreters and WAV synthesis I/O, with only speech engines stubbed.
    (tmp_path / "piper.py").write_text(
        "class PiperVoice:\n"
        "    @classmethod\n"
        "    def load(cls, path): return cls()\n"
        "    def synthesize_wav(self, text, wav):\n"
        "        wav.setparams((1, 2, 8000, 0, 'NONE', ''))\n"
        "        wav.writeframes(b'\\x01\\x00' * 800)\n"
    )
    (tmp_path / "faster_whisper.py").write_text(
        "from pathlib import Path\n"
        "from types import SimpleNamespace\n"
        "class WhisperModel:\n"
        "    def __init__(self, *args, **kwargs): pass\n"
        "    def transcribe(self, path, **kwargs):\n"
        "        return [SimpleNamespace(text=Path(path).read_text())], None\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/operator/library/path")
    monkeypatch.setenv("CT2_USE_MKL", "1")
    monkeypatch.setattr(sys, "argv", ["sip_exchange", "--voice", str(tmp_path / "voice with spaces.onnx")])
    monkeypatch.setattr(sip_exchange, "extract", lambda _: CASES["pending"][1])
    real_run = subprocess.run
    parent_native_before = {name: name in sys.modules for name in ("piper", "onnxruntime")}

    def run(command, *args, **kwargs):
        if command[0] == "ffmpeg":
            shutil.copyfile(command[command.index("-i") + 1], command[-1])
            return subprocess.CompletedProcess(command, 0)
        if command[:2] == ["bash", "scripts/run_sip_probe.sh"]:
            directory = Path(command[-1])
            (directory / "question-heard.wav").write_text("Billing office asking for claim status.")
            (directory / "reply-heard.wav").write_text("This is Daniel. The claim is pending.")
            monkeypatch.chdir(tmp_path.parent)
            os.environ["LD_LIBRARY_PATH"] = "/changed/after/synthesis"
            os.environ["CT2_USE_MKL"] = "0"
            return subprocess.CompletedProcess(command, 0)
        return real_run(command, *args, **kwargs)

    from pathlib import Path
    monkeypatch.setattr(subprocess, "run", run)
    assert sip_exchange.main() == 0
    path, = tmp_path.glob("artifacts/sip-exchange/*/result.json")
    startup = json.loads((path.parent / "recognition-startup.json").read_text())
    assert startup["environment"]["LD_LIBRARY_PATH"] == "/operator/library/path"
    assert startup["environment"]["CT2_USE_MKL"] == "1"
    assert startup["cwd"] == str(sip_exchange.REPOSITORY_ROOT)
    assert startup["parent_native_modules"] == parent_native_before
    assert startup["worker_exit_code"] == 0
    assert (path.parent / "question-original.wav").stat().st_size > 44
    assert json.loads(path.read_text())["mismatches"] == []


def test_synthesis_worker_failure_stops_before_sip(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    from claimcall import sip_exchange

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["sip_exchange", "--voice", "missing.onnx"])

    def fail(command, stdout, stderr, check):
        assert command[:2] == [sys.executable, str(sip_exchange.SYNTHESIS_WORKER)]
        stdout.write("Piper could not load the voice")
        raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(subprocess, "run", fail)
    assert sip_exchange.main() == 1
    path, = tmp_path.glob("artifacts/sip-exchange/*/result.json")
    assert json.loads(path.read_text())["failed_stage"] == "question synthesis"
    assert (path.parent / "synthesis.log").read_text() == "Piper could not load the voice"


@pytest.mark.parametrize(("readings", "reference", "review"), [
    (["Position one is eight, position two is eight, position three is four, position four is one.",
      "First digit is eight. Second digit is eight. Third digit is four. Fourth digit is one."], "8841", False),
    (["First digit is one.", "First digit is two."], None, True),
    (["I couldn't hear you.", "I couldn't hear you."], None, True),
    ([], None, True),
])
def test_paid_reference_requires_agreeing_numbered_readings(readings, reference, review):
    initial = CASES["paid"][1].model_copy(update={"reference": "841"})
    result = evaluate("Billing office asking for status.", "Reported payment.", lambda _: initial,
                      case="paid", reference_readings=readings)
    assert result["initial_capture"]["reference"] == "841"
    assert result["captured"]["reference"] == reference
    assert result["reference_needs_review"] is review
    assert result["mismatches"] == (["reference"] if review else [])


def test_paid_replay_decodes_the_two_received_reference_wavs(tmp_path, monkeypatch):
    import json
    import sys
    from claimcall import sip_exchange

    (tmp_path / "faster_whisper.py").write_text(
        "from pathlib import Path\n"
        "from types import SimpleNamespace\n"
        "class WhisperModel:\n"
        "    def __init__(self, *args, **kwargs): pass\n"
        "    def transcribe(self, path, **kwargs):\n"
        "        return [SimpleNamespace(text=Path(path).read_text())], None\n"
    )
    recordings = {
        "question": "The billing office is asking for claim status.",
        "reply": "Maria here. Paid 850 dollars on March 20, 2026. Reference 841.",
        "reference-1": "First digit is eight. Second digit is eight. Third digit is four. Fourth digit is one.",
        "reference-2": "Position one is eight, position two is eight, position three is four, position four is one.",
    }
    for name, text in recordings.items():
        (tmp_path / f"{name}-heard.wav").write_text(text)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["sip_exchange", "--replay", str(tmp_path), "--case", "paid"])

    def capture(reply):
        assert reply == recordings["reply"]
        return CASES["paid"][1].model_copy(update={"reference": "841"})

    monkeypatch.setattr(sip_exchange, "extract", capture)
    assert sip_exchange.main() == 0
    path, = tmp_path.glob("artifacts/sip-exchange/*/result.json")
    report = json.loads(path.read_text())
    assert report["initial_capture"]["reference"] == "841"
    assert report["captured"]["reference"] == "8841"
    assert [turn["value"] for turn in report["reference_turns"]] == ["8841", "8841"]
    audit = json.loads(path.with_name("reference-audit.json").read_text())
    assert audit["decision"] == "verified"
    assert audit["evidence"][1]["quote"] == recordings["reference-2"]
