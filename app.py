r"""Run with: .venv\Scripts\python.exe -m streamlit run app.py"""
import hashlib
import json
from uuid import uuid4
import streamlit as st
from claimvoice.claims import CLAIMS, SCENARIOS
from claimvoice.config import load_config
from claimvoice.groq_client import GroqClient, ServiceError
from claimvoice.speech import speech_html
from claimvoice.storage import save_reviewed, export_json, export_csv, transcript
from claimvoice.workflow import start, submit, respond


def main():
    st.set_page_config(page_title="ClaimVoice", page_icon="🎙️", layout="wide")
    st.title("ClaimVoice")
    st.caption("Synthetic insurer follow-up • Turn-based browser demo • No phone calls")
    st.info("You play the insurer representative. The assistant plays a medical billing assistant. Use fictional information only. No real claims, insurers or telephone numbers.")
    try:
        secrets = dict(st.secrets)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        secrets = {}
    config = load_config(secrets)
    client = GroqClient(config)
    with st.sidebar:
        st.header("Demonstration setup")
        mode = st.selectbox("Mode", ["Scripted walkthrough", "Live Groq"])
        claim_id = st.selectbox("Synthetic claim", list(CLAIMS))
        scenario = st.selectbox("Guided scenario", list(SCENARIOS))
        st.write("Respond with the fictional status and details below. Omit anything you do not know.")
        st.code(SCENARIOS[scenario], language=None)
        st.caption("Scripted mode reads Status, Reference, Documents, Next action, and Follow-up date labels separated by semicolons. Commands: human handoff / end session.")
        if mode == "Live Groq":
            st.warning("Send reply sends the conversation and selected synthetic claim to Groq. Transcribe sends recorded audio to Groq only when clicked. API usage may incur costs.")
            st.caption(f"Model: {config.model} | STT: {config.stt_model}")
            if not config.api_key:
                st.error("No Groq key configured. Add it locally or select Scripted walkthrough.")
        else:
            st.success("Deterministic script. No live AI or transcription requests.")
        if st.button("Start / reset session", type="primary"):
            st.session_state.cv = start(claim_id, mode)
            st.session_state.pop("reviewed_fingerprint", None)
            st.rerun()
        st.caption("Reset discards this session's transcript and saved records. Download first. Browser refresh may also discard state.")
    state = st.session_state.get("cv")
    if state is None:
        st.write("Select a claim and scenario, then press Start / reset session.")
        return
    if state.claim_id != claim_id or state.mode != mode:
        st.warning("Setup changed. Start / reset session to apply it.")
        return
    left, right = st.columns([3, 2])
    with right:
        st.subheader("Original claim data")
        st.json(CLAIMS[state.claim_id], expanded=True)
        st.caption("Original submitted data. Reported information appears separately below.")
        st.write(f"Human handoff flagged: {'Yes' if state.handoff else 'No'} · Session: {'Ended' if state.ended else 'Active'}")
    with left:
        st.subheader("Conversation")
        for turn in state.turns:
            with st.chat_message(turn["role"]):
                st.caption(f"Turn {turn['id']} · {'Insurer representative' if turn['role'] == 'user' else state.mode}")
                st.text(turn["content"])
        latest = next((t['content'] for t in reversed(state.turns) if t['role'] == 'assistant'), "")
        st.iframe(speech_html(latest), height=115)
        st.caption("Playback uses your browser speech service, which may use its own network service. Press Play explicitly; voice availability varies.")
        if state.error:
            st.error(state.error)
            if st.button("Retry assistant explicitly", disabled=state.ended):
                respond(state, client)
                st.rerun()
        prefix = state.session_id
        audio = st.audio_input("Record insurer reply (optional)", key=prefix + "audio", disabled=state.ended or state.mode != "Live Groq")
        text_key = prefix + "reply"
        if text_key not in st.session_state:
            st.session_state[text_key] = ""
        if st.button("Transcribe recording with Groq", disabled=state.ended or state.mode != "Live Groq" or not config.api_key or audio is None):
            audio_bytes = audio.getvalue()
            token = "audio:" + hashlib.sha256(audio_bytes).hexdigest()
            if state.reserve(token):
                try:
                    st.session_state[text_key] = client.transcribe(audio_bytes)
                    st.session_state.pop(prefix + "audio_error", None)
                except (ValueError, ServiceError) as exc:
                    st.session_state[prefix + "audio_error"] = str(exc)
            else:
                st.session_state[prefix + "audio_error"] = "This recording was already attempted. Record again to explicitly retry."
        if st.session_state.get(prefix + "audio_error"):
            st.error(st.session_state[prefix + "audio_error"])
        if st.button("Use scenario example", disabled=state.ended):
            st.session_state[text_key] = SCENARIOS[scenario]
        with st.form(prefix + "send", clear_on_submit=False):
            text = st.text_area("Edit transcription or type your insurer reply", key=text_key, max_chars=8000, disabled=state.ended)
            sent = st.form_submit_button("Send reply", disabled=state.ended or (state.mode == "Live Groq" and not config.api_key))
        if sent:
            # Form content cannot be sent twice by an incidental rerun or double-click.
            token = "reply:" + hashlib.sha256(text.encode()).hexdigest()
            try:
                submit(state, text, token, client)
            except ValueError as exc:
                state.error = str(exc)
            st.rerun()
        st.caption("Identical reply text is accepted once per session. Edit the text for a new statement; use Retry assistant after a service failure.")
    st.divider()
    review, activity = st.columns([3, 2])
    with review:
        st.subheader("Newly reported information · draft")
        st.caption("Null means unknown. Reported payments remain unverified. To correct facts, submit a corrected statement and update the draft before approving.")
        if state.draft:
            st.json(state.draft)
            fingerprint = hashlib.sha256(json.dumps(state.draft, sort_keys=True).encode()).hexdigest()
            approved = st.checkbox("I reviewed the draft and supporting transcript and approve saving this record", key=prefix + fingerprint)
            if st.button("Save reviewed follow-up", disabled=not approved):
                save_reviewed(state, approved)
                st.success("Reviewed record saved in this browser session. Download to retain it.")
        else:
            st.write("No draft yet. Supply reported facts in the conversation.")
        if state.saved:
            st.write(f"{len(state.saved)} reviewed record(s) saved in this session")
            st.download_button("Export saved JSON", export_json(state.saved), "claimvoice-followups.json", "application/json")
            st.download_button("Export saved CSV", export_csv(state.saved), "claimvoice-followups.csv", "text/csv")
        st.download_button("Download transcript", transcript(state), "claimvoice-transcript.json", "application/json")
    with activity:
        with st.expander("Tool activity", expanded=True):
            for event in state.activity:
                st.json(event, expanded=False)


if __name__ == "__main__":
    main()
