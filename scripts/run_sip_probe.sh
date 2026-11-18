#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../lab/sip"
docker compose version >/dev/null
docker info >/dev/null
logdir="../../artifacts/sip/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$logdir"
cleanup() {
  docker compose logs --no-color > "$logdir/services.log" 2>&1 || true
  docker compose down --remove-orphans >/dev/null
}
trap cleanup EXIT
docker compose build
docker compose up -d --wait --wait-timeout 90 redis server sip insurer
docker compose images > "$logdir/images.txt"
docker compose exec -T insurer asterisk -rx 'core show version' > "$logdir/asterisk.txt"
docker compose exec -T insurer asterisk -rx 'module show like websocket' >> "$logdir/asterisk.txt"
docker compose exec -T insurer asterisk -rx 'core show application AudioSocket' >> "$logdir/asterisk.txt"
docker compose run --rm -T probe 2>&1 | tee "$logdir/result.log"
