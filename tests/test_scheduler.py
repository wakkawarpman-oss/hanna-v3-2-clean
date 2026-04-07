from __future__ import annotations

from adapters.base import ReconHit
from scheduler import dedup_and_confirm


def test_dedup_and_confirm_boosts_cross_confirmed_hits():
    h1 = ReconHit(
        observable_type="email",
        value="x@example.com",
        source_module="a",
        source_detail="a",
        confidence=0.4,
    )
    h2 = ReconHit(
        observable_type="email",
        value="x@example.com",
        source_module="b",
        source_detail="b",
        confidence=0.6,
    )

    deduped, cross = dedup_and_confirm([h1, h2])

    assert len(deduped) == 1
    assert len(cross) == 1
    assert cross[0].confidence > 0.6
