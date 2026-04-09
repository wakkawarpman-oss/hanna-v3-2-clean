"""Tests for discovery_engine.py — extraction, classification, normalization, entity resolution."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from adapters.base import ReconModuleOutcome, ReconReport

from discovery_engine import (
    DiscoveryEngine,
    Observable,
    _is_garbage_target,
    _normalize_domain,
    _normalize_phone,
    _shannon_entropy,
)


# ── _normalize_phone ──────────────────────────────────────────────

class TestNormalizePhone:
    def test_ua_with_plus(self):
        assert _normalize_phone("+380991234567") == "+380991234567"

    def test_ua_without_plus(self):
        assert _normalize_phone("380991234567") == "+380991234567"

    def test_us_formatted(self):
        assert _normalize_phone("+1-202-555-0173") == "+12025550173"

    def test_short_rejects(self):
        assert _normalize_phone("123") is None

    def test_spaces_stripped(self):
        assert _normalize_phone("+38 099 123 45 67") == "+380991234567"


# ── _normalize_domain ─────────────────────────────────────────────

class TestNormalizeDomain:
    def test_lowercase(self):
        assert _normalize_domain("Example.COM") == "example.com"

    def test_trailing_dot(self):
        assert _normalize_domain("example.com.") == "example.com"

    def test_ip_rejected(self):
        assert _normalize_domain("192.168.1.1") is None

    def test_too_short(self):
        assert _normalize_domain("a.b") is None


# ── _shannon_entropy ──────────────────────────────────────────────

class TestShannonEntropy:
    def test_empty(self):
        assert _shannon_entropy("") == 0.0

    def test_single_char(self):
        assert _shannon_entropy("aaa") == 0.0

    def test_high_entropy(self):
        # Random hex should be high entropy
        assert _shannon_entropy("a1b2c3d4e5f6789") > 3.5

    def test_low_entropy(self):
        assert _shannon_entropy("admin") < 3.0


# ── _is_garbage_target ────────────────────────────────────────────

class TestIsGarbageTarget:
    def test_empty(self):
        assert _is_garbage_target("") is True

    def test_single_char(self):
        assert _is_garbage_target("a") is True

    def test_valid_name(self):
        assert _is_garbage_target("Hanna Dosenko") is False


# ── DiscoveryEngine._infer_type ───────────────────────────────────

class TestInferType:
    @pytest.fixture(autouse=True)
    def engine(self, tmp_db):
        self.eng = DiscoveryEngine(db_path=tmp_db)

    def test_email(self):
        assert self.eng._infer_type("user@example.com") == "email"

    def test_phone(self):
        assert self.eng._infer_type("+380991234567") == "phone"

    def test_url(self):
        assert self.eng._infer_type("https://example.com/user") == "url"

    def test_domain(self):
        assert self.eng._infer_type("example.com") == "domain"

    def test_username(self):
        assert self.eng._infer_type("john_doe") == "username"

    def test_hex_hash_rejected(self):
        """Long hex strings should be rejected (likely SHA/MD5)."""
        assert self.eng._infer_type("a" * 32) is None

    def test_high_entropy_rejected(self):
        """Random token-like strings should be rejected."""
        assert self.eng._infer_type("xK9zQ2wR5tY8uI3o") is None


# ── DiscoveryEngine entity resolution (Union-Find) ───────────────

class TestEntityResolution:
    @pytest.fixture(autouse=True)
    def engine(self, tmp_db):
        self.eng = DiscoveryEngine(db_path=tmp_db)

    def _register(self, value: str, source: str = "test_tool", target: str = "test_target", is_original: bool = False) -> Observable | None:
        return self.eng._classify_and_register(
            value, source, target, "test.json", depth=0, is_original_target=is_original,
        )

    def test_single_observable(self):
        self._register("user@example.com", is_original=True)
        clusters = self.eng.resolve_entities()
        assert len(clusters) >= 1

    def test_corroboration_increments(self):
        """Same value from two different tools should increment corroboration_count."""
        self._register("user@example.com", source="tool_a")
        self._register("user@example.com", source="tool_b")
        row = self.eng.db.execute(
            "SELECT corroboration_count FROM observables WHERE value = ?",
            ("user@example.com",),
        ).fetchone()
        assert row is not None
        assert row[0] >= 1

    def test_tier_escalation(self):
        """After multiple corroborations, tier should escalate."""
        self._register("+380991234567", source="tool_a")
        self._register("+380991234567", source="tool_b")
        self._register("+380991234567", source="tool_c")
        row = self.eng.db.execute(
            "SELECT tier FROM observables WHERE value = ?",
            ("+380991234567",),
        ).fetchone()
        assert row is not None
        # After 3 registrations, corroboration_count >= 2 → probable
        assert row[0] in ("probable", "confirmed")

    def test_garbage_rejected(self):
        """Garbage values should not be registered."""
        obs = self._register("")
        assert obs is None

    def test_placeholder_domain_rejected(self):
        """Placeholder domains like example.com should be rejected."""
        obs = self._register("example.com")
        assert obs is None

    def test_same_business_record_links_push_cluster_confidence_above_threshold(self):
        phone = "+380991234598"
        target = "Test FOP Persona"
        ua = self.eng._classify_and_register(phone, "deep_recon:ua_phone", target, "ua.json", depth=0)
        fop = self.eng._classify_and_register(target, "deep_recon:opendatabot", target, "odb.json", depth=0, is_original_target=True)
        phone2 = self.eng._classify_and_register(phone, "deep_recon:opendatabot", target, "odb.json", depth=1)

        assert ua is not None
        assert fop is not None
        assert phone2 is not None

        self.eng._link_observables(fop, phone2, "same_business_record", 0.95)
        self.eng._link_observables(fop, ua, "same_business_record", 0.95)

        clusters = self.eng.resolve_entities()

        assert clusters
        assert clusters[0].confidence > 0.90


# ── Schema versioning ────────────────────────────────────────────

class TestSchemaVersioning:
    def test_schema_version_set(self, tmp_db):
        eng = DiscoveryEngine(db_path=tmp_db)
        version = eng.db.execute("PRAGMA user_version").fetchone()[0]
        assert version >= 1


class TestRenderGraphReport:
    @pytest.fixture(autouse=True)
    def engine(self, tmp_db):
        self.eng = DiscoveryEngine(db_path=tmp_db)

    def _register(self, value: str, source: str = "test_tool", target: str = "Hanna Dosenko", is_original: bool = False) -> Observable | None:
        return self.eng._classify_and_register(
            value,
            source,
            target,
            "test.json",
            depth=0,
            is_original_target=is_original,
        )

    def test_redacts_sensitive_values_by_default(self, tmp_path):
        self._register("Hanna Dosenko", is_original=True)
        self._register("+380991234567", source="ua_phone")
        self._register("user@example.com", source="ghunt")
        self.eng._record_rejected_target(
            "/Users/admin/private/meta.json",
            "+380991234567",
            "phone_profile_invalid_target",
        )

        self.eng.resolve_entities()
        out = tmp_path / "dossier.html"
        html = self.eng.render_graph_report(output_path=out)

        assert out.exists()
        assert out.read_text(encoding="utf-8") == html
        assert "+380991234567" not in html
        assert "user@example.com" not in html
        assert "Hanna Dosenko" not in html
        assert "Fast / Slow Lane Summary" in html
        assert "Rejected Targets" in html
        assert "phone_profile_invalid_target" in html

    def test_internal_mode_preserves_sensitive_values(self, tmp_path):
        self._register("Hanna Dosenko", is_original=True)
        self._register("+380991234567", source="ua_phone")
        self.eng.resolve_entities()

        html = self.eng.render_graph_report(
            output_path=tmp_path / "internal.html",
            redaction_mode="internal",
        )

        assert "Hanna Dosenko" in html
        assert "+380991234567" in html

    def test_invalid_redaction_mode_raises(self):
        with pytest.raises(ValueError):
            self.eng.render_graph_report(redaction_mode="unknown")


def test_run_deep_recon_summary_uses_report_outcomes(monkeypatch, tmp_db):
    import deep_recon as deep_recon_mod

    engine = DiscoveryEngine(db_path=tmp_db)

    report = ReconReport(
        target_name="Case",
        modules_run=["ua_leak", "ghunt"],
        hits=[],
        started_at="2026-04-09T00:00:00",
        finished_at="2026-04-09T00:00:01",
        outcomes=[
            ReconModuleOutcome(module_name="ua_leak", lane="fast"),
            ReconModuleOutcome(
                module_name="ghunt",
                lane="fast",
                error="missing credentials: GHUNT_CREDS_DIR",
                error_kind="missing_credentials",
            ),
        ],
        errors=[],
    )

    monkeypatch.setattr(
        deep_recon_mod.DeepReconRunner,
        "run",
        lambda self, **kwargs: report,
    )
    monkeypatch.setattr(
        deep_recon_mod.DeepReconRunner,
        "report_summary",
        staticmethod(lambda report: "summary"),
    )

    summary, returned_report = engine.run_deep_recon(target_name="Case", modules=["ua_leak", "ghunt"])

    assert returned_report is report
    assert summary["modules_run"] == ["ua_leak", "ghunt"]
    assert summary["outcomes"][1]["module_name"] == "ghunt"
    assert summary["outcomes"][1]["error_kind"] == "missing_credentials"
    assert summary["errors"] == [{
        "module": "ghunt",
        "error": "missing credentials: GHUNT_CREDS_DIR",
        "error_kind": "missing_credentials",
    }]
