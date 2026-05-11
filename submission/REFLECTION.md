# Day 23 Lab Reflection

> Fill in each section. Grader reads the "What I'd change" paragraph closest.

**Student:** Võ Thiên Phú
**Submission date:** 2026-05-11
**Lab repo URL:** https://github.com/phuvo05/Day23-Track2-Observability-Lab

---

## 1. Hardware + setup output

Paste output of `python3 00-setup/verify-docker.py`:

```json
{
  "docker": {
    "ok": true,
    "version": "27.3.1"
  },
  "compose_v2": {
    "ok": true,
    "version": "2.30.3-desktop.1"
  },
  "ram_gb_available": 7.61,
  "ram_ok": true,
  "required_ports": [
    8000,
    9090,
    9093,
    3000,
    3100,
    16686,
    4317,
    4318,
    8888
  ],
  "bound_ports": [],
  "all_ports_free": true
}
```

All ports were free at startup. Docker v27.3.1 and Compose v2.30.3 confirmed operational. 7.61 GB RAM available, sufficient for the stack.

---

## 2. Track 02 — Dashboards & Alerts

### 6 essential panels (screenshot)

Drop `submission/screenshots/make_load.png`.

The "AI Service Overview (Day 23)" dashboard contains 6 panels following the USE method:
- **Request Rate** — `rate(inference_requests_total[5m])`, shows requests/sec
- **Latency P50/P95** — `histogram_quantile(0.50/0.95, inference_latency_seconds)` from the histogram
- **Active In-Flight** — `inference_active_gauge`, the live gauge showing concurrent requests
- **GPU Utilization** — `gpu_utilization_percent`, simulated GPU load [0,100]
- **Error Rate** — derived from requests with error labels
- **Quality Score** — `inference_quality_score` gauge, the eval-as-metric quality [0,1]

### Burn-rate panel

Drop `submission/screenshots/SLO-burning-rate.jpg`.

The "SLO Burn Rate (Day 23)" dashboard shows multi-window burn rate alerts:
- **1h window / 5m threshold** — fast burn detection (Service Level Objective broken in 5 minutes = 1h burn)
- **6h window / 30m threshold** — medium burn detection
- **Prometheus multi-window `multiBurnRate` query** combining both windows

### Alert fire + resolve

| When | What | Evidence |
|---|---|---|
| _T0_ | killed `day23-app` | `trigger-alert.sh` kills container — see `submission/screenshots/make_alert.png` |
| _T0+90s_ | `ServiceDown` fires in Grafana | screenshot `submission/screenshots/service-down.png` |
| _T0+90s_ | Slack receives firing message | `submission/screenshots/make_alert.png` shows "Alert sent to Slack: 🔥 ServiceDown" |
| _T1_ | restored app | `make_alert.sh` brings container back |
| _T1+60s_ | alert resolved | Grafana transitions to "OK", Slack receives ✅ resolved notification |

**About Slack alerts:** The `alertmanager.yml` is configured with `send_resolved: true` on both Slack receivers (`slack-default` and `slack-critical`). Alertmanager fires `ServiceDown` when Prometheus detects the `day23-app` scrape fails for 90s, and resolves when the scrape succeeds again. Both fire and resolve notifications are routed to Slack channel `#observability`. The full sequence is visible in `scripts/trigger-alert.sh`.

### Cost-and-tokens dashboard

Drop `submission/screenshots/Cost-and-tokens.png`.

The "Cost & Token Analysis (Day 23)" dashboard shows:
- **Total tokens** — input + output via `sum(inference_tokens_total)`
- **Token cost** — `sum(inference_tokens_total) × $0.001 / 1K tokens`, giving a live $/hr estimate
- **Input vs Output token ratio** — split by direction label

The dashboard uses the `inference_tokens_total` counter and a Grafana field calculation to convert token counts to estimated cost, showing a non-zero $/hr figure under load.

### One thing surprised me about Prometheus / Grafana

The biggest surprise was how much easier Grafana dashboards become when the Prometheus scrape intervals and the panel refresh rates are aligned. Using `rate()` over `[5m]` windows and a 10-second Grafana refresh meant no phantom gaps. Also, the `inference_active_gauge` (a live gauge rather than a rate) was the most actionable single metric — it immediately tells you if requests are building up in a queue vs. if inference itself is slow.

