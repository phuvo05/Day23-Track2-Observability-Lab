"""Run the Pyroscope-profiled version of the day23 app.

Usage:
    # With Pyroscope server running:
    python main_profiled.py

    # Environment variables (can also be set in .env):
    PYROSCOPE_SERVER_ADDRESS=http://localhost:4040
    DEPLOY_ENV=lab
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the parent project modules are importable
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "01-instrument-fastapi" / "app"))

from main_profiled import app  # noqa: E402  (side-effect: starts pyroscope profiler)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
