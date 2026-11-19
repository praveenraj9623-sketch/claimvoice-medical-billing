# Private SIP transport check

From the repository root in WSL2 Ubuntu, run `bash scripts/run_sip_probe.sh` with a running Docker engine and Compose v2. Run one instance at a time. Initial setup needs network access to build and pull images. The test uses an isolated Docker network, no published ports and a single internal extension, 7001. The launcher inspects the active Docker engine’s network allocations and selects an unused private IPv4 /24 for this run. It writes the selected subnet to prerequisites.log and renders the LiveKit and Asterisk configuration in the same run directory.

The caller joins a LiveKit room, publishes an audio track and dials Asterisk through LiveKit SIP. Asterisk allows only G.711 µ-law. The caller waits for menu audio and sends key 2. The successful menu branch plays 660 Hz and starts Echo(). The caller sends 980 Hz and must detect it coming back through the remote insurer track. A timeout, wrong route or missing echo fails the run.

Look for `PASS: caller audio returned through Asterisk Echo()` and exit code zero. The runner tears down the temporary stack and writes service logs, image details and the result under `artifacts/sip/`. The Asterisk report lists installed WebSocket modules and the AudioSocket application for planning the representative bridge. Look specifically for `chan_websocket.so` before choosing that channel driver.

The local voice feasibility run at revision d523189 passed both paid and pending in two operator-reported WSL trials. This SIP test checks the transport independently of the language and speech models. Once a connected run passes, record the working image digests and SDK versions before combining the two. The initial LiveKit images can be overridden with LIVEKIT_SERVER_IMAGE and LIVEKIT_SIP_IMAGE.

### First spoken exchange

In the same WSL environment as the successful voice and SIP tests, run
`bash scripts/run_voice_probe.sh --sip-pending`. The ordinary voice probe and
extension 7001 echo check remain available. Extension 7002 records the caller's
spoken question, then plays a fixed synthetic insurer reply. Key # marks the end
of the question. Tones delimit the reply on the caller's received audio track.
Whisper reads the two recordings after the call; the local Qwen extractor sees
only the insurer transcript. The check expects the caller's billing/status
question, representative Daniel, pending status, and three unknown payment fields.
Inspect both received WAVs and result.json in the printed artifacts/sip-exchange
directory. This exercises one scripted representative turn and offline capture.

To investigate a completed call, pass its received WAV directory to
`bash scripts/run_voice_probe.sh --sip-replay artifacts/sip-exchange/RUN_ID`.
Replay starts the local extractor and reads both original recordings. It skips
Docker and synthesis and writes a fresh result directory. Recognition uses a
separate process and defaults to CT2_USE_MKL=0 for the CPU lab. A native crash
leaves its exit code and recognition.log. The SIP exchange defaults to small.en.
To compare another model on the same audio, set CLAIMCALL_WHISPER_MODEL to a
cached model directory or a faster-whisper model name (may download weights).
Names and missing fields are checked against the same fixture on every run.

### Audit a saved paid reference

New paid exchanges and paid replays save `reference-audit.json` beside the
capture result. The audit checks the final reference against the two numbered
clarifications in the recognition worker's separate `transcripts.json`. Each
finding includes the exact quotes and the digits parsed from each. A verified
reference only establishes agreement with those transcripts.

For an existing run, use `python -m claimcall.reference_audit path/to/result.json`.
It prints JSON and reads the saved files without changing them. Exit 0 means
verified, 1 means the field needs review, and 2 means the audit inputs could
not be read or validated. To test a deliberately altered copy, pass the copy as
the record and `--transcripts path/to/original/transcripts.json` as its evidence.

### Changed claim-status menu

In WSL, activate the same Python environment with the cached small.en speech
model used for paid calls. Run these commands from the repository root:

```bash
bash scripts/run_sip_probe.sh --menu-preflight &&
  bash scripts/run_sip_probe.sh --menu-control &&
  bash scripts/run_sip_probe.sh --menu-changed
```

Preflight uses host FFmpeg with the flite filter to generate both spoken menus. It runs the same cached CPU recognizer as the caller, without starting Docker or placing a call. Set `PROBE_PYTHON` to the existing environment’s Python if it is not active. On a worker failure, inspect `menu-2/recognition.log` or `menu-3/recognition.log` and the adjacent `loader.log` under the printed run directory.

The control and changed menus use the same simulated voice and wording: “To check the status of your claim. Please press the number [two or three].” Only the requested digit differs. Both preflight and Asterisk use `render_menu.sh` to generate their prompts. A transcript such as “press free” leaves the digit unknown and routes to review. It does not count as recognition of the changed digit. The caller records the
received SIP audio through the end-of-menu tone and a local Whisper worker
transcribes it before the caller can send a key. Only a single explicit
claim-status instruction matching the approved key 2 authorizes navigation.
An unclear or changed menu goes to review. The end-of-menu tone is part of the
simulated insurer. The pending and paid exchanges use the same check. The
original echo-only transport diagnostic continues to exercise keypad transport.

Find the received WAV, transcript, decision and sent digits in the run's
`artifacts/sip/.../menu/` directory. The control passes when Asterisk receives
2. The changed-menu test passes when the caller hears 3, requests review, and
Asterisk's hangup log confirms an empty selection. A recognition error, an
unclear transcript, or missing receiver evidence cannot pass that test.

To replay a failed SIP control, run `bash scripts/run_sip_probe.sh --menu-replay-control path/to/menu-heard.wav`.
For a changed-menu recording use `--menu-replay-changed`. Replay reads the original capture,
writes into a fresh artifact directory, and runs the live menu recognizer and decision rule.
It neither starts Docker nor sends a key. Live and replay ASR both use `menu-speech.wav`,
which excludes the two confirmed 50 ms blocks of the simulated insurer's ending tone
and trims excess leading digital silence. The raw SIP recording stays in `menu-heard.wav`.
Only a fresh call provides receiver-side evidence of which key reached Asterisk.
The lab plays the 1520 Hz marker as the Asterisk `Read()` prompt, so the
keypad reader owns the channel when ClaimCall hears the cue. The caller's
`sent_digits` records dispatch. Use Asterisk's DTMF logs and
`CLAIMCALL_MENU_EXIT` line, which includes `READSTATUS`, to confirm receipt.
