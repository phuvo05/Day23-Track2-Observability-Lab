#!/usr/bin/env bash
# BONUS-ebpf-profiling/demo-load.sh
# Generate traffic so Pyroscope captures meaningful CPU profiles.
set -euo pipefail

echo "Sending 20 concurrent requests to trigger profiling..."
for i in $(seq 1 20); do
  curl -sS -X POST http://localhost:8000/predict \
    -H 'Content-Type: application/json' \
    -d "{\"prompt\":\"benchmark request $i\"}" &
done
wait
echo "Done. Check Pyroscope at http://localhost:4040 or Grafana."
