#!/usr/bin/env bash
set -euo pipefail
exchange=""
case_name=""
extension=7001
if [[ $# == 1 && ( $1 == --menu-control || $1 == --menu-changed ) ]]; then
  case_name=${1#--}
  extension=7004
  if [[ $case_name == menu-changed ]]; then extension=7005; fi
elif [[ $# == 2 && ( $1 == --pending || $1 == --paid ) && -s "$2/question.wav" ]]; then
  case_name=${1#--}
  exchange=$(cd "$2" && pwd)
  extension=7002
  if [[ $case_name == paid ]]; then extension=7003; fi
elif (( $# )); then
  echo "Usage: $0 [--menu-control | --menu-changed | --pending DIRECTORY | --paid DIRECTORY]" >&2
  exit 2
fi
python_bin="${PROBE_PYTHON:-python3}"
if [[ $python_bin == */* && $python_bin != /* ]]; then python_bin="$PWD/$python_bin"; fi
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
menu_pid=""
cleanup() {
  if [[ -n "$menu_pid" ]]; then
    kill "$menu_pid" 2>/dev/null || true
    wait "$menu_pid" 2>/dev/null || true
  fi
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
options=()
if [[ -n "$case_name" ]]; then
  menu_dir="$CLAIMCALL_CONFIG_DIR/menu"
  mkdir "$menu_dir"
  "$python_bin" menu_guard.py "$menu_dir" > "$menu_dir/recognition.log" 2>&1 &
  menu_pid=$!
  for ((i=0; i<120; i++)); do
    [[ -f "$menu_dir/ready" ]] && break
    kill -0 "$menu_pid" 2>/dev/null || fail_setup "Menu recognizer startup failed. See $menu_dir/recognition.log"
    sleep 1
  done
  [[ -f "$menu_dir/ready" ]] || fail_setup "Menu recognizer startup timed out."
  options+=(-v "$menu_dir:/menu" -e CLAIMCALL_MENU_DIR=/menu -e "CLAIMCALL_EXTENSION=$extension")
fi
if [[ -n "$exchange" ]]; then
  options+=(-v "$exchange:/exchange" -e CLAIMCALL_EXCHANGE_DIR=/exchange -e "CLAIMCALL_CASE=$case_name")
fi
docker compose run --rm -T "${options[@]}" probe 2>&1 | tee "$logdir/result.log"
if [[ "$case_name" == menu-* ]]; then
  # Independent receiver evidence: wait for Asterisk's hangup handler to record CHOICE.
  for ((i=0; i<12; i++)); do
    docker compose logs --no-color insurer > "$menu_dir/insurer.log"
    if grep -Fq 'CLAIMCALL_MENU_EXIT digit=[' "$menu_dir/insurer.log"; then break; fi
    sleep 1
  done
  "$python_bin" verify_menu.py "$case_name" "$menu_dir"
fi
if [[ -n "$exchange" ]]; then
  docker compose cp insurer:/tmp/claimcall-question.wav "$exchange/question-heard.wav"
  if [[ "$case_name" == paid ]]; then
    for attempt in 1 2; do
      docker compose cp "insurer:/tmp/claimcall-clarify-$attempt.wav" "$exchange/clarify-$attempt-heard.wav"
    done
  fi
fi
