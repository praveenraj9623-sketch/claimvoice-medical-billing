#!/usr/bin/env bash
set -euo pipefail
exchange=""
if (( $# )); then
  [[ $# == 2 && $1 == --pending && -s "$2/question.wav" ]] || { echo "Usage: $0 [--pending DIRECTORY_WITH_QUESTION_WAV]" >&2; exit 2; }
  exchange=$(cd "$2" && pwd)
fi
cd "$(dirname "$0")/../lab/sip"
logdir="../../artifacts/sip/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$logdir"
log="$logdir/prerequisites.log"
echo "SIP probe logs: $(cd "$logdir" && pwd)"
fail_setup() {
  echo "$1" | tee -a "$log" >&2
  exit 1
}
command -v docker > "$log" || fail_setup "Docker CLI unavailable in this shell. Check Docker Desktop WSL integration for this Ubuntu distribution."
docker compose version >> "$log" 2>&1 || fail_setup "Compose unavailable. Check the Compose plugin or Docker Desktop WSL integration. See $log."
docker context show >> "$log" 2>&1 || true
engine_os=$(docker info --format '{{.OSType}}' 2>> "$log") || fail_setup "Docker engine unreachable. Start the engine and check the selected Docker context. See $log."
echo "Engine OS: $engine_os" >> "$log"
[[ "$engine_os" == "linux" ]] || fail_setup "This lab requires a Linux container engine. Check Docker Desktop's container mode."
# Read every configured subnet, including networks without running containers.
network_ids=$(docker network ls -q)
mapfile -t ids <<< "$network_ids"
docker network inspect --format '{{range .IPAM.Config}}{{println .Subnet}}{{end}}' "${ids[@]}" > "$logdir/docker-subnets.txt"
CLAIMCALL_CONFIG_DIR=$(cd "$logdir" && pwd)
CLAIMCALL_PREFIX=$(python3 network.py "$CLAIMCALL_CONFIG_DIR" < "$logdir/docker-subnets.txt")
export CLAIMCALL_PREFIX CLAIMCALL_CONFIG_DIR
echo "Selected SIP lab subnet: $CLAIMCALL_PREFIX.0/24" | tee -a "$log"
cleanup() {
  docker compose logs --no-color > "$logdir/services.log" 2>&1 || true
  docker compose down --remove-orphans >/dev/null
}
trap cleanup EXIT
docker compose build
docker compose up -d --wait --wait-timeout 90 redis server sip insurer
docker compose images > "$logdir/images.txt"
for service in server sip redis insurer; do
  id=$(docker compose images -q "$service")
  docker image inspect --format '{{.Id}} {{json .RepoDigests}}' "$id" >> "$logdir/image-digests.txt"
done
docker compose exec -T insurer asterisk -rx 'core show version' > "$logdir/asterisk.txt"
docker compose exec -T insurer asterisk -rx 'module show like websocket' >> "$logdir/asterisk.txt"
docker compose exec -T insurer asterisk -rx 'core show application AudioSocket' >> "$logdir/asterisk.txt"
if [[ -n "$exchange" ]]; then
  docker compose run --rm -T -v "$exchange:/exchange" -e CLAIMCALL_EXCHANGE_DIR=/exchange probe 2>&1 | tee "$logdir/result.log"
  docker compose cp insurer:/tmp/claimcall-question.wav "$exchange/question-heard.wav"
else
  docker compose run --rm -T probe 2>&1 | tee "$logdir/result.log"
fi
