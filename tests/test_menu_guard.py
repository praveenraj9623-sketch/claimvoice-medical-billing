import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import wave

import pytest

from lab.sip.audio import tone
from lab.sip.menu_guard import decide
from lab.sip.verify_menu import passed


@pytest.mark.parametrize("transcript,key", [
    ("For claim status, press two.", "2"), ("For claims status please press 2.", "2"),
    ("For claim status press three.", "3"),
    ("For claim status. Please press the number three.", "3"),
    ("For claim status please press the number 2.", "2"),
    ("For claim status please press the number free.", None), ("For claim status press 0.", "0"),
    ("For payments press two.", None), ("For claim status do not press two.", None),
    ("For claim status press two or three.", None), ("", None),
])
def test_only_one_explicit_matching_route_is_authorized(transcript, key):
    result = decide(transcript)
    assert result["heard_digit"] == key
    assert (result["decision"] == "authorized") == (key == "2")


@pytest.mark.parametrize("transcript,case,expected", [
    ("For claim status press two.", "menu-control", ["2"]),
    ("For claim status press three.", "menu-changed", []),
    ("For claim status, press free.", "menu-changed", []),
    ("Unclear.", "menu-changed", []),
    ("For clean status, press 2.", "menu-control", []),
])
def test_received_menu_gates_keypad(tmp_path, monkeypatch, transcript, case, expected):
    sip = Path(__file__).resolve().parents[1] / "lab/sip"
    monkeypatch.syspath_prepend(str(sip))
    monkeypatch.setitem(sys.modules, "livekit", SimpleNamespace(api=None, rtc=None))
    spec = importlib.util.spec_from_file_location("probe_runner", sip / "run.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    emitted = []

    async def keypad(*, code, digit):
        assert code == int(digit)
        emitted.append(digit)

    async def track():
        for block in (tone(440, 400), tone(1520, 400), tone(1520, 400)):
            yield SimpleNamespace(frame=SimpleNamespace(data=memoryview(block)))

    async def recognize():
        while not (tmp_path / "menu-speech.wav").exists():
            await asyncio.sleep(0.01)
        with wave.open(str(tmp_path / "menu-heard.wav")) as wav:
            assert wav.getnframes() == 1200
        with wave.open(str(tmp_path / "menu-speech.wav")) as wav:
            assert wav.getnframes() == 400
        runner.publish(tmp_path / "menu-transcript.json", {"transcript": transcript})

    async def run():
        room = SimpleNamespace(local_participant=SimpleNamespace(publish_dtmf=keypad))
        allowed, _ = await asyncio.gather(runner.check_menu(room, track(), tmp_path), recognize())
        return allowed

    assert asyncio.run(run()) == bool(expected)
    result = json.loads((tmp_path / "menu-result.json").read_text())
    assert result["sent_digits"] == emitted == expected
    assert result["transcript"] == transcript
    receiver = "CLAIMCALL_MENU_EXIT digit=[" + "".join(emitted) + "]"
    assert passed(case, result, receiver) == (result["heard_digit"] is not None)
    if result["heard_digit"] is None:
        assert (result["reason"], result["decision"]) == ("unrecognized_menu", "review_required")
    assert not passed(case, result, "")
    assert not passed(case, result, "CLAIMCALL_MENU_EXIT digit=[9]")
