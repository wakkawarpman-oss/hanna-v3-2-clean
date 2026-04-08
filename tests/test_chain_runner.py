from __future__ import annotations

from pathlib import Path

from adapters.base import ReconHit, ReconReport
from runners.chain import ChainRunner


def test_chain_runner_populates_all_hits(monkeypatch, tmp_path):
    from discovery_engine import DiscoveryEngine

    render_calls = []

    hit = ReconHit(
        observable_type="email",
        value="user@example.com",
        source_module="ua_leak",
        source_detail="fixture",
        confidence=0.7,
    )
    report = ReconReport(
        target_name="target",
        modules_run=["ua_leak"],
        hits=[hit],
        errors=[],
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:00:01",
    )

    monkeypatch.setattr(DiscoveryEngine, "resolve_entities", lambda self: [])
    monkeypatch.setattr(DiscoveryEngine, "ingest_metadata", lambda self, _p: {"status": "skipped"})
    monkeypatch.setattr(DiscoveryEngine, "get_stats", lambda self: {"ok": True})
    def _render_graph_report(self, output_path, redaction_mode="shareable"):
        render_calls.append({"output_path": output_path, "redaction_mode": redaction_mode})
        Path(output_path).write_text("ok", encoding="utf-8")

    monkeypatch.setattr(DiscoveryEngine, "render_graph_report", _render_graph_report)
    monkeypatch.setattr(
        DiscoveryEngine,
        "run_deep_recon",
        lambda self, **_kwargs: (
            {
                "modules_run": ["ua_leak"],
                "new_observables": 1,
                "new_phones": [],
                "new_emails": ["user@example.com"],
                "errors": [],
            },
            report,
        ),
    )

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "dossier.html"

    runner = ChainRunner(db_path=str(tmp_path / "chain.db"))
    result = runner.run(
        exports_dir=str(exports_dir),
        target_name="target",
        modules=["ua_leak"],
        output_path=str(out),
    )

    assert result.all_hits
    assert result.all_hits[0].value == "user@example.com"
    assert out.exists()
    assert render_calls == [{"output_path": str(out), "redaction_mode": "shareable"}]


def test_chain_runner_passes_explicit_report_mode(monkeypatch, tmp_path):
    from discovery_engine import DiscoveryEngine

    render_calls = []

    monkeypatch.setattr(DiscoveryEngine, "resolve_entities", lambda self: [])
    monkeypatch.setattr(DiscoveryEngine, "ingest_metadata", lambda self, _p: {"status": "skipped"})
    monkeypatch.setattr(DiscoveryEngine, "get_stats", lambda self: {"ok": True})
    monkeypatch.setattr(
        DiscoveryEngine,
        "run_deep_recon",
        lambda self, **_kwargs: ({"modules_run": [], "new_observables": 0, "new_phones": [], "new_emails": [], "errors": []}, None),
    )

    def _render_graph_report(self, output_path, redaction_mode="shareable"):
        render_calls.append(redaction_mode)
        Path(output_path).write_text("ok", encoding="utf-8")

    monkeypatch.setattr(DiscoveryEngine, "render_graph_report", _render_graph_report)

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "dossier.html"

    runner = ChainRunner(db_path=str(tmp_path / "chain.db"))
    runner.run(
        exports_dir=str(exports_dir),
        output_path=str(out),
        report_mode="internal",
    )

    assert render_calls == ["internal"]


def test_chain_runner_exposes_runtime_summary(monkeypatch, tmp_path):
    from discovery_engine import DiscoveryEngine

    monkeypatch.setattr(DiscoveryEngine, "resolve_entities", lambda self: [])
    monkeypatch.setattr(DiscoveryEngine, "ingest_metadata", lambda self, _p: {"status": "skipped"})
    monkeypatch.setattr(DiscoveryEngine, "get_stats", lambda self: {"ok": True})
    monkeypatch.setattr(DiscoveryEngine, "render_graph_report", lambda self, output_path, redaction_mode="shareable": Path(output_path).write_text("ok", encoding="utf-8"))
    monkeypatch.setattr(
        DiscoveryEngine,
        "run_deep_recon",
        lambda self, **_kwargs: ({"modules_run": ["ua_leak", "ghunt"], "new_observables": 0, "new_phones": [], "new_emails": [], "errors": [{"module": "ghunt", "error": "missing credentials: GHUNT_CREDS_DIR", "error_kind": "missing_credentials"}]}, None),
    )

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "dossier.html"

    runner = ChainRunner(db_path=str(tmp_path / "chain.db"))
    result = runner.run(
        exports_dir=str(exports_dir),
        target_name="target",
        modules=["ua_leak", "ghunt"],
        output_path=str(out),
        report_mode="strict",
    )

    summary = result.runtime_summary()
    assert summary["queued"] == 2
    assert summary["completed"] == 1
    assert summary["skipped_missing_credentials"] == 1
    assert summary["report_mode"] == "strict"
