"""Tests for deep_recon.py — ReconHit serialization, config integration."""
from __future__ import annotations

from deep_recon import ReconHit


class TestReconHitSerialization:
    def _sample_hit(self) -> ReconHit:
        return ReconHit(
            observable_type="phone",
            value="+380991234567",
            source_module="ua_leak",
            source_detail="test_leak_2024",
            confidence=0.85,
            raw_record={"name": "Test User", "city": "Kyiv"},
            timestamp="2026-04-06T12:00:00",
            cross_refs=["email:test@example.com"],
        )

    def test_to_dict_roundtrip(self):
        hit = self._sample_hit()
        d = hit.to_dict()
        restored = ReconHit.from_dict(d)
        assert restored.observable_type == hit.observable_type
        assert restored.value == hit.value
        assert restored.source_module == hit.source_module
        assert restored.confidence == hit.confidence
        assert restored.raw_record == hit.raw_record
        assert restored.cross_refs == hit.cross_refs

    def test_fingerprint(self):
        hit = self._sample_hit()
        assert hit.fingerprint == "phone:+380991234567"

    def test_from_dict_missing_optional_fields(self):
        minimal = {
            "observable_type": "email",
            "value": "user@example.com",
            "source_module": "sherlock",
            "source_detail": "profile",
            "confidence": 0.7,
        }
        hit = ReconHit.from_dict(minimal)
        assert hit.raw_record == {}
        assert hit.timestamp == ""
        assert hit.cross_refs == []

    def test_confidence_clamp(self):
        """Confidence values should remain within 0.0–1.0 boundary."""
        hit = self._sample_hit()
        assert 0.0 <= hit.confidence <= 1.0
