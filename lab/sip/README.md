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
