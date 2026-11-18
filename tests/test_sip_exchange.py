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

    def crash(command, stdout, stderr):
        assert command[1:3] == ["-m", "claimcall.recognize_exchange"]
        assert command[3] == str(recordings)
        stdout.write("native library load failed")
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(subprocess, "run", crash)
    assert sip_exchange.main() == 1
    path, = tmp_path.glob("artifacts/sip-exchange/*/result.json")
    result = json.loads(path.read_text())
    assert result["failed_stage"] == "recognition"
    assert result["recognition_exit_code"] == 2
    assert (path.parent / "recognition.log").read_text() == "native library load failed"
    assert {item.read_bytes() for item in recordings.iterdir()} == {b"untouched source"}


def test_reported_mishearing_remains_a_mismatch():
    payment = CASES["pending"][1].model_copy(update={"representative": "manual"})
    result = evaluate("Ambill in Spilling Office. Could you tell me the status of this claim?",
                      "This is manual. The claim is still pending.", lambda _: payment)
    assert set(result["mismatches"]) == {"caller question", "representative"}
    assert result["captured"]["representative"] == "manual"