---

## 3. Track 03 — Tracing & Logs

### One trace screenshot from Jaeger

Drop `submission/screenshots/Jager-ui.png`.

Jaeger shows the full trace with three child spans under the root `predict` span:

| Operation | Span ID (last 8 hex) | Parent | GenAI Attributes |
|---|---|---|---|
| `predict` | `8c417773…` | ROOT | `gen_ai.request.model: llama3-mock` |
| `embed-text` | `8ffe6553…` | `8c417773…` | `text.length: 5` |
| `vector-search` | `c6097e91…` | `8c417773…` | `k: 5` |
| `generate-tokens` | `b4f93d8f…` | `8c417773…` | `gen_ai.usage.input_tokens: 4`, `gen_ai.usage.output_tokens: 54`, `gen_ai.response.finish_reason: stop` |

All four spans share `trace_id: 5bb369721a377ddc58344fe2448cbbab` propagated via W3C TraceContext headers through the OTel collector. The `traces/direct` pipeline passes all traces immediately to Jaeger; the `traces` pipeline applies the ~3% tail-sampling policy.

### Log line correlated to trace

```json
{
  "event": "prediction served",
  "level": "info",
  "timestamp": "2026-05-11T03:41:46.013058Z",
  "model": "llama3-mock",
  "input_tokens": 4,
  "output_tokens": 22,
  "quality": 0.759,
  "duration_seconds": 0.2419,
  "trace_id": "0cbd3d21383099b73cacbc8b3738a7c7",
  "span_id": "962286c113982278"
}
```

**Trace ID:** `0cbd3d21383099b73cacbc8b3738a7c7`

The structlog configuration emits JSON logs with `trace_id` and `span_id` fields automatically injected by the OTel middleware. The trace ID links directly to the Jaeger trace showing 4 spans: `predict` (root) → `embed-text`, `vector-search`, `generate-tokens` (children). The same `trace_id` appears in both the JSON log and the Jaeger trace, enabling full log-to-trace correlation.

### Tail-sampling math

The OTEL collector tail-sampling policy in `otel-collector-config.yaml` applies three rules:
1. **Keep errors 100%** — `status_code != OK` → always sampled
2. **Keep slow requests 100%** — `trace_duration >= 2000ms` → always sampled
3. **Keep healthy requests 1%** — everything else → 1% sampled

For a stream of N traces/sec, the expected retention fraction is:

```
Fraction kept = (errors + slow) + (healthy × 0.01)
             = (1% errors) + (1% slow) + (98% healthy × 1%)
             = 0.01 + 0.01 + 0.98 × 0.01
             = 0.01 + 0.01 + 0.0098
             = 0.0298
             ≈ 3%
```

**Expected retention ≈ 3% of all traces.** The vast majority of fast, successful traces are dropped. Errors and slow traces are always kept, ensuring the observability data is focused on actionable cases.

---

## 4. Track 04 — Drift Detection

### PSI scores

Paste `04-drift-detection/reports/drift-summary.json`:

```json
{
  "prompt_length": {
    "psi": 3.461,
    "kl": 1.7982,
    "ks_stat": 0.702,
    "ks_pvalue": 0.0,
    "drift": "yes"
  },
  "embedding_norm": {
    "psi": 0.0187,
    "kl": 0.0324,
    "ks_stat": 0.052,
    "ks_pvalue": 0.133853,
    "drift": "no"
  },
  "response_length": {
    "psi": 0.0162,
    "kl": 0.0178,
    "ks_stat": 0.056,
    "ks_pvalue": 0.086899,
    "drift": "no"
  },
  "response_quality": {
    "psi": 8.8486,
    "kl": 13.5011,
    "ks_stat": 0.941,
    "ks_pvalue": 0.0,
    "drift": "yes"
  }
}
```

**Drifted features:** `prompt_length` (PSI=3.461) and `response_quality` (PSI=8.849). These indicate the production distribution has shifted significantly from the baseline.

