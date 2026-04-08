from __future__ import annotations

import html
import json
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RiskSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class RiskFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1)
    severity: RiskSeverity
    evidence: str = Field(..., min_length=1)


class SmartSummaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    target_name: str = Field(..., min_length=1)
    cleaned_text: str
    summary: str
    observables: dict[str, list[str]]
    risk_flags: list[RiskFlag] = Field(default_factory=list)


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)

_RISK_PATTERNS: list[tuple[str, RiskSeverity, list[str]]] = [
    (
        "credential_leak",
        RiskSeverity.high,
        ["password", "passwd", "credential", "login:", "api key", "token", "пароль", "логін"],
    ),
    (
        "military_association",
        RiskSeverity.high,
        ["military", "brigade", "battalion", "airfield", "arsenal", "військ", "бригада", "батальйон", "військова частина"],
    ),
    (
        "doxxing_contact_exposure",
        RiskSeverity.medium,
        ["phone", "email", "contact", "telegram", "телефон", "пошта"],
    ),
]


def summarize_text(target_name: str, raw_text: str) -> SmartSummaryResult:
    cleaned_text = _clean_text(raw_text)
    observables = {
        "phones": _unique(_PHONE_RE.findall(cleaned_text)),
        "emails": _unique(_EMAIL_RE.findall(cleaned_text)),
        "urls": _unique(_URL_RE.findall(cleaned_text)),
    }
    risk_flags = _extract_risk_flags(cleaned_text)
    summary = _build_summary(cleaned_text, observables, risk_flags)
    return SmartSummaryResult(
        target_name=target_name,
        cleaned_text=cleaned_text,
        summary=summary,
        observables=observables,
        risk_flags=risk_flags,
    )


def summarize_payload(target_name: str, raw_text: str) -> str:
    return json.dumps(summarize_text(target_name, raw_text).model_dump(mode="json"), ensure_ascii=False, indent=2)


def _clean_text(raw_text: str) -> str:
    unescaped = html.unescape(raw_text)
    no_tags = _HTML_TAG_RE.sub(" ", unescaped)
    normalized = _WHITESPACE_RE.sub(" ", no_tags).strip()
    return normalized


def _extract_risk_flags(cleaned_text: str) -> list[RiskFlag]:
    lowered = cleaned_text.lower()
    flags: list[RiskFlag] = []
    for code, severity, patterns in _RISK_PATTERNS:
        for pattern in patterns:
            idx = lowered.find(pattern)
            if idx == -1:
                continue
            start = max(0, idx - 40)
            end = min(len(cleaned_text), idx + len(pattern) + 60)
            evidence = cleaned_text[start:end].strip()
            flags.append(RiskFlag(code=code, severity=severity, evidence=evidence))
            break
    return flags


def _build_summary(cleaned_text: str, observables: dict[str, list[str]], risk_flags: list[RiskFlag]) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned_text) if part.strip()]
    selected: list[str] = []
    for sentence in sentences:
        if any(item in sentence for values in observables.values() for item in values):
            selected.append(sentence)
        elif any(flag.evidence in sentence for flag in risk_flags):
            selected.append(sentence)
        if len(selected) == 2:
            break
    if not selected:
        selected = sentences[:2]
    summary = " ".join(selected).strip()
    if not summary:
        summary = "No analyzable content extracted from the supplied text."
    return summary[:600]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items