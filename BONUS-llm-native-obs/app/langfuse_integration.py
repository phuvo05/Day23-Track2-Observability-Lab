"""Langfuse integration — wraps the mock inference with Langfuse v2 SDK tracing.

This module uses Langfuse Python SDK v2 (server-compatible) with the
generation() / update() / end() pattern for LLM tracing.

Usage:
    from langfuse_integration import predict_with_langfuse
    result = predict_with_langfuse("What is 2+2?", "llama3-mock")
    # → traces to http://localhost:3001
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

# Ensure the parent project modules are importable
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFERENCE_ROOT = PROJECT_ROOT / "01-instrument-fastapi" / "app"
sys.path.insert(0, str(INFERENCE_ROOT))

import structlog
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from inference import simulate_inference

log = structlog.get_logger("langfuse")

# ── Langfuse client ───────────────────────────────────────────────────

_langfuse_client = None


def _get_langfuse():
    """Lazy initialization of Langfuse v2 client."""
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client
    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3001"),
        )
        log.info(
            "langfuse v2 initialized",
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3001"),
        )
        return _langfuse_client
    except ImportError:
        log.warning("langfuse not installed — tracing disabled")
        return None


# ── LangChain CallbackHandler for Langfuse v2 ────────────────────────

class LangfuseCallbackHandler:
    """LangChain callback that traces LLM calls via Langfuse v2 SDK."""

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        pass

    def on_llm_end(
        self,
        response: ChatResult,
        *,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        pass

    def on_llm_error(
        self,
        error: Exception,
        *,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        pass


# ── LangChain ChatModel wrapper ────────────────────────────────────────

class LangfuseChatModel(BaseChatModel):
    """LangChain ChatModel that wraps simulate_inference() and emits Langfuse v2 traces."""

    model_name: str = Field(default="llama3-mock")
    temperature: float = Field(default=0.7)

    @property
    def _llm_type(self) -> str:
        return "langfuse-mock"

    def _generate(
        self,
        messages: list[BaseMessage],
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = messages[-1].content if messages else ""
        lf = _get_langfuse()

        gen = None
        if lf is not None:
            try:
                gen = lf.generation(
                    name="llm_generate",
                    input={"prompt": prompt, "model": self.model_name},
                    model=self.model_name,
                    metadata={"temperature": self.temperature},
                )
            except Exception as e:
                log.warning("langfuse generation start failed", error=str(e))

        start = time.perf_counter()
        text, in_toks, out_toks, quality = simulate_inference(prompt, self.model_name)
        elapsed = time.perf_counter() - start

        if gen is not None:
            try:
                gen.update(
                    output={"response": text, "finish_reason": "stop"},
                    usage_details={
                        "input_tokens": in_toks,
                        "output_tokens": out_toks,
                    },
                    metadata={
                        "quality_score": quality,
                        "latency_seconds": round(elapsed, 4),
                    },
                )
                gen.end()
            except Exception as e:
                log.warning("langfuse generation update/end failed", error=str(e))

        ai_message = AIMessage(content=text)
        generation_info = {
            "finish_reason": "stop",
            "input_tokens": in_toks,
            "output_tokens": out_toks,
            "quality": quality,
            "latency_seconds": round(elapsed, 4),
        }
        return ChatResult(
            generations=[ChatGeneration(message=ai_message, generation_info=generation_info)],
            llm_output={
                "token_usage": {
                    "input_tokens": in_toks,
                    "output_tokens": out_toks,
                    "total_tokens": in_toks + out_toks,
                },
                "model": self.model_name,
                "finish_reason": "stop",
            },
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[BaseMessage]:
        result = self._generate(messages, run_manager)
        yield result.generations[0].message


# ── Convenience API ───────────────────────────────────────────────────

def predict_with_langfuse(prompt: str, model: str = "llama3-mock") -> dict[str, Any]:
    """Call the mock LLM and trace the result to Langfuse v2.

    Uses generation() + update() + end() for LLM tracing.
    Returns a dict with the same shape as the FastAPI /predict response,
    plus Langfuse trace metadata.
    """
    lf = _get_langfuse()

    gen = None
    if lf is not None:
        try:
            gen = lf.generation(
                name="llm_predict",
                input={"prompt": prompt},
                model=model,
                metadata={"type": "generation"},
            )
        except Exception as e:
            log.warning("langfuse generation start failed", error=str(e))

    start = time.perf_counter()
    text, in_toks, out_toks, quality = simulate_inference(prompt, model)
    elapsed = time.perf_counter() - start

    response_data: dict[str, Any] = {
        "text": text,
        "model": model,
        "input_tokens": in_toks,
        "output_tokens": out_toks,
        "quality_score": quality,
        "latency_seconds": round(elapsed, 4),
    }

    if gen is not None and lf is not None:
        try:
            gen.update(
                output={"response": text, "finish_reason": "stop"},
                usage_details={
                    "input_tokens": in_toks,
                    "output_tokens": out_toks,
                },
                metadata={
                    "quality_score": quality,
                    "latency_seconds": round(elapsed, 4),
                },
            )
            gen.end()
            if gen.id:
                response_data["langfuse_observation_id"] = gen.id
            if gen.trace_id:
                response_data["langfuse_trace_id"] = gen.trace_id
                host = os.getenv("LANGFUSE_HOST", "http://localhost:3001")
                response_data["langfuse_trace_url"] = (
                    f"{host}/project/default/traces/{gen.trace_id}"
                )
        except Exception as e:
            log.warning("langfuse update/end failed", error=str(e))

    return response_data


if __name__ == "__main__":
    import json

    result = predict_with_langfuse("Explain why the sky is blue in one sentence.")
    print(json.dumps(result, indent=2, default=str))
