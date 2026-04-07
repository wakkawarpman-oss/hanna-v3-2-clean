from __future__ import annotations

from discovery_engine import DiscoveryEngine


def test_verify_profiles_uses_proxy_aware_request(monkeypatch, tmp_db):
    import discovery_engine as de_mod

    engine = DiscoveryEngine(db_path=tmp_db)
    engine.db.execute(
        "INSERT INTO profile_urls (username, platform, url, source_tool, status) VALUES (?, ?, ?, ?, ?)",
        ("alice", "github", "https://example.com/alice", "sherlock", "unchecked"),
    )
    engine.db.commit()

    calls: list[dict] = []

    def _fake_req(url, method="GET", timeout=5.0, proxy=None, headers=None, max_body_bytes=0):
        calls.append({"url": url, "method": method, "proxy": proxy})
        return 200, {"Content-Length": "1000"}, ""

    monkeypatch.setattr(de_mod, "proxy_aware_request", _fake_req)
    engine.verify_profiles(max_checks=10, timeout=1.0, proxy="socks5h://127.0.0.1:9050")

    status = engine.db.execute("SELECT status FROM profile_urls").fetchone()[0]
    assert status == "verified"
    assert calls and calls[0]["method"] == "HEAD"
    assert calls[0]["proxy"] == "socks5h://127.0.0.1:9050"
