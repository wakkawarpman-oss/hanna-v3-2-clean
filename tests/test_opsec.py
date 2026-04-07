from __future__ import annotations

import pytest

from adapters import cli_common
from adapters.web_search import WebSearchAdapter
from net import proxy_aware_request


def test_run_cli_requires_proxy_when_enforced(monkeypatch):
    monkeypatch.setattr(cli_common, "REQUIRE_PROXY", True)
    with pytest.raises(RuntimeError):
        cli_common.run_cli(["python3", "-c", "print('ok')"], timeout=1.0)


def test_web_search_enforces_proxy_flag(monkeypatch):
    import adapters.web_search as ws_mod

    monkeypatch.setattr(ws_mod, "REQUIRE_PROXY", True)
    adapter = WebSearchAdapter(proxy=None, timeout=1.0)
    with pytest.raises(RuntimeError):
        adapter.search("target", [], [])


def test_proxy_aware_request_requires_proxy(monkeypatch):
    import net as net_mod

    monkeypatch.setattr(net_mod, "REQUIRE_PROXY", True)
    with pytest.raises(RuntimeError):
        proxy_aware_request("https://example.com", method="HEAD", timeout=1.0, proxy=None)