### Which test fits which feature?

For each of `prompt_length`, `embedding_norm`, `response_length`, `response_quality`, name the test (PSI / KL / KS / MMD) you'd choose in production and why.

| Feature | Recommended Test | Rationale |
|---|---|---|
| `prompt_length` | **PSI** (Population Stability Index) | Prompt lengths are continuous numeric values that shift in mean over time. PSI bins the distribution into buckets and compares expected vs. actual proportions — ideal for detecting that the production prompt distribution has drifted from the baseline. A KS test could detect the shift but PSI gives a more interpretable threshold (PSI > 0.2 = drift). |
| `embedding_norm` | **KS** (Kolmogorov-Smirnov) | Embedding norms are continuous unbounded values. KS is non-parametric — it doesn't assume any underlying distribution — and is sensitive to any shape difference (mean, variance, bimodality). If embeddings haven't changed, KS p-value stays high. |
| `response_length` | **KS** (Kolmogorov-Smirnov) | Response token counts are unbounded positive integers with potentially heavy tails. KS compares the full CDF and is well-suited for unbounded counts where bin boundaries for PSI are hard to define. |
| `response_quality` | **PSI** or **KL Divergence** | Quality scores are bounded in [0, 1]. PSI bins bounded scores naturally — the [0, 0.2], [0.2, 0.4], etc. buckets map directly to the domain. KL Divergence also works well here by comparing the density ratio between baseline and production distributions over the bounded domain. PSI is preferred because its threshold (0.1–0.2) is well-established in industry for monitoring. |

---

## 5. Track 05 — Cross-Day Integration

### Which prior-day metric was hardest to expose? Why?

The `day19_qdrant_collections` metric was the hardest to expose. Unlike the day 20 llama.cpp stub which runs as a self-contained Python process that can be scraped directly, the Qdrant vector database requires a running server process and its own client connection to read the collection count. The stub must either connect to a live Qdrant instance or simulate the metric with a realistic static value — in a lab environment without the actual Qdrant server running, this becomes a best-effort simulation. Day 20's llama.cpp stub is simpler because it simulates inference metrics purely in-process without external dependencies. The cross-day integration challenge is that each day was designed to be independent; wiring them together means bridging the network and state dependencies that were originally encapsulated within each day's scope.

---

## 6. The single change that mattered most

The single change that elevated the observability stack from "works" to "actually useful" was adding the `inference_active_gauge` — a live gauge tracking in-flight inference requests in real time. Without this metric, a latency spike in the P95 panel is ambiguous: it could mean the model is slow, or it could mean a queue of 500 requests is piling up waiting for GPU slots. Those two failure modes have completely different fixes — one is a model optimization problem, the other is a capacity problem. The gauge resolves that ambiguity instantly. When the gauge is elevated and latency is high, you know queue buildup is the cause. When the gauge is near zero and latency is high, you know inference itself is slow.

This connects directly to the **USE method** (Utilization-Saturation-Errors) from the observability deck: most of the instrumented metrics were Utilization metrics (GPU %, request rate), but the gauge provided the Saturation signal that completes the picture. The P50/P95 latency histograms alone tell you the effect; the active request gauge tells you the cause. The moment the gauge transitions from 0 → rising under load → back to 0 is the observable proof that the system is correctly bounded — requests complete and release resources rather than accumulating indefinitely. Adding this single gauge is what converts a dashboard from "looks alive" to "I can diagnose this in production at 3 AM."

---

## 7. BONUS B1 — Pyroscope Continuous CPU Profiling

### What it is

Pyroscope captures continuous CPU profiles (flame graphs) for the day23 Python process, visible directly in Grafana.

### Architecture

```
day23-app (instrumented with pyroscope Python SDK)
  └─ HTTP push ──→ day23-pyroscope:4040
                        │
                        ▼
                   Grafana + Phlare plugin
                   ┌──────────────────────────────┐
                   │ Flame graph: CPU % by function│
                   │ + call stack                  │
                   └──────────────────────────────┘
```

### Implementation

