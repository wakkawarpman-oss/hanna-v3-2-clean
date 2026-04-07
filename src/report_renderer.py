"""Reporting service facade for DiscoveryEngine."""
from __future__ import annotations

from typing import Any, Callable


class ReportRenderer:
    """Facade that hosts reporting responsibilities."""

    def __init__(self, hooks: dict[str, Callable[..., Any]]):
        self._hooks = hooks

    def get_stats(self, *args: Any, **kwargs: Any):
        return self._hooks["get_stats"](*args, **kwargs)

    def get_runs_dir(self, *args: Any, **kwargs: Any):
        return self._hooks["get_runs_dir"](*args, **kwargs)

    def get_lane_registry(self, *args: Any, **kwargs: Any):
        return self._hooks["get_lane_registry"](*args, **kwargs)

    def lane_from_source_tool(self, *args: Any, **kwargs: Any):
        return self._hooks["lane_from_source_tool"](*args, **kwargs)

    def load_latest_deep_recon_report(self, *args: Any, **kwargs: Any):
        return self._hooks["load_latest_deep_recon_report"](*args, **kwargs)

    def build_lane_summary(self, *args: Any, **kwargs: Any):
        return self._hooks["build_lane_summary"](*args, **kwargs)

    def render_graph_report(self, *args: Any, **kwargs: Any):
        return self._hooks["render_graph_report"](*args, **kwargs)
