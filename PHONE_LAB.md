# ClaimVoice Phone Lab

ClaimVoice supports a synthetic claim call with phone-menu navigation, bounded hold handling, structured capture and transcript review. The Streamlit workspace runs the local simulator. The optional FastAPI service connects the same call logic to a configured Twilio ConversationRelay test number.

## Run the demo on Windows

From the repository directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Choose **Phone Lab** in the sidebar. Run **Paid after hold** and inspect the DTMF sequence, return from hold, claim number repeat and saved evidence preview. Run **Menu changed** to see a route stop and **Missing payment amount** to see a human-review flag. **Run benchmark** covers all six scenarios. Download **call reports** for the transcript and capture details.

To repeat the fixtures from a terminal or scheduler:

```powershell
.\.venv\Scripts\python.exe -m claimvoice.phone.simulator --repeat 20
```

## Review and measurement

- The call flow uses explicit menu phrases and known DTMF keys. An unrecognized route stops after two mismatches. One clarification per field, a turn cap, a hold deadline and a call deadline bound the conversation. The default simulator uses a 30-second hold cap and advances its clock during hold scenarios.
- The structured report contains claim status, denial code, paid amount, payment reference, payment date, call reference and representative name. Paid and denied claims have different required fields. Unknown values remain blank.
- The transcript checker independently checks whether a captured value matches its cited representative turn. Missing answers, unsupported values and aborted calls surface for human review. This check shares the supported value normalization rules with capture.
- The local benchmark compares output with named fixture expectations. Repeated runs exercise the same six fixtures. Fixture field matches include correct blanks. Python processing latency excludes speech recognition, synthesis, network, call setup and hold time. The simulator has zero provider spend.
- The optional dialer bounds call duration and blocks attempts whose **estimated** maximum exceeds the configured budget. Its report uses provider-reported duration and an operator-entered combined per-minute rate, rounded up to whole minutes. It does not reconcile invoice items, fixed fees or optional AI review fees. An unconfirmed dial is never automatically redialed.
- For a live evaluation, record speech-end to first-audible-reply latency, label representative-call fields with a human reviewer, and reconcile charges with provider billing. Report denominators for IVR pass, all-required-field capture, and field agreement. The employer's targets require live validation.

## Hosted staging service

The phone service uses Twilio Programmable Voice and ConversationRelay. Twilio handles phone audio, speech recognition and voice playback. Python controls the call and sends DTMF keypad tones. PostgreSQL stores the captured fields, transcript evidence, provider outcome and review findings. Streamlit continues to serve the existing browser workspace.

1. Provision a WebSocket-capable host for the repository's Dockerfile and a PostgreSQL database. Set the host's HTTP health check to `/ready`. The container runs as an unprivileged user and listens on the host-provided `PORT`. Keep server access logs free of webhook query strings and use HTTPS/WSS on the public edge.
2. Add the server settings from `phone.env.example` through your host's secrets manager. Set `CLAIMVOICE_ENV=hosted`, the assigned HTTPS origin as `CLAIMVOICE_PUBLIC_URL`, and an SSL-verified Postgres DSN as `CLAIMVOICE_PHONE_STORAGE`. The DSN must include `sslmode=verify-full`. Mount the database CA certificate using the hosting provider's secret-file feature when needed and include its path as `sslrootcert`. The database role needs access to its dedicated schema. The service initializes its own tables and does not write to a billing system.
3. Use a Twilio account with Voice and ConversationRelay enabled, a permitted caller ID and an authorized test destination. Configure the test line to play **“For claims, press 2”**, then **“For claim status, press 1”**, followed by a representative greeting. The route is defined for that test line. Trial calls are subject to provider verification and eligibility limits.
4. Confirm `GET /health` and `GET /ready` return 200 from an external network. Confirm the database is reachable by the operator process. Use a private operator shell or job with the same database DSN, Twilio settings and public URL. Set `CLAIMVOICE_DIALING_ENABLED=true` only there. Use synthetic data throughout staging.

Run an authorized test call from that operator environment after confirming applicable charges:

```sh
python -m claimvoice.phone.telephony dial --request-id staging-001 --confirm-test-call
python -m claimvoice.phone.telephony report --call-id ATTEMPT_ID
```

Use the same request ID to retrieve the original attempt without placing a duplicate call. Use a unique ID for each intentionally new call. The service reserves the maximum estimated cost against a UTC-day allowance before dialing and permits one active or unconfirmed call at a time during its lease. Reservations are conservative and stay in the day's budget after completion. If a request times out, check the Twilio call log and the stored provider status before authorizing a new attempt. The provider call timer bounds a dropped or interrupted call. An outbound call already connected is controlled through the provider console.

The dialer uses a fixed destination, keeps recording off and provides no public dial route. The WebSocket and status callback require Twilio signatures. After setup the service ties the provider call ID to the saved attempt and rejects mismatches and replayed relay sessions. If the menu changes, the call stops and reports a review issue. An unavailable database returns 503 from readiness. Keep the previous image available for rollback and stop new test calls while investigating outages or unexpected costs.

The evidence check runs on each finalized call. Operators can request one additional Groq review per synthetic transcript using `python -m claimvoice.phone.telephony review-ai ATTEMPT_ID`. Model findings are stored with the call and can send the record to human review. This command sends the synthetic transcript to Groq and may incur charges. Model availability, spend and transcript quality need separate monitoring.

- [Twilio ConversationRelay setup](https://www.twilio.com/docs/voice/conversationrelay/onboarding)
- [ConversationRelay WebSocket protocol](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages)
- [Supabase database TLS settings](https://supabase.com/docs/guides/platform/ssl-enforcement)

## Production release criteria

- Verify routing, keypad input, held calls, ambiguous replies, disconnects, and signed callbacks over actual controlled phone calls. Measure speech-end to first-audible-reply latency on these calls.
- Report IVR reach rate, required-field completion, human-labeled field agreement and provider-reconciled cost per completed call. Exact thresholds and denominator definitions come from the business requirements.
- Before handling live insurer data, obtain company approval for telephony, speech, storage and LLM providers, applicable BAAs, access and retention controls, an approved operational review workflow, and authorization for each call route. Synthetic staging keeps production insurer calls and patient data outside the current scope.