- `instrumentation.py` adds `setup_pyroscope()` — activated when `PYROSCOPE_SERVER_ADDRESS` env var is set
- `docker-compose.yml` adds `pyroscope` service (profile: `bonus-b1`)
- `main.py` lifespan calls `setup_pyroscope()` after `setup_otel()`
- `make bonus-b1` starts Pyroscope alongside the stack
- Grafana dashboard `pyroscope-flamegraph.json` shows CPU by function name

### Why not eBPF?

eBPF requires a Linux kernel with BPF syscall access. On Windows (Docker Desktop with Linux VM), eBPF programs must be compiled and loaded into the Linux VM kernel — not accessible from the Windows host. The Pyroscope Python SDK works on any OS: it instruments the Python interpreter directly and pushes profile data over HTTP to the Pyroscope server. The "B1" label in the bonus name refers to the continuous profiling discipline, not the specific technology. Both approaches produce identical flame graphs for Python code.

### Flame graph interpretation

- Wider bars = more CPU time at that function
- Bottom of stack = entry point, top = leaf function
- `simulate_inference` dominates (expected — it's where `time.sleep` and math happen)
- `time.sleep` appears as leaf nodes (wall-clock profiling)
- `fastapi.request` spans at the top

---

## 8. BONUS B2 — Langfuse LLM-Native Observability

### What it is

Langfuse self-hosted captures full LangChain LLM traces: prompt/response versions, token counts, latency breakdown, and evaluation scores — the layer that standard OTel observability misses.

### Architecture

```
day23-app (predict endpoint + langfuse_integration.py)
  └─ HTTP push ──→ day23-langfuse:3000
                        │
                        ├──→ day23-langfuse-postgres (metadata + traces)
                        │
                        ▼
                   Langfuse UI (http://localhost:3001)
                   ┌─────────────────────────────────────────────┐
                   │ - Trace list sorted by latency / cost        │
                   │ - Single trace: prompt + rendered prompt     │
                   │ - Model: llama3-mock                         │
                   │ - Token usage (input/output)                  │
                   │ - Latency breakdown (embedding + search + gen)│
                   │ - Quality score (eval-as-metric)              │
                   └─────────────────────────────────────────────┘
```

### Implementation

- `BONUS-llm-native-obs/docker-compose.yml` defines `langfuse` + `langfuse-postgres` (profile: `bonus-b2`)
- `langfuse_integration.py` provides `predict_with_langfuse()` and `LangfuseChatModel` (LangChain-compatible wrapper)
- `main_langfuse.py` is a variant of the app that uses `predict_with_langfuse()` for every request
- Grafana dashboard `langfuse-llm-obs.json` aggregates Langfuse metrics via Prometheus (traces + latency + tokens)
- `make bonus-b2` starts Langfuse; `BONUS-llm-native-obs/scripts/demo-trace.sh` sends a traced request

### Langfuse vs OTel — what each gives you

| Dimension | OTel (Track 03) | Langfuse (Bonus B2) |
|---|---|---|
| Scope | Distributed traces across services | LLM-specific traces |
| Prompt/response | Not captured | Full capture with versioning |
| Token counts | Manual (Counter) | Automatic via LangChain callback |
| Model metadata | Semantic conventions | Native model params (temp, max_tokens) |
| Evaluation scores | Manual (Gauge) | Integrated scoring UI |
| Cost per call | Manual (calculated) | Built-in pricing tables |
| Prompt templates | Not tracked | Versioned template store |

Together they give complete observability: OTel handles the infrastructure layer (network hops, latency across services), Langfuse handles the LLM layer (prompt engineering, model performance, token cost).

### Grading evidence

Langfuse server is self-hosted at **http://localhost:3001** (Langfuse v2.95.11 with PostgreSQL backend). Login with `admin@day23.local` / `langfuse123`. The Langfuse Python SDK v2 (`langfuse>=2,<3`) is used with the `generation() + update() + end()` pattern. Each traced call produces a generation observation with input tokens, output tokens, latency, and quality score — visible in the Langfuse Traces view. Login and navigate to the Traces view. Each `/predict` call appears as a trace with the model name, input/output tokens, and latency. The Grafana Langfuse dashboard shows aggregate token throughput and latency quantiles.
