"""Exercise the launcher with real fixture audio and a stand-in speech worker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("exit_code", [0, 2])
def test_menu_preflight_without_call(tmp_path, exit_code):
    if not shutil.which("bash") or not shutil.which("ffmpeg"):
        pytest.skip("requires Bash and FFmpeg")
    filters = subprocess.check_output(["ffmpeg", "-hide_banner", "-filters"], text=True)
    if " flite " not in filters:
        pytest.skip("requires FFmpeg flite")
    root = Path(__file__).resolve().parents[1]
    for path in ("scripts/run_sip_probe.sh", "scripts/diagnose_menu_loader.py",
                 "claimcall/recognize_exchange.py", "lab/sip/menu_guard.py"):
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
        digit = {"menu-2": "two", "menu-3": "three"}[wav.parent.name]
        return [SimpleNamespace(text="For claim status press " + digit)], None
""")
    env = dict(os.environ, PROBE_PYTHON=sys.executable, PYTHONPATH=str(tmp_path),
               TEST_EXIT=str(exit_code))
    env.pop("CT2_USE_MKL", None)
    run = subprocess.run(["bash", "scripts/run_sip_probe.sh", "--menu-preflight"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == exit_code, run.stdout + run.stderr
    directory, = (tmp_path / "artifacts/sip").iterdir()
    assert not (directory / "services.log").exists()
    if exit_code:
        assert (directory / "menu-2/loader.log").is_file()
        assert not (directory / "menu-2/ready").exists()
        assert not (directory / "menu-3").exists()
    else:
        for key in ("2", "3"):
            reading = directory / f"menu-{key}/menu-transcript.json"
            assert json.loads(reading.read_text())["transcript"]
        assert '"decision": "authorized"' in run.stdout
        assert '"reason": "menu_changed"' in run.stdout
