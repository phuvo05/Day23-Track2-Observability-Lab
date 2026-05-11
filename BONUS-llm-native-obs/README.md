# BONUS-llm-native-obs — Langfuse Self-Hosted LLM Observability

Langfuse captures LangChain LLM traces with full prompt/response versioning,
token usage, latency breakdown, and evaluation scores.

**Grading checkpoint (B2, +10 pts):** Langfuse self-hosted running, 1 LangChain LLM trace
captured with prompt, response, tokens, latency, and trace link visible in Langfuse UI.

**Stack:** Langfuse v2 (`langfuse/langfuse:2`) + PostgreSQL. No ClickHouse needed.

## Architecture

```
day23-app (instrumented with langfuse SDK)
  └─ HTTP push ──→ langfuse:3000 (inside Docker: http://langfuse-postgres:5432)
                        │
                        ├──→ PostgreSQL (langfuse metadata + traces)
                        │
                        ▼
                   Langfuse UI (http://localhost:3001)
                   ┌──────────────────────────────────┐
                   │ Trace list / single trace view    │
                   │ - prompt + rendered prompt         │
                   │ - model + response                │
                   │ - token usage (input/output)     │
                   │ - latency breakdown               │
                   │ - quality score (eval-as-metric)  │
                   └──────────────────────────────────┘
```

## Quick start

```bash
# Start Langfuse + PostgreSQL:
docker compose --profile bonus-b2 up -d
# Or from project root: make bonus-b2

# Wait ~30s for migrations, then visit:
# http://localhost:3001
# Login: admin@day23.local / langfuse123
```

## What gets traced

Langfuse traces every LLM call with:
- **Prompt:** raw input text
- **Response:** model output text
- **Token usage:** input and output token counts (from mock inference)
- **Latency:** total latency
- **Model metadata:** `model`, `temperature`, `max_tokens`
- **Quality score:** from mock inference

## Integration

- `BONUS-llm-native-obs/app/langfuse_integration.py` — `predict_with_langfuse()` + `LangfuseChatModel`
- `BONUS-llm-native-obs/app/main_langfuse.py` — variant FastAPI app using Langfuse tracing
- `requirements.txt` — `langfuse==3.2.1` (Python SDK, works with Langfuse v2 server)

## Langfuse vs OpenTelemetry

| Dimension | OTel (Track 03) | Langfuse (Bonus B2) |
|---|---|---|
| Scope | Distributed traces across services | LLM-specific traces |
| Prompt/response | Not captured | Full capture |
| Token counts | Manual (Counter) | Automatic via LangChain callback |
| Model metadata | Semantic conventions | Native model params |
| Evaluation scores | Manual (Gauge) | Integrated scoring UI |
