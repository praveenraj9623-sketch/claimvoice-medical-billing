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
