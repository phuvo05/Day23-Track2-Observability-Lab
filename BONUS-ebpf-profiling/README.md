# BONUS-ebpf-profiling — Continuous Profiling with Pyroscope

Continuous profiling via Pyroscope + Grafana flame graphs.

**Grading checkpoint (B1, +10 pts):** Pyroscope flame graph for `day23-app` Python process visible in Grafana.

**Why this works on Windows:** Pyroscope Python SDK (`pyroscope-io`) instruments the Python code itself (not eBPF), and sends profile data over HTTP to the Pyroscope server. The "ebpf" in the bonus name refers to the general continuous profiling discipline — the Python instrumentation uses CPU profiling under the hood, which works on any OS. Server image: `grafana/pyroscope:1.20.3`.

## Architecture

```
day23-app (instrumented with pyroscope-io SDK)
  └─ HTTP push ──→ pyroscope:4040
                        │
                        ▼
                   Grafana (+ Phlare/Pyroscope plugin)
                   ┌──────────────────────────────┐
                   │ Flame graph for predict()     │
                   │ CPU % by function + call stack│
                   └──────────────────────────────┘
```

## Quick start

```bash
# Install Python SDK:
pip install pyroscope-io==1.0.6

# Start Pyroscope server (uses defaults — no config needed):
docker compose --profile bonus-b1 up -d
# Or from project root: make bonus-b1

# Visit: http://localhost:4040   (Pyroscope UI)
```

## Enable profiling in the app

Edit `.env` and set:
```
PYROSCOPE_SERVER_ADDRESS=http://localhost:4040
```

Then restart the app:
```bash
docker compose restart app
```

## What gets profiled

- `predict` endpoint: total CPU time, wall time, and call count
- `simulate_inference`: where inference time is spent
- `simulate_gpu_load`: smooth sinusoidal GPU simulation
- Structlog JSON rendering

## Pyroscope dashboard (Grafana)

Navigate to Grafana → Dashboards → "Pyroscope / Flame Graph". Select:
- **App:** `day23-app`
- **Profile type:** `cpu` (CPU time) or `Wall` (wall clock)
- **Time range:** last 15 minutes

The flame graph shows the call stack — wider bars = more CPU time. Look for:
- `simulate_inference` taking the most time (expected)
- `time.sleep` visible as leaf nodes
- FastAPI route handlers at the top

## Profile types

| Type | What it measures | Useful for |
|---|---|---|
| `cpu` | CPU time only (wall minus sleep) | Hot code paths |
| `wall` | Wall clock including I/O | Detecting slow calls |
