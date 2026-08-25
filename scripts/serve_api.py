#!/usr/bin/env python3
"""
Run the Analyst Copilot HTTP service.

    python scripts/serve_api.py
    python scripts/serve_api.py --reload
    API_PORT=9000 python scripts/serve_api.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import uvicorn  # noqa: E402

from analyst_copilot.api.config import get_api_settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    settings = get_api_settings()
    parser = argparse.ArgumentParser(description="Serve the Analyst Copilot API.")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="Reload on code changes.")
    parser.add_argument("--log-level", default="info")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(
        "analyst_copilot.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
