r"""Run with: .venv\Scripts\python.exe -m streamlit run app.py"""
import hashlib
import json
import streamlit as st
from claimvoice.claims import CLAIMS, SCENARIOS
from claimvoice.config import load_config
from claimvoice.groq_client import GroqClient, ServiceError
from claimvoice.speech import speech_html
from claimvoice.storage import save_reviewed, export_json, export_csv, transcript
from claimvoice.workflow import start, submit, respond
from claimvoice import presentation as ui


def setup(config):
    with st.sidebar:
        ui.brand()
        st.header("Session setup")
        mode = st.selectbox("Mode", ["Scripted walkthrough", "Live Groq"])
        claim_id = st.selectbox("Synthetic claim", list(CLAIMS))
        scenario = st.selectbox("Guided scenario", list(SCENARIOS))
        if mode == "Live Groq":
            if config.api_key:
                st.caption("Groq key configured · verified only by a successful request")
            else:
                st.error("No Groq key configured. Add it locally or select Scripted walkthrough.")
            st.caption("Send sends conversation and selected claim to Groq. Transcribe sends audio only when clicked. API usage may incur costs.")
        else:
            st.caption("Scripted mode · no live AI or transcription requests")
        st.button("Start / reset session", type="primary", use_container_width=True, on_click=reset_session, args=(claim_id, mode))
        st.caption("Download first: reset or refresh may discard this session and saved records.")
        with st.expander("Scenario guide"):
            st.write("You play the insurer representative. Reply with fictional details you know; omit unknown facts.")
            st.write(SCENARIOS[scenario])
            st.caption("Scripted labels: Status; Reference; Documents; Next action; Follow-up date. Commands: human handoff / end session.")
        with st.expander("Models & privacy"):
            st.caption(f"Text: {config.model}\n\nSpeech recognition: {config.stt_model}")
            st.caption("Playback uses the browser speech service, which may use a vendor network service. No telephone calls. Use fictional data only.")
        st.markdown('<div class="cv-footer">A synthetic workflow demonstration.<br>AI drafts. People review and decide.</div>', unsafe_allow_html=True)
    return mode, claim_id, scenario


def reset_session(claim_id, mode):
    st.session_state.cv = start(claim_id, mode)
    st.session_state.pop("reviewed_fingerprint", None)


