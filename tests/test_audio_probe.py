import json
import shutil
import subprocess

import pytest
from claimcall import audio_probe as probe


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg")
def test_input_is_true_g711(tmp_path):
    path = probe.phone_fixture("paid", tmp_path)
    result = subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)])
    stream = json.loads(result)["streams"][0]
    assert (stream["codec_name"], stream["channels"], stream["sample_rate"]) == ("pcm_mulaw", 1, "8000")
    assert float(stream["duration"]) > 1


def test_invented_zero_and_wrong_amount_fail():
    paid = probe.CASES["paid"][1]
    assert probe.check_fields(paid.model_copy(update={"amount_usd": 950}), paid) == ["amount_usd"]
    pending = probe.CASES["pending"][1]
    assert probe.check_fields(pending.model_copy(update={"amount_usd": 0}), pending) == ["amount_usd"]


def test_incomplete_tool_output_retries_once(monkeypatch):
    from io import BytesIO

    def body(reason):
        capture = probe.CASES["paid"][1].model_dump_json()
        return BytesIO(json.dumps({"choices": [{"finish_reason": reason, "message": {
            "tool_calls": [{"function": {"name": "record_payment", "arguments": capture}}]
        }}]}).encode())

    responses = iter([body("length"), body("tool_calls")])
    monkeypatch.setattr(probe, "urlopen", lambda *args, **kwargs: next(responses))
    assert probe.extract("fictional test reply") == probe.CASES["paid"][1]


def test_repeated_invalid_tool_result_fails(monkeypatch):
    from io import BytesIO

    monkeypatch.setattr(probe, "urlopen", lambda *args, **kwargs: BytesIO(b'{"choices": []}'))
    with pytest.raises(ValueError, match="both attempts"):
        probe.extract("fictional test reply")


def test_repeat_corrects_dropped_digit_and_preserves_evidence():
    replies = iter(["First eight, second eight, third four, fourth one.",
                    "First digit is 8. Second digit is 8. Third digit is 4. Fourth digit is 1."])
    reference, turns = probe.verify_reference("841", lambda _: next(replies))
    assert reference == "8841"
    assert len(turns) == 2


def test_disagreement_remains_unverified():
    replies = iter(["First zero, second two.", "First zero, second three."])
    assert probe.verify_reference("1", lambda _: next(replies))[0] is None


def test_positional_reference_preserves_leading_zero_and_rejects_gaps():
    assert probe.positional_reference("First zero. Second seven.") == "07"
    assert probe.positional_reference("First eight. Third four.") is None
    assert probe.positional_reference("First eighty four.") is None
