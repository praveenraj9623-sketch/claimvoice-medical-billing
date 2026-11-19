"""Operator console for fresh calls to the private ClaimCall SIP lab."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import streamlit as st

ROOT = Path(__file__).resolve().parent
CASES = {"Paid claim": "--sip-paid", "Pending claim": "--sip-pending"}
RESULT_LINE = re.compile(r"^(?:passed|failed|mismatch|review_required): (.+/result\.json)$", re.MULTILINE)
REQUIRED_COMMANDS = ("bash", "flock", "docker", "llama-server", "ffmpeg", "curl")


def start_call(scenario):
    logs = ROOT / "artifacts" / "console"
    logs.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=logs, prefix="call-", suffix=".log", delete=False) as log:
        process = subprocess.Popen(
            ["flock", "-n", "-E", "75", str(logs / "call.lock"),
             "bash", "scripts/run_voice_probe.sh", CASES[scenario]],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "PROBE_PYTHON": sys.executable, "PYTHONUNBUFFERED": "1"},
        )
    return process, Path(log.name)


def read_progress(log):
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 16384))
        return stream.read().decode("utf-8", errors="replace")


def saved_result(progress):
    match = RESULT_LINE.search(progress)
    if not match:
        return
    path = Path(match[1]).resolve()
    if path.is_relative_to(ROOT / "artifacts" / "sip-exchange"):
        return path


def render_result(path):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.warning("The run reported a result file that could not be read.")
        return
    if result.get("status") == "review_required":
        st.warning("The phone menu needs review.")
    if menu := result.get("menu"):
        st.subheader("Phone menu")
        st.text(menu.get("transcript") or "No transcript available")
        st.write("Decision", menu.get("reason") or "No reason recorded")
        st.write("Keys sent", ", ".join(menu.get("sent_digits", [])) or "None")
    if result.get("error"):
        st.warning(f"{result.get('failed_stage', 'Call')}: {result['error']}")
    if result.get("captured"):
        st.subheader("Captured fields")
        st.json(result["captured"], expanded=1)
    for label, key, filename in (
        ("Caller", "caller", "question-heard.wav"),
        ("Insurer", "insurer", "reply-heard.wav"),
    ):
        if result.get(key):
            st.markdown(f"**{label}**")
            st.text(result[key])
        audio = path.parent / filename
        if audio.is_file():
            st.audio(str(audio), format="audio/wav")


@st.fragment(run_every=1)
def call_status(ready):
    job = st.session_state.get("claimcall_job")
    if job is None:
        st.subheader("Ready to start" if ready else "Setup required")
        if ready:
            st.write("Choose a scenario to place a fresh call to the simulated insurer.")
        return
    process, log = job
    exit_code = process.poll()
    try:
        progress = read_progress(log)
    except OSError:
        progress = "The worker log could not be read."
    if exit_code is None:
        st.info("Running SIP lab")
    elif exit_code == 75:
        st.warning("Another call started from this console is already running.")
    elif exit_code == 0:
        st.success("Call completed")
    elif re.search(r"^review_required: ", progress, re.MULTILINE):
        st.warning("Call stopped for review")
    else:
        st.error(f"Run ended with exit code {exit_code}. Check the result and worker log.")
    path = saved_result(progress)
    if path:
        render_result(path)
    with st.expander("Worker log", expanded=bool(exit_code and exit_code != 75)):
        st.code(progress or "Waiting for the first worker event.", language="text")


def main():
    st.set_page_config(page_title="ClaimCall | Live Call", layout="wide")
    st.caption("CLAIMCALL / LIVE CALL")
    st.title("Outbound claims")
    st.write("Place a fresh SIP call to the simulated insurer using a synthetic scenario.")
    setup, operations = st.columns([1, 1.75], gap="large")
    with setup:
        with st.container(border=True):
            st.subheader("Call setup")
            scenario = st.selectbox("Scenario", CASES)
            st.caption("Destination")
            st.markdown("**Asterisk test insurer** · Private SIP lab")
            missing = [name for name in REQUIRED_COMMANDS if shutil.which(name) is None]
            if missing:
                st.warning("Missing local tools: " + ", ".join(missing))
            if st.button("Start Call", type="primary", disabled=bool(missing), width="stretch"):
                job = st.session_state.get("claimcall_job")
                if job is not None and job[0].poll() is None:
                    st.warning("Wait for the current call to finish.")
                else:
                    launch(scenario)
    with operations:
        with st.container(border=True):
            st.caption("CALL STATUS")
            call_status(not missing)


def launch(scenario):
    try:
        st.session_state.claimcall_job = start_call(scenario)
    except OSError as exc:
        st.error(f"Could not launch the call worker: {exc}")


if __name__ == "__main__":
    main()
