from __future__ import annotations

import json

import pytest

from adapters.base import MissingCredentialsError
from adapters.hibp_adapter import HIBPAdapter


def test_hibp_adapter_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("HIBP_API_KEY", raising=False)

    adapter = HIBPAdapter(timeout=0.1)

    with pytest.raises(MissingCredentialsError, match="HIBP_API_KEY"):
        adapter.search("person@example.com", [], [])


def test_hibp_adapter_emits_breach_and_paste_hits(monkeypatch):
    monkeypatch.setenv("HIBP_API_KEY", "test-key")

    adapter = HIBPAdapter(timeout=0.1)

    def fake_fetch(url: str, headers: dict | None = None):
        assert headers is not None
        assert headers["hibp-api-key"] == "test-key"
        assert headers["user-agent"] == "HANNA/2026"
        if "/breachedaccount/" in url:
            return 200, json.dumps([
                {
                    "Name": "Adobe",
                    "Title": "Adobe",
                    "Domain": "adobe.com",
                    "BreachDate": "2013-10-04",
                    "AddedDate": "2013-12-04T00:00:00Z",
                    "DataClasses": ["Email addresses", "Passwords"],
                    "IsVerified": True,
                    "IsSensitive": False,
                    "IsMalware": False,
                    "IsStealerLog": False,
                }
            ])
        if "/pasteaccount/" in url:
            return 200, json.dumps([
                {
                    "Source": "Pastebin",
                    "Id": "abc123",
                    "Title": "dump",
                    "Date": "2026-04-08T10:00:00Z",
                    "EmailCount": 2,
                }
            ])
        return 404, ""

    monkeypatch.setattr(adapter, "_fetch", fake_fetch)

    hits = adapter.search("primary@example.com", [], ["secondary@example.com", "primary@example.com"])

    assert len(hits) == 4
    details = {hit.source_detail for hit in hits}
    assert "hibp:breach:Adobe@adobe.com" in details
    assert "hibp:paste:Pastebin:abc123" in details
    assert {hit.value for hit in hits} == {"primary@example.com", "secondary@example.com"}


def test_hibp_adapter_ignores_not_found(monkeypatch):
    monkeypatch.setenv("HIBP_API_KEY", "test-key")

    adapter = HIBPAdapter(timeout=0.1)
    monkeypatch.setattr(adapter, "_fetch", lambda url, headers=None: (404, ""))

    assert adapter.search("nobody@example.com", [], []) == []