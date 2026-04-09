from __future__ import annotations

import pytest

from adapters.amass_adapter import AmassAdapter
from adapters.base import UnsupportedProxyError
from adapters.blackbird import BlackbirdAdapter
from adapters import cli_common
from adapters.nmap_adapter import NmapAdapter
from adapters.reconng import ReconNGAdapter
from adapters.shodan_adapter import ShodanAdapter
from adapters.subfinder_adapter import SubfinderAdapter
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


@pytest.mark.parametrize(
    ("adapter_cls", "target", "known_usernames", "expected_token"),
    [
        (ShodanAdapter, "example.com", [], "host"),
        (AmassAdapter, "example.com", [], "enum"),
        (SubfinderAdapter, "example.com", [], "-d"),
        (BlackbirdAdapter, "Case", ["operator_handle"], "blackbird"),
        (ReconNGAdapter, "Case", ["analyst@example.com"], "recon-ng"),
    ],
)
def test_cli_backed_adapters_forward_proxy_to_run_cli(monkeypatch, adapter_cls, target, known_usernames, expected_token):
    calls = []

    def _fake_run_cli(cmd, timeout, cwd=None, env=None, proxy=None, proxy_cli_flag=None):
        calls.append({
            "cmd": cmd,
            "proxy": proxy,
            "proxy_cli_flag": proxy_cli_flag,
        })

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()

    proxy = "socks5h://127.0.0.1:9050"
    module = __import__(adapter_cls.__module__, fromlist=[adapter_cls.__name__])
    monkeypatch.setattr(module, "run_cli", _fake_run_cli)
    if adapter_cls is ReconNGAdapter:
        monkeypatch.setattr(ReconNGAdapter, "_read_workspace_db", lambda self, db_path, seed: [])

    adapter = adapter_cls(proxy=proxy, timeout=1.0)
    adapter.search(target, [], known_usernames)

    assert calls
    assert calls[0]["proxy"] == proxy
    assert any(expected_token in str(part) for part in calls[0]["cmd"])


def test_nmap_rejects_proxy_routing_explicitly():
    adapter = NmapAdapter(proxy="socks5h://127.0.0.1:9050", timeout=1.0)

    with pytest.raises(UnsupportedProxyError, match="nmap cannot be executed safely"):
        adapter.search("example.com", [], [])
