#!/usr/bin/env python3
"""Run the infrastructure reconnaissance preset."""
from __future__ import annotations

import argparse

from pipelines.shared import run_preset


def main() -> None:
    parser = argparse.ArgumentParser(description="HANNA infra recon pipeline")
    parser.add_argument("target")
    parser.add_argument("--proxy", default=None)
    parser.add_argument("--leak-dir", default=None)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = run_preset("recon-auto", args.target, proxy=args.proxy, leak_dir=args.leak_dir, workers=args.workers)
    for line in result.summary_lines():
        print(line)


if __name__ == "__main__":
    main()
