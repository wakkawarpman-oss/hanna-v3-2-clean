#!/usr/bin/env python3
"""Run the person-centric reconnaissance preset."""
from __future__ import annotations

import argparse

from pipelines.shared import run_preset


def main() -> None:
    parser = argparse.ArgumentParser(description="HANNA person recon pipeline")
    parser.add_argument("target")
    parser.add_argument("--phones", default="")
    parser.add_argument("--usernames", default="")
    parser.add_argument("--proxy", default=None)
    parser.add_argument("--leak-dir", default=None)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = run_preset(
        "person-deep",
        args.target,
        phones=[v.strip() for v in args.phones.split(",") if v.strip()],
        usernames=[v.strip() for v in args.usernames.split(",") if v.strip()],
        proxy=args.proxy,
        leak_dir=args.leak_dir,
        workers=args.workers,
    )
    for line in result.summary_lines():
        print(line)


if __name__ == "__main__":
    main()
