"""Prometheus + OTel + structlog wiring.

Single source of truth for the metric/span/log namespace.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram

# ── Prometheus metrics ────────────────────────────────────────
INFERENCE_REQUESTS = Counter(
    "inference_requests_total",
    "Total inference requests",
    ["model", "status"],
)
INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds",
    "Inference end-to-end latency",
    ["model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
INFERENCE_ACTIVE = Gauge(
    "inference_active_gauge",
    "In-flight inference requests",
)
INFERENCE_TOKENS = Counter(
    "inference_tokens_total",
    "Tokens processed (input/output)",
    ["model", "direction"],
)
INFERENCE_QUALITY = Gauge(
    "inference_quality_score",
    "Latest eval-as-metric quality score [0,1]",
    ["model"],
)
GPU_UTIL = Gauge(
    "gpu_utilization_percent",
    "Simulated GPU utilization [0,100]",
)

tracer = trace.get_tracer(__name__)


def setup_otel() -> None:
    """Configure OTLP trace export + FastAPI auto-instrumentation."""
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "inference-api"),
            "service.namespace": "aicb",
            "deployment.environment": os.getenv(
                "DEPLOY_ENV",
                "lab",
            ),
        }
    )
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    # Auto-instrument FastAPI handlers (creates server spans for every route)
    from fastapi import FastAPI  # local import: only needed at setup

    FastAPIInstrumentor().instrument()
    _configure_logging()


def _configure_logging() -> None:
    log_file = os.getenv("LOG_FILE")
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO"), logging.INFO)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        _file = open(log_file, "a", encoding="utf-8")

        class _FileLoggerFactory:
            """structlog factory that writes structured JSON to a shared file handle.
            Holds a single PrintLogger instance; cache ensures structlog.get_logger()
            returns the same logger object each time.
            """

            def __call__(self, _: str):
                if not hasattr(self, "_logger"):
                    self._logger = structlog.PrintLoggerFactory(file=_file)()
                return self._logger

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=_FileLoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=log_level,
        )
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )


# ── Global logger (initialized lazily on first use after setup_otel()) ─
_log_name: str | None = None


def bind_log(name: str) -> structlog.BoundLogger:
    """Return a structlog logger. Always calls get_logger() to pick up the
    current global config (configured by _configure_logging at startup)."""
    return structlog.get_logger(name)


# ── BONUS B1: Pyroscope continuous profiling ─────────────────────────
# Activated when PYROSCOPE_SERVER_ADDRESS is set.
# Python SDK sends CPU/Wall profiles to the Pyroscope server over HTTP.
# Works on any OS (Windows included) — Python instrumentation replaces eBPF.

def setup_pyroscope() -> bool:
    """Configure Pyroscope profiling if PYROSCOPE_SERVER_ADDRESS is set.

    Returns True if pyroscope is active, False otherwise.
    Call this after setup_otel() in the app lifespan.
    """
    import sys
    server = os.getenv("PYROSCOPE_SERVER_ADDRESS", "")
    print(f"[pyroscope] PYROSCOPE_SERVER_ADDRESS={server!r}", file=sys.stderr)
    if not server:
        return False
    try:
        import pyroscope_io
        pyroscope_io.configure(
            application_name="day23-app",
            server_address=server,
            sample_rate=100,
            oncpu=True,
            enable_logging=True,
            tags={
                "service": "inference-api",
                "environment": os.getenv("DEPLOY_ENV", "lab"),
            },
        )
        print("[pyroscope] configure() called successfully", file=sys.stderr)
        return True
    except ImportError:
        print("[pyroscope] pyroscope-io not installed", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[pyroscope] configure() failed: {e}", file=sys.stderr)
        return False
