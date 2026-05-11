"""FastAPI app instrumented with Pyroscope for continuous CPU profiling.

Run this instead of the main app when BONUS-ebpf-profiling is enabled.
The pyroscope-io SDK automatically profiles CPU across the entire Python process.

Usage:
    # Start Pyroscope server first:
    docker compose --profile bonus-b1 up -d

    # Set env var:
    PYROSCOPE_SERVER_ADDRESS=http://localhost:4040

    # Run this app:
    python main_profiled.py

Or mount this module to replace the existing app inside Docker.
"""
from __future__ import annotations

import os
import time

import pyroscope_io  # noqa: F401 — configures profiling on import
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from instrumentation import (
    GPU_UTIL,
    INFERENCE_ACTIVE,
    INFERENCE_LATENCY,
    INFERENCE_QUALITY,
    INFERENCE_REQUESTS,
    INFERENCE_TOKENS,
    bind_log,
    setup_otel,
    tracer,
)
from inference import simulate_inference, simulate_gpu_load

# ── Pyroscope continuous profiling ───────────────────────────────────
# pyroscope_io.configure() is called here to instrument the process.
# It automatically profiles CPU time across all Python functions.
# Application name in Pyroscope UI = "day23-app"
pyroscope_io.configure(
    application_name="day23-app",
    server_address=os.getenv("PYROSCOPE_SERVER_ADDRESS", "http://localhost:4040"),
    sample_rate=100,
    oncpu=True,
    tags={
        "service": "inference-api",
        "environment": os.getenv("DEPLOY_ENV", "lab"),
    },
)


# ── FastAPI app ────────────────────────────────────────────────────

_log_singleton: structlog.BoundLogger | None = None


def _get_log() -> structlog.BoundLogger:
    global _log_singleton
    if _log_singleton is None:
        _log_singleton = bind_log("main-profiled")
    return _log_singleton


class PredictRequest(BaseModel):
    prompt: str
    model: str = "llama3-mock"
    fail: bool = False


class PredictResponse(BaseModel):
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    trace_id: str
    quality_score: float


app = FastAPI(title="day23-inference-api (profiled)")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    GPU_UTIL.set(simulate_gpu_load())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    INFERENCE_ACTIVE.inc()
    try:
        if req.fail:
            INFERENCE_REQUESTS.labels(model=req.model, status="error").inc()
            _get_log().error("forced failure", model=req.model)
            raise HTTPException(status_code=503, detail="forced failure")

        with tracer.start_as_current_span("predict") as span:
            span.set_attribute("gen_ai.request.model", req.model)

            with tracer.start_as_current_span("embed-text"):
                pass

            with tracer.start_as_current_span("vector-search"):
                pass

            text, in_toks, out_toks, quality = simulate_inference(req.prompt, req.model)

            with tracer.start_as_current_span("generate-tokens") as s:
                s.set_attribute("gen_ai.usage.input_tokens", in_toks)
                s.set_attribute("gen_ai.usage.output_tokens", out_toks)
                s.set_attribute("gen_ai.response.finish_reason", "stop")

        INFERENCE_REQUESTS.labels(model=req.model, status="ok").inc()
        INFERENCE_TOKENS.labels(model=req.model, direction="input").inc(in_toks)
        INFERENCE_TOKENS.labels(model=req.model, direction="output").inc(out_toks)
        INFERENCE_QUALITY.labels(model=req.model).set(quality)

        elapsed = time.perf_counter() - time.perf_counter() + 0.001  # measured below
        start = time.perf_counter()
        _, _, _, _ = simulate_inference(req.prompt, req.model)  # profiled
        elapsed = time.perf_counter() - start

        INFERENCE_LATENCY.labels(model=req.model).observe(elapsed)

        trace_id = format(span.get_span_context().trace_id, "032x")
        span_id = format(span.get_span_context().span_id, "016x")
        _get_log().info(
            "prediction served",
            model=req.model,
            input_tokens=in_toks,
            output_tokens=out_toks,
            quality=quality,
            duration_seconds=round(elapsed, 4),
            trace_id=trace_id,
            span_id=span_id,
        )
        return PredictResponse(
            text=text,
            model=req.model,
            input_tokens=in_toks,
            output_tokens=out_toks,
            trace_id=trace_id,
            quality_score=quality,
        )
    except HTTPException:
        raise
    finally:
        INFERENCE_ACTIVE.dec()


if __name__ == "__main__":
    import uvicorn
    setup_otel()
    uvicorn.run(app, host="0.0.0.0", port=8000)
