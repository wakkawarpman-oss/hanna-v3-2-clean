#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_cli_module():
    src_path = Path(__file__).resolve().parent / "src" / "cli.py"
    spec = importlib.util.spec_from_file_location("hanna_operator_cli", src_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load CLI entrypoint from {src_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalized_argv(argv: list[str] | None = None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in (["tui"], ["ui"]):
        return args
    return ["tui", *args]


def main(argv: list[str] | None = None) -> None:
    cli_mod = _load_cli_module()
    original_argv = list(sys.argv)
    try:
        sys.argv = [original_argv[0], *_normalized_argv(argv)]
        cli_mod.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()