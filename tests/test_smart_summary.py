from __future__ import annotations

import json

from smart_summary import summarize_payload, summarize_text


def test_smart_summary_cleans_html_and_extracts_observables():
    result = summarize_text(
        "Case Target",
        "<div>Password leaked for user@example.com and phone +380991234598</div><p>See https://example.com/leak</p>",
    )

    assert "<div>" not in result.cleaned_text
    assert result.observables["emails"] == ["user@example.com"]
    assert result.observables["phones"] == ["+380991234598"]
    assert result.observables["urls"] == ["https://example.com/leak"]
    assert result.summary


def test_smart_summary_emits_risk_flags_without_hallucinating():
    text = "Telegram dump contains login: operator and password: hunter2 near військова частина 301."

    result = summarize_text("Case Target", text)

    codes = {flag.code for flag in result.risk_flags}
    assert "credential_leak" in codes
    assert "military_association" in codes
    assert all(flag.evidence in result.cleaned_text for flag in result.risk_flags)


def test_smart_summary_payload_is_json_schema_like():
    payload = summarize_payload("Case Target", "Simple clean text without html")
    data = json.loads(payload)

    assert data["schema_version"] == 1
    assert data["target_name"] == "Case Target"
    assert isinstance(data["risk_flags"], list)
    assert isinstance(data["observables"], dict)