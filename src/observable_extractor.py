"""Observable extraction service facade for DiscoveryEngine."""
from __future__ import annotations

from typing import Any, Callable


class ObservableExtractor:
    """Facade that hosts observable extraction responsibilities."""

    def __init__(self, hooks: dict[str, Callable[..., Any]]):
        self._hooks = hooks

    def extract_observables(self, *args: Any, **kwargs: Any):
        return self._hooks["extract_observables"](*args, **kwargs)

    def classify_and_register(self, *args: Any, **kwargs: Any):
        return self._hooks["classify_and_register"](*args, **kwargs)

    def infer_type(self, *args: Any, **kwargs: Any):
        return self._hooks["infer_type"](*args, **kwargs)

    def normalize(self, *args: Any, **kwargs: Any):
        return self._hooks["normalize"](*args, **kwargs)

    def extract_from_phone_log(self, *args: Any, **kwargs: Any):
        return self._hooks["extract_from_phone_log"](*args, **kwargs)

    def extract_from_username_log(self, *args: Any, **kwargs: Any):
        return self._hooks["extract_from_username_log"](*args, **kwargs)

    def extract_from_domain_log(self, *args: Any, **kwargs: Any):
        return self._hooks["extract_from_domain_log"](*args, **kwargs)

    def extract_generic(self, *args: Any, **kwargs: Any):
        return self._hooks["extract_generic"](*args, **kwargs)

    def platform_from_url(self, *args: Any, **kwargs: Any):
        return self._hooks["platform_from_url"](*args, **kwargs)
