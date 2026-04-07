"""
enums.py — Typed enumerations for HANNA OSINT pipeline.

Replaces string-typed tiers, statuses, and states with Enum classes.
"""

from __future__ import annotations

from enum import StrEnum


class Tier(StrEnum):
    """Observable confidence tier."""
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    UNVERIFIED = "unverified"


class VerificationStatus(StrEnum):
    """Profile URL verification status."""
    VERIFIED = "verified"
    SOFT_MATCH = "soft_match"
    DEAD = "dead"
    UNCHECKED = "unchecked"


class QueueState(StrEnum):
    """Discovery queue item state."""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"


class Lane(StrEnum):
    """Adapter execution lane."""
    FAST = "fast"
    SLOW = "slow"
