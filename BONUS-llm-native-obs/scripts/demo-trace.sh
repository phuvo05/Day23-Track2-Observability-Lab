#!/usr/bin/env bash
# BONUS-llm-native-obs/demo-trace.sh
# Send a request to the Langfuse-traced app and print the trace URL.
set -euo pipefail

PORT=${1:-8001}
curl -sS -X POST "http://localhost:${PORT}/predict" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"What is the capital of France?"}' | \
  python3 -c 'import json,sys; d=json.load(sys.stdin); print("trace_id:", d.get("langfuse_trace_id","N/A")); print("lf_url:", d.get("langfuse_trace_url","N/A (Langfuse server may not be running)")); print("model:", d["model"]); print("quality:", d["quality_score"]); print("latency:", d.get("latency_seconds", "N/A"), "s")'
