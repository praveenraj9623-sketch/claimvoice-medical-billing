#!/usr/bin/env bash
# Run inside Linux or WSL2, after installing the prerequisites in VOICE_PROBE.md.
set -euo pipefail
cd "$(dirname "$0")/.."
target=claimcall.audio_probe
voice="$PWD/models/en_US-lessac-medium.onnx"
args=(--voice "$voice")
if [[ $# == 1 && $1 == --sip-pending ]]; then
  target=claimcall.sip_exchange
elif [[ $# == 2 && $1 == --sip-replay ]]; then
  target=claimcall.sip_exchange
  for wav in question-heard.wav reply-heard.wav; do
    [[ -s "$2/$wav" ]] || { echo "Missing received recording: $2/$wav" >&2; exit 1; }
  done
  args=(--replay "$2")
elif (( $# )); then
  echo "Usage: $0 [--sip-pending | --sip-replay RECORDING_DIRECTORY]" >&2
  exit 2
fi
for binary in llama-server curl; do
  command -v "$binary" >/dev/null || { echo "Missing $binary; see VOICE_PROBE.md" >&2; exit 1; }
done
python_bin="${PROBE_PYTHON:-python3}"
mkdir -p artifacts/voice
if [[ ${args[0]} == --voice ]]; then
  command -v ffmpeg >/dev/null || { echo "Missing ffmpeg" >&2; exit 1; }
  if ! ffmpeg -hide_banner -filters 2>/dev/null | grep ' flite ' >/dev/null; then
    echo "Install FFmpeg with the flite filter." >&2
    exit 1
  fi
  mkdir -p models
  if [[ ! -s "$voice" || ! -s "$voice.json" ]]; then
    (cd models && "$python_bin" -m piper.download_voices en_US-lessac-medium)
  fi
fi
if curl -s --max-time 2 -o /dev/null http://127.0.0.1:8080/health; then
  echo "Port 8080 already has a server. Stop it before running this test." >&2
  exit 1
fi
server_log=$(mktemp "$PWD/artifacts/voice/llama-XXXXXX.log")
llama-server -hf Qwen/Qwen3-4B-GGUF:Q4_K_M --alias claimcall --jinja \
  --host 127.0.0.1 --port 8080 -ngl 0 -c 2048 -t 4 >"$server_log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT
echo "Starting Qwen. First run downloads model files. Server log: $server_log"
for ((attempt=0; attempt<900; attempt++)); do
  kill -0 "$server_pid" || { tail -n 10 "$server_log"; exit 1; }
  if curl -fs --max-time 2 http://127.0.0.1:8080/health >/dev/null; then
    "$python_bin" -m "$target" "${args[@]}"
    exit 0
  fi
  sleep 2
done
echo "Model server startup timed out. See $server_log" >&2
exit 1
