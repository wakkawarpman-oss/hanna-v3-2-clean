"""CLI entrypoint wrapper for DiscoveryEngine."""
from __future__ import annotations


def run() -> int:
    from discovery_engine import _cli

    _cli()
    return 0
