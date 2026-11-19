"""Exercise the launcher with real fixture audio and a stand-in speech worker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import pytest

from lab.sip.audio import tone


@pytest.mark.parametrize("mode,reading,exit_code", [
    ("--menu-preflight", "", 0), ("--menu-preflight", "", 2),
    ("--menu-replay-control", "For claim status press two.", 0),
    ("--menu-replay-control", "For clean status press two.", 1),
    ("--menu-replay-changed", "For claim status press three.", 0),
])
def test_menu_recognition_without_call(tmp_path, mode, reading, exit_code):
    if not shutil.which("bash") or not shutil.which("ffmpeg"):
        pytest.skip("requires Bash and FFmpeg")
    filters = subprocess.check_output(["ffmpeg", "-hide_banner", "-filters"], text=True)
    if " flite " not in filters:
        pytest.skip("requires FFmpeg flite")
    root = Path(__file__).resolve().parents[1]
    for path in ("scripts/run_sip_probe.sh", "scripts/diagnose_menu_loader.py",
                 "claimcall/recognize_exchange.py", "lab/sip/menu_guard.py", "lab/sip/render_menu.sh",
                 "lab/sip/audio.py"):
        dst = tmp_path / path
        dst.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(root / path, dst)
    dist = tmp_path / "ctranslate2-1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Name: ctranslate2\nVersion: 1\n")
    (tmp_path / "faster_whisper.py").write_text("""
import os
from pathlib import Path
from types import SimpleNamespace
assert Path.cwd() == Path(__file__).parent
assert os.environ["CT2_USE_MKL"] == "0"
if os.environ["TEST_EXIT"] == "2":
    os._exit(2)
class WhisperModel:
    def __init__(self, name, **kwargs):
        assert kwargs["local_files_only"] is True
    def transcribe(self, path, **kwargs):
        wav = Path(path)
        assert wav.read_bytes()[:4] == b"RIFF"
        if os.environ["TEST_READING"]:
            assert wav.name == "menu-speech.wav"
            return [SimpleNamespace(text=os.environ["TEST_READING"])], None
        digit = {"menu-2": "two", "menu-3": "three"}[wav.parent.name]
        return [SimpleNamespace(text="For claim status press " + digit)], None
""")
    env = dict(os.environ, PROBE_PYTHON=sys.executable, PYTHONPATH=str(tmp_path),
               TEST_EXIT=str(exit_code), TEST_READING=reading)
    env.pop("CT2_USE_MKL", None)
    command = ["bash", "scripts/run_sip_probe.sh", mode]
    if reading:
        source = tmp_path / "original.wav"
        speech = tone(440, 800)
        with wave.open(str(source), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", ""))
            wav.writeframes(bytes(800 * 8) + speech + tone(1520, 800))
        original = source.read_bytes()
        command.append(str(source))
    run = subprocess.run(command,
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == exit_code, run.stdout + run.stderr
    directory, = (tmp_path / "artifacts/sip").iterdir()
    assert not (directory / "services.log").exists()
    if reading:
        assert source.read_bytes() == original
        with wave.open(str(directory / "menu/menu-speech.wav")) as wav:
            assert wav.readframes(wav.getnframes()) == bytes(800 * 3) + speech
        assert json.loads((directory / "menu/menu-transcript.json").read_text())["transcript"] == reading
        if exit_code:
            assert '"reason": "unrecognized_menu"' in run.stdout
    elif exit_code:
        assert (directory / "menu-2/loader.log").is_file()
        assert not (directory / "menu-2/ready").exists()
        assert not (directory / "menu-3").exists()
    else:
        for key in ("2", "3"):
            reading = directory / f"menu-{key}/menu-transcript.json"
            assert json.loads(reading.read_text())["transcript"]
        assert '"decision": "authorized"' in run.stdout
        assert '"reason": "menu_changed"' in run.stdout
