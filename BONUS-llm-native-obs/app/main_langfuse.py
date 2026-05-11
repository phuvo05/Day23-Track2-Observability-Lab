"""FastAPI app with Langfuse LLM tracing.

Run this alongside BONUS-llm-native-obs/docker-compose.yml.
The /predict endpoint uses LangfuseCallbackHandler for full LangChain tracing.

Usage:
    # Start Langfuse stack:
    cd BONUS-llm-native-obs && docker compose up -d

    # Start this app with Langfuse env vars:
    LANGFUSE_PUBLIC_KEY=sk-lf-local \
    LANGFUSE_SECRET_KEY=sk-lf-local \
    LANGFUSE_HOST=http://localhost:3001 \
    python main_langfuse.py

    # Or call the integration directly:
    python -c "from langfuse_integration import predict_with_langfuse; print(predict_with_langfuse('hello'))"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the parent project modules are importable
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "01-instrument-fastapi" / "app"))

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
from langfuse_integration import predict_with_langfuse


_log_singleton: structlog.BoundLogger | None = None


def _get_log() -> structlog.BoundLogger:
    global _log_singleton
    if _log_singleton is None:
        _log_singleton = bind_log("main-langfuse")
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
    langfuse_trace_id: str | None = None


app = FastAPI(title="day23-inference-api (langfuse-traced)")


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

            # Use Langfuse-traced inference
            langfuse_result = predict_with_langfuse(req.prompt, req.model)
            text = langfuse_result["text"]
            in_toks = langfuse_result["input_tokens"]
            out_toks = langfuse_result["output_tokens"]
            quality = langfuse_result["quality_score"]

            with tracer.start_as_current_span("generate-tokens") as s:
                s.set_attribute("gen_ai.usage.input_tokens", in_toks)
                s.set_attribute("gen_ai.usage.output_tokens", out_toks)
                s.set_attribute("gen_ai.response.finish_reason", "stop")

        INFERENCE_REQUESTS.labels(model=req.model, status="ok").inc()
        INFERENCE_TOKENS.labels(model=req.model, direction="input").inc(in_toks)
        INFERENCE_TOKENS.labels(model=req.model, direction="output").inc(out_toks)
        INFERENCE_QUALITY.labels(model=req.model).set(quality)

        elapsed = langfuse_result.get("latency_seconds", 0)
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
            langfuse_trace_id=langfuse_result.get("langfuse_trace_id"),
        )
        return PredictResponse(
            text=text,
            model=req.model,
            input_tokens=in_toks,
            output_tokens=out_toks,
            trace_id=trace_id,
            quality_score=quality,
            langfuse_trace_id=langfuse_result.get("langfuse_trace_id"),
        )
    except HTTPException:
        raise
    finally:
        INFERENCE_ACTIVE.dec()


if __name__ == "__main__":
    import uvicorn
    setup_otel()
    uvicorn.run(app, host="0.0.0.0", port=8001)
