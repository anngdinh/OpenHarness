"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio

from lgharness.config.settings import Settings
from lgharness.model import build_model
from lgharness.engine.query_engine import QueryEngine
from lgharness.permissions.checker import PermissionChecker
from lgharness.permissions.modes import PermissionMode
from lgharness.ui.repl import run_repl


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="lgharness", description="LangGraph agent harness")
    parser.add_argument("--model", default=None, help="model id")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    parser.add_argument(
        "--permission-mode",
        default=None,
        choices=[m.value for m in PermissionMode],
        help="permission mode",
    )
    return parser


def app(argv: list[str] | None = None) -> int:
    """Parse args, build the engine, and run the REPL."""
    import os

    args = build_parser().parse_args(argv)
    settings = Settings.from_env(
        model=args.model,
        base_url=args.base_url,
        permission_mode=args.permission_mode,
    )
    if not settings.api_key:
        print("error: set OPENAI_API_KEY (and optionally OPENAI_BASE_URL).")
        return 1
    model = build_model(settings)
    engine = QueryEngine(model, PermissionChecker(settings.permission_mode), cwd=os.getcwd())
    asyncio.run(run_repl(engine))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(app())
