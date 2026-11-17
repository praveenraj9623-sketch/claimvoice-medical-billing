# ClaimVoice - Insurer Follow-up Assistant

[Live demo](https://praveen-claimvoice.streamlit.app/) · [Source](https://github.com/praveenraj9623-sketch/claimvoice-medical-billing)

A turn-based browser PoC that turns fictional insurer replies into a structured follow-up draft. The user plays an insurer representative; the assistant plays a billing employee. Built with Python, Streamlit, Groq, HTTPX and browser speech.

## Browser Voice

Open **Browser Voice**, start a microphone session, and play the representative for fictional claim TEST-48213. ClaimVoice waits on hold, asks for missing answers, and saves the transcript, captured fields and evidence checks. The panel can export its report as JSON. **Claim follow-up** and **Phone Lab** are also available from the sidebar.

### Run from the checkout

Python 3.12 is used in the voice service container. Install `requirements.txt` for Streamlit and `requirements-browser.txt` for the backend. Copy `browser.env.example` to `.env` for a fresh checkout, or add its keys to your existing `.env`. Supply `GROQ_API_KEY` and generate a launch signing secret with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Use the same signing secret on the backend and in Streamlit.

Start these in two terminals:

```sh
python -m uvicorn claimvoice.browser.server:app_factory --factory --host 0.0.0.0 --port 7860 --no-access-log
python -m streamlit run app.py
```

Restart both processes after changing their settings. In a new tab or inside the workspace, grant browser microphone access. For the easiest first check, say “please hold,” then “I'm back.” Say “the claim is pending,” then give a reference and representative name one at a time. Say “unknown” twice for a required field to see the review flag.

### Host a staging demo

Deploy `Dockerfile.browser` as a separate, single-worker service. Configure HTTPS and test ICE connectivity over UDP from an external network. An HTTP-only host can pass `/ready` without carrying WebRTC audio. `CLAIMVOICE_STUN_URLS` accepts STUN endpoints when needed. This version does not configure a TURN relay. For restricted networks, plan relay support or verify a reachable ICE path before sharing the demo.

Set `CLAIMVOICE_STREAMLIT_ORIGIN` on the backend to the existing Streamlit HTTPS origin. Set `CLAIMVOICE_BROWSER_URL` and the shared `CLAIMVOICE_BROWSER_SECRET` in Streamlit secrets. Set the Groq key only on the backend for Browser Voice. Store the SQLite database on a persistent volume or set `CLAIMVOICE_BROWSER_STORAGE` to a dedicated PostgreSQL connection string configured for verified TLS. Keep the voice API to one worker, because in-progress calls and launch limits live in its process. Completed reports persist in the selected database. A process restart interrupts active calls.

The backend exchanges microphone audio over WebRTC and sends final, VAD-segmented utterances to Groq Whisper. The browser speaks the resulting prompts with device speech synthesis and pauses input during playback. Response time in reports runs from final transcript to server reply and excludes audio processing and playback. The capture path uses deterministic parsing and a Groq exact-quote fallback for selected fields. The evidence checker flags missing or unsupported answers. A matched quote establishes transcript support, not a verified payment.

Before publishing the resume link, test the deployed embed and separate-tab fallback with a real microphone, speaker, and Groq account on the intended network. Verify hold and resume, saved records, and responses when the provider is unavailable. Use fictional information only. The live telephone integration is a separate milestone.

## Phone Lab

Select **Phone Lab** in the Streamlit sidebar to run synthetic insurer calls and inspect IVR navigation, hold behavior, structured capture, evidence checks and benchmark results. [Phone Lab setup and optional Twilio test adapter](PHONE_LAB.md).

## User problem and outcome

A useful follow-up note needs a status, reference, requested documents, next action and follow-up date. ClaimVoice keeps these together with supporting transcript turns, requires human approval before saving, and exports reviewed records. More consistent documentation is the intended benefit; real call handling, time savings and throughput have not been measured.

## Workflow

1. Select one of three synthetic claims and start a session.
2. Type a representative reply, or explicitly request transcription in live mode and edit the text.
3. Process the reply through the selected scripted or live path.
4. Inspect the draft, original claim and supporting transcript.
5. Approve, save a session snapshot and export JSON/CSV or transcript.

Original claim data and newly reported facts stay separate. Unknown facts remain null. Reported payment is not a verified remittance or bank receipt.

## Interface

The workspace separates **Conversation**, **Review & export** and **Activity**. Readable claim cards and draft fields are shown first; original JSON and tool payloads remain available in expandable panels. Browser playback has explicit Play/Stop controls. The sidebar configures the session, and changing a claim or mode still requires an explicit reset.

## Modes, models and tools

| Component | Actual implementation |
|---|---|
| Scripted walkthrough | Deterministic parsing of labelled scenario text; no Groq requests |
| Live conversation | Groq chat completions, default `openai/gpt-oss-20b` |
| Speech recognition | Groq transcription, default `whisper-large-v3-turbo` |
| Audible playback | Browser Web Speech service; engine/voices depend on the browser and OS |
| Application control | Custom Python workflow and allowlisted tools, not a LiveKit call |

The LLM is a configurable starting point for tool calling and hosted inference on a lightweight app host. GPT-OSS has Apache-2.0 open weights; Groq is a separate hosted service with account-specific quotas and pricing. No comparison establishes this model as the best voice or billing model. The LLM generates text; Whisper recognises speech; neither is the browser's playback voice.

Allowed tools in [claimvoice/tools.py](claimvoice/tools.py):

- `lookup_claim`: access only the selected synthetic claim.
- `record_draft`: prepare candidate fields supported by representative turns; not a final save.
- `flag_handoff`: set a local human-review flag; no actual transfer or message.
- `end_session`: end the local demonstration session.

Python validates argument fields, quote support and ISO dates. Exact-substring support does not prove correct interpretation, including negation, so human review remains necessary. The live loop is bounded to four completion requests per reply and eight tool calls per completion; retries are explicit.

## Run locally - Python 3.11 / PowerShell

```powershell
git clone https://github.com/praveenraj9623-sketch/claimvoice-medical-billing.git
Set-Location claimvoice-medical-billing
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

`requirements.txt` is sufficient for the browser app; the development file also installs pytest. No private machine-specific Python path is required. No LiveKit, SIP, Deepgram, Cartesia, CUDA or local LLM download is required for this Streamlit path.

## Groq configuration

Scripted mode needs no key. For live mode, copy the existing Streamlit example without overwriting a real secrets file:

```powershell
if (-not (Test-Path -LiteralPath .streamlit/secrets.toml)) {
    Copy-Item -LiteralPath .streamlit/secrets.example.toml -Destination .streamlit/secrets.toml
}
notepad .streamlit/secrets.toml
```

Fill in these top-level settings locally, or in Streamlit Community Cloud's Secrets settings:

```toml
GROQ_API_KEY = "your-key-here"
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
```

The app also reads a manually created root `.env`; no `.env.example` is required. Per-variable precedence is environment, Streamlit Secrets, root `.env`, defaults. An explicitly empty environment key disables live mode. Restart after file changes. Never commit or screenshot credentials. For Community Cloud use `app.py` and the browser-app dependency file.

## Two-minute scripted demonstration

1. Select **Scripted walkthrough**, a claim and **Pending processing**; click **Start / reset session**.
2. Click **Use scenario example**, then **Send reply**. The script reads `Status`, `Reference`, `Documents`, `Next action` and `Follow-up date` labels.
3. Compare the draft with the supporting representative turn. Dates must be explicit YYYY-MM-DD values.
4. Open **Review & export**, check the supporting transcript and approval box, then **Save reviewed follow-up**. Show JSON/CSV export and transcript download.
5. Submit `human handoff`, then `end session` separately. Explain that these are local state changes.
6. Download before resetting. Repeat with document-requested or payment-reported scenarios.

For a live check, select **Live Groq** and start a new session. Transcription sends audio only when clicked; edit before sending. Play/Stop uses browser speech. A scripted result is not evidence that live Groq, microphone capture or playback succeeded.

## State, privacy and failure handling

Records persist within a Streamlit session until downloaded; resets/refreshes can discard them. Approval is checked in storage code, repeated identical saves are idempotent, and CSV formula prefixes are neutralised. Duplicate reply/audio requests are controlled. Failures preserve conversation and completed tool activity with safe messages; partial tool operations are not rolled back.

Recording uploads audio to the Streamlit host; requested transcription sends it to Groq. Live replies send conversation and relevant synthetic claim/tool context. Browser speech may use vendor network services. Use fictional data only. No real phone calls, document submissions, payment verification, durable enterprise storage or established HIPAA compliance is provided.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The UI update passed **22 offline tests**, with external socket connections blocked. Coverage includes tool/evidence validation, session isolation, duplicate protection, review-gated saves, exports, service errors, Streamlit AppTest flows and HTML/script escaping. Dependency and whitespace checks also passed. No live Groq requests were made during this update. Offline tests do not validate microphone hardware, audible output, model quality or production load.

Before a live demonstration, separately check microphone permission, transcription/edit/send, audible Play/Stop, safe failure handling and exports in the actual browser. Typed input and clearly labelled scripted mode remain separate demonstration paths.

## Open-source speech options - not additional implemented features

- [Whisper](https://github.com/openai/whisper): MIT-licensed speech-recognition code and weights. The app currently accesses its configured model through Groq, rather than running it locally.
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M): Apache-2.0 open-weight text-to-speech option. It is not this app's current playback engine.
- [Piper](https://github.com/OHF-Voice/piper1-gpl): a local neural TTS engine under GPL-3.0. Check each selected voice model's separate licence and deployment terms.

LiveKit is a real-time framework, not a speech model. Replacing browser speech or adding real telephony needs implementation and testing; listing an option does not implement it.

## Foundation and licence

Adapts patterns from [livekit-examples/outbound-caller-python](https://github.com/livekit-examples/outbound-caller-python) at `608f4c7`. The original `agent.py`, history and [MIT LICENSE](LICENSE) are preserved. Adaptation work includes the Streamlit workflow, synthetic claims, Groq transport, validated draft tools, editable transcription, browser speech bridge, session saves/exports and offline tests.

The preserved worker is separate from this browser app and retains its original dental example. See [README.upstream.md](README.upstream.md) for its scope and original source. Its dependencies and environment placeholders are in `requirements-livekit.txt` and `.env.livekit.example`; it is not a tested ClaimVoice telephone deployment.