def conversation(state, client, config, scenario):
    left, right = st.columns([2.05, 1], gap="large")
    prefix = state.session_id
    with right:
        with st.container(border=True):
            ui.section("Claim at a glance", "Original submitted information")
            claim = CLAIMS[state.claim_id]
            st.markdown(ui.field_list([
                ("Patient", claim["patient"]), ("Insurer", claim["insurer"]),
                ("Service date", claim["service_date"]), ("Service", claim["service"]),
                ("Original status", claim["original_status"]),
            ]), unsafe_allow_html=True)
            with st.expander("View original JSON"):
                st.json(claim)
        with st.container(border=True):
            ui.section("Your role in this demo")
            st.write("Play the insurer representative. The assistant asks for claim status, references, documents and next steps.")
            st.caption("This is a turn-based browser conversation. No real insurers are contacted.")
            if state.handoff:
                st.warning("Human review flagged · no actual transfer")
            if state.ended:
                st.info("Session ended. You can still review and export.")
    with left:
        ui.section("Conversation", "Reported facts stay linked to the representative’s transcript.")
        with st.container(height=240 if len(state.turns) == 1 else 360, border=False):
            for turn in state.turns:
                with st.chat_message(turn["role"], avatar="🎧" if turn["role"] == "assistant" else "👤"):
                    st.caption(f"Turn {turn['id']} · {'Insurer representative' if turn['role'] == 'user' else 'Billing assistant · ' + state.mode}")
                    st.text(turn["content"])
        latest = next((t['content'] for t in reversed(state.turns) if t['role'] == 'assistant'), "")
        st.iframe(speech_html(latest), height=108)
        if state.error:
            st.error(state.error)
            if st.button("Retry assistant explicitly", disabled=state.ended):
                with st.spinner("Retrying assistant…"):
                    respond(state, client)
                st.rerun()
        text_key = prefix + "reply"
        if text_key not in st.session_state:
            st.session_state[text_key] = ""
        with st.container(border=True):
            ui.section("Representative reply", "Type a reply, or record and transcribe before sending.")
            typed, recorded = st.tabs(["Type a reply", "Record audio"])
            # Audio processing runs before the text widget is instantiated so a
            # transcription can populate its existing session-state value safely.
            with recorded:
                audio = st.audio_input("Record insurer reply (optional)", key=prefix + "audio", disabled=state.ended or state.mode != "Live Groq")
                if state.mode != "Live Groq":
                    st.caption("Recording and transcription are available in Live Groq mode. Scripted mode uses typed scenario text.")
                if st.button("Transcribe recording with Groq", disabled=state.ended or state.mode != "Live Groq" or not config.api_key or audio is None):
                    audio_bytes = audio.getvalue()
                    token = "audio:" + hashlib.sha256(audio_bytes).hexdigest()
                    if state.reserve(token):
                        try:
                            with st.spinner("Transcribing recording…"):
                                st.session_state[text_key] = client.transcribe(audio_bytes)
                            st.session_state.pop(prefix + "audio_error", None)
                        except (ValueError, ServiceError) as exc:
                            st.session_state[prefix + "audio_error"] = str(exc)
                    else:
                        st.session_state[prefix + "audio_error"] = "This recording was already attempted. Record again to explicitly retry."
                if st.session_state.get(prefix + "audio_error"):
                    st.error(st.session_state[prefix + "audio_error"])
                st.caption("Transcription appears in Type a reply. Review and edit it before sending. Recording uploads to this app; transcription sends audio to Groq only when clicked.")
            with typed:
                if st.button("Use scenario example", disabled=state.ended):
                    st.session_state[text_key] = SCENARIOS[scenario]
                with st.form(prefix + "send", clear_on_submit=False, border=False):
                    text = st.text_area("Edit transcription or type your insurer reply", key=text_key, max_chars=8000, height=125, disabled=state.ended, placeholder="Status: pending processing; Reference: DEMO-P17; Next action: check status again")
                    sent = st.form_submit_button("Send reply", type="primary", use_container_width=True, disabled=state.ended or (state.mode == "Live Groq" and not config.api_key))
                if sent:
                    token = "reply:" + hashlib.sha256(text.encode()).hexdigest()
                    try:
                        with st.spinner("Preparing follow-up draft…"):
                            submit(state, text, token, client)
                    except ValueError as exc:
                        state.error = str(exc)
                    st.rerun()
                st.caption("Duplicate replies are blocked. New facts require new text; service failures use explicit Retry.")
        if state.draft:
            st.info("Draft ready. Open Review & export to check the evidence and approve a save.")


