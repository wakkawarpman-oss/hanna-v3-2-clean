#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_legacy_module():
    src_path = Path(__file__).resolve().parent / "src" / "run_discovery.py"
    spec = importlib.util.spec_from_file_location("hanna_legacy_run_discovery", src_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load legacy entrypoint from {src_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    _load_legacy_module().main()


if __name__ == "__main__":
    main()