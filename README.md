# ClaimVoice

A turn-based Streamlit portfolio demo for synthetic ambulance-claim follow-up. The user plays an insurer representative; the assistant plays a medical billing assistant. No telephone calls, real claims, real insurer contact, streaming audio, or interruption handling.

## Install and run (PowerShell, Python 3.11)

```powershell
Set-Location C:\AI-Projects\claimvoice-medical-billing
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The workspace's pre-existing virtual environment referenced an absent interpreter. During implementation a private Python 3.11 was installed inside ignored `.python/`, and `.venv` was repaired. On this machine the existing `.venv` commands above work directly. To recreate it here if the system `py` launcher is still broken:

```powershell
.\.python\cpython-3.11.15-windows-x86_64-none\python.exe -m venv .venv
```

Use `requirements.txt` alone for running the browser demo. LiveKit, SIP, OpenAI, Deepgram, Cartesia, CUDA and model downloads are not browser-demo requirements.

## Local Groq configuration

Scripted mode needs no key. To use live mode, create root `.env` only if it does not exist, then edit it locally:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
notepad .env
```

Set `GROQ_API_KEY` to your own key inside that file. Do not paste it into the conversation, screenshots, source code or exports. Existing credentials are never overwritten by this setup. `.env`, `.env.local`, and `.streamlit/secrets.toml` are ignored by Git.

Configuration precedence, per variable: process environment > Streamlit Secrets > root `.env` > defaults. An explicitly empty environment key disables live mode even if another source has a key. `.env.local` is only for the preserved upstream worker and is not read by this demo. Restart Streamlit after editing secrets.

Alternative `.streamlit/secrets.toml` (copy `.streamlit/secrets.example.toml` only if the real file does not exist):

```toml
GROQ_API_KEY = "your-key-here"
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
```

The default model IDs can be changed locally. Availability depends on your Groq account. No paid API requests were made during development.

## Guided two-minute demonstration

1. Leave **Scripted walkthrough** selected. Choose a synthetic claim and **Pending processing**, then **Start / reset session**. Read the assistant greeting as the insurer representative.
2. Press **Use scenario example**, edit it if desired, then **Send reply**. The script reads semicolon-separated labels: `Status`, `Reference`, `Documents`, `Next action`, `Follow-up date`. No LLM or transcription runs. Unlabelled free text produces guidance rather than guessed facts.
3. Compare **Original claim data** with **Newly reported information**. Inspect supporting transcript turns and **Tool activity**. Unknown values are JSON null. Supply dates only as explicit YYYY-MM-DD values. Example dates/references are fictional, not predictions or deadlines.
4. Read the draft, check the review box, then **Save reviewed follow-up**. Download JSON, CSV and transcript. Saving is session-local; downloads provide durable files. Identical saves are idempotent. CSV formula prefixes are neutralized.
5. Type `human handoff`, then `end session`, submitting each separately. These set local flags and end the demo; no transfer occurs. Existing drafts remain reviewable.
6. Download before resetting. Start new sessions for **Additional documents requested** and **Payment reported**. Payment is a representative report, not a verified remittance. No payment amounts or settlement details are invented.
7. With a configured key, select **Live Groq** and start a new session. Type a fictional reply, or record WAV audio and click **Transcribe recording with Groq**. Edit the resulting text before pressing **Send reply**. Click **Play assistant reply** / **Stop** for browser speech.

## Architecture and provenance

- `app.py`: Streamlit interface, explicit forms/buttons, microphone, review and downloads. Guarded entrypoint; importing it does not start the UI or load LiveKit.
- `claimvoice/config.py`: three-source configuration, key excluded from config representation.
- `state.py`: per-session conversation, request reservations, draft, saved records and lifecycle flags. No shared mutable conversation cache.
- `claims.py`: three fictional claims and independent guided examples.
- `tools.py`: complete function schemas and allowlisted execution for lookup, draft, handoff and end. Argument keys/types, selected-claim access, ISO dates and exact representative-quote evidence are checked before state mutation. Validation failures are returned as errors. No final-save tool exists.
- `groq_client.py`: HTTPX requests to Groq chat completions and audio transcription. Correct assistant tool-call messages and matching tool results. At most four completion requests per reply and eight calls per completion, with no automatic retries. Timeout/authentication/rate-limit/network/malformed-response errors are sanitized. Conversation and any successful draft tool activity remain available on failure; partial tool activity is not rolled back.
- `workflow.py`: common lifecycle, deterministic labelled-input parsing, live orchestration.
- `speech.py`: WAV validation and browser speech controls. Script-sensitive text is JSON encoded and HTML-sensitive characters escaped.
- `storage.py`: review-gated idempotent session saves, immutable snapshots and JSON/CSV/transcript export. No disk database or global record store.

This project adapts `livekit-examples/outbound-caller-python` at upstream commit `608f4c7`. The upstream `agent.py`, `LICENSE`, `.github/` assets and Git history are preserved. The original README is retained verbatim as `README.upstream.md`; original dependencies are retained as `requirements-livekit.txt`, and original environment placeholders as `.env.livekit.example`.

Precisely reused patterns: `OutboundCaller.__init__`'s explicit role instructions become the billing-specific `SYSTEM` prompt and opening turn; the decorated `look_up_availability` function's structured tool boundary becomes explicit JSON function schemas plus local dispatch; `transfer_call` and `end_call` inspire separate handoff/end lifecycle tools. These are conceptual adaptations, not shared LiveKit runtime code. The original upstream lookup returned a hardcoded availability result and confirmation returned a success string. The new claim lookup, evidence validation, draft recording and human-reviewed storage are application implementations. All Streamlit UI, synthetic claims, Groq transport, speech bridge, state, exports and offline tests are new.

The original worker remains an optional, separate integration starting at `agent.py`; its setup and notices are in `README.upstream.md`. It retains its original dental workflow and can dial real numbers if separately configured/dispatched. It is not wired to the ClaimVoice browser UI and was not run, dispatched or tested here. Keep optional packages in a separate environment if exploring it. No calls should be dispatched as part of this demonstration.

## Reliability, privacy and limitations

All external API calls require explicit actions. Merely recording uploads audio to the Streamlit server; **Transcribe** sends those bytes to Groq. **Send reply** in live mode sends conversation text, selected claim ID, tool schemas and any requested synthetic claim tool results to Groq. Later tool-loop requests may also include the draft/evidence. Audio is not saved or exported. Browser speech uses the browser's speech service and may use vendor network services. Use synthetic content only; this is not a production medical/PHI application.

Request IDs are reserved before calls. Reruns cannot resubmit the same reply text or recording within a session. Identical reply text is intentionally accepted only once per session; edit for a distinct statement. Audio failures require a new recording. Assistant failures have an explicit retry button, without appending the user turn twice. Tool activity exposes successes and failures. Setup changes require a new session; reset/refresh can discard all session data. Separate Streamlit sessions have separate objects.

Exact-substring validation prevents recording unsupported strings; it cannot prove a model interpreted a representative correctly, including negation or which field a quote belongs to. Human review remains mandatory. Assistant prose is model-generated and must also be checked. Draft updates replace the draft; earlier reviewed snapshots remain saved. Scripted updates use the latest nonempty labelled value per field; start a fresh session to clear a previously supplied fact. Relative dates are not resolved automatically. No real handoff, document submission, payment verification or completed external actions occur.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Offline tests block socket connections and mock all external services with HTTPX MockTransport. They cover tools/evidence/schema failures, dates, unknown claims, session isolation, duplicate prevention, review gating, snapshot/export behavior, CSV safety, secret-safe failures, tool result protocol/loop bounds, multipart STT, empty audio, script escaping and Streamlit AppTest startup plus a complete save/reset flow. AppTest exercises the app without opening a browser or network listener.

Verified on Python 3.11.15 with Streamlit 1.67.0: **20 tests passed**. `pip check` and `git diff --check` passed. Transcription UI tests use mocked audio/services, verify explicit transcription, editable text and duplicate suppression; they do not test a physical microphone. Windows AppTest event loops allocate local socketpairs during fixture setup before socket connections are blocked for each test. No external services are contacted by tests. Upstream README, requirements and environment-example copies match Git HEAD after Windows line-ending normalization; `agent.py` and `LICENSE` remain unchanged.

Manual checklist (not yet verified with real microphone/playback or paid Groq requests):

- Open localhost in a browser, allow microphone, record a fictional reply. Confirm recording alone makes no Groq request.
- Click Transcribe once; check editable text, edit it, then Send. Rerun unrelated controls and confirm no duplicate requests. Try silence/empty audio and a denied microphone permission; typed input must remain usable.
- Click Play and Stop. Verify actual audible output, absent voices, blocked playback and text fallback. Submit `</script><img src=x onerror=alert(1)>` as fictional text and confirm no execution.
- Try an invalid key and rate-limited key only if intentionally making live API requests; confirm preserved conversation and safe messages. Verify both tool-calling behavior and manual draft review with your configured model.
- Open a second browser session and confirm no shared transcript or records. Download all exports before reset.

API and UI contracts referenced: [Groq tool use](https://console.groq.com/docs/tool-use/overview), [Groq speech-to-text](https://console.groq.com/docs/speech-to-text), [Streamlit audio input](https://docs.streamlit.io/develop/api-reference/widgets/st.audio_input), [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest).