def review(state):
    prefix = state.session_id
    ui.section("Review the follow-up", "Compare each reported fact with the supporting transcript before saving.")
    st.markdown('<div class="cv-note">Not reported means unknown. A reported payment is unverified. Correct facts through a new representative reply before approving.</div>', unsafe_allow_html=True)
    if state.draft:
        draft = state.draft
        facts, evidence = st.columns([1.1, 1], gap="large")
        with facts:
            with st.container(border=True):
                ui.section("Newly reported information", "Draft · not submitted or independently verified")
                st.markdown(ui.field_list([
                    ("Reported status", draft.get("reported_status")),
                    ("Reference number", draft.get("reference_number")),
                    ("Next action", draft.get("next_action")),
                    ("Follow-up date", draft.get("follow_up_date")),
                    ("Requested documents", draft.get("requested_documents")),
                ], draft=True), unsafe_allow_html=True)
                with st.expander("View complete draft JSON"):
                    st.json(draft)
        with evidence:
            with st.container(border=True):
                ui.section("Supporting transcript", "Check what the representative actually said.")
                for turn in draft.get("supporting_transcript_turns", []):
                    st.caption(f"Representative · Turn {turn['id']}")
                    st.text(turn["content"])
                if not draft.get("supporting_transcript_turns"):
                    st.caption("No supporting transcript available. Review the conversation before saving.")
        fingerprint = hashlib.sha256(json.dumps(draft, sort_keys=True).encode()).hexdigest()
        with st.container(border=True):
            approved = st.checkbox("I reviewed the draft and supporting transcript and approve saving this record", key=prefix + fingerprint)
            if st.button("Save reviewed follow-up", type="primary", disabled=not approved):
                save_reviewed(state, approved)
                st.success("Reviewed record saved in this browser session. Download to retain it.")
    else:
        st.info("No draft yet. Use a scenario example or supply reported facts in the Conversation tab.")
    st.divider()
    ui.section("Download your work", f"{len(state.saved)} reviewed record(s) saved in this session. Downloads retain your work outside the browser session.")
    a, b, c = st.columns(3)
    with a:
        st.download_button("Export saved JSON", export_json(state.saved), "claimvoice-followups.json", "application/json", disabled=not state.saved, use_container_width=True)
    with b:
        st.download_button("Export saved CSV", export_csv(state.saved), "claimvoice-followups.csv", "text/csv", disabled=not state.saved, use_container_width=True)
    with c:
        st.download_button("Download transcript", transcript(state), "claimvoice-transcript.json", "application/json", use_container_width=True)


def activity(state):
    ui.section("Session activity", "Inspect the tools used during this demonstration. A tool event is not a real-world action.")
    labels = {"lookup_claim": "Synthetic claim retrieved", "record_draft": "Follow-up draft updated", "flag_handoff": "Human review flagged", "end_session": "Demonstration session ended"}
    for number, event in enumerate(state.activity, 1):
        name = event.get("tool", "Tool event")
        title = labels.get(name, name) if event.get("ok") else f"Tool rejected: {name}"
        with st.expander(f"{number:02d} · {title}"):
            st.json(event)
    if not state.activity:
        st.caption("No tool activity yet.")


def main():
    st.set_page_config(page_title="ClaimVoice | Follow-up workspace", page_icon="🎧", layout="wide")
    ui.style()
    try:
        secrets = dict(st.secrets)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        secrets = {}
    config = load_config(secrets)
    client = GroqClient(config)
    mode, claim_id, scenario = setup(config)
    ui.header()
    state = st.session_state.get("cv")
    ui.steps(state)
    if state is None:
        st.markdown('''<div class="cv-empty"><div class="cv-eyebrow">Start with a synthetic claim</div><h2>From a conversation to a reviewed record.</h2><p>Select your mode, claim and scenario in the sidebar, then choose <strong>Start / reset session</strong>. Try the scripted walkthrough without an API key, or use Live Groq for model-generated replies.</p></div>''', unsafe_allow_html=True)
        a, b, c = st.columns(3)
        for col, title, desc in [(a, "01 · Capture", "Type a representative reply, or transcribe recorded audio in live mode."), (b, "02 · Review", "Keep unknown facts unknown and check the draft against its transcript."), (c, "03 · Save & export", "Approve a reviewed record, then download JSON, CSV and the transcript.")]:
            with col:
                with st.container(border=True):
                    ui.section(title, desc)
        st.caption("Fictional claims only. This browser demo makes no phone calls and does not verify payments.")
        return
    if state.claim_id != claim_id or state.mode != mode:
        st.warning("Setup changed. Start / reset session to apply it. Download any work before resetting.")
        return
    ui.summary(state, CLAIMS[state.claim_id])
    convo, reviewed, events = st.tabs(["Conversation", "Review & export", "Activity"])
    with convo:
        conversation(state, client, config, scenario)
    with reviewed:
        review(state)
    with events:
        activity(state)
    st.markdown('<div class="cv-footer">Synthetic data only · No telephone calls · Session-only storage: download your work before leaving.</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
