from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import cli as cli_mod


def test_cli_parser_accepts_export_flags_for_chain():
    parser = cli_mod._build_parser()
    args = parser.parse_args([
        "chain",
        "--target", "Target",
        "--export-formats", "json,stix,zip",
        "--export-dir", "/tmp/out",
        "--report-mode", "strict",
    ])

    assert args.mode == "chain"
    assert args.export_formats == "json,stix,zip"
    assert args.export_dir == "/tmp/out"
    assert args.report_mode == "strict"


def test_cli_parser_accepts_reset_subcommand():
    parser = cli_mod._build_parser()
    args = parser.parse_args(["reset", "--confirm"])

    assert args.mode == "reset"
    assert args.confirm is True


def test_cli_parser_accepts_tui_subcommand():
    parser = cli_mod._build_parser()
    args = parser.parse_args([
        "tui",
        "--target", "Case Target",
        "--modules", "full-spectrum",
        "--run-mode", "aggregate",
        "--phones", "+380500000000",
        "--usernames", "caseuser",
        "--workers", "2",
        "--export-formats", "json,zip",
        "--report-mode", "strict",
        "--plain",
    ])

    assert args.mode == "tui"
    assert args.target == "Case Target"
    assert args.modules == "full-spectrum"
    assert args.run_mode == "aggregate"
    assert args.phones == "+380500000000"
    assert args.usernames == "caseuser"
    assert args.workers == 2
    assert args.export_formats == "json,zip"
    assert args.report_mode == "strict"
    assert args.plain is True


def test_cli_parser_accepts_summarize_subcommand():
    parser = cli_mod._build_parser()
    args = parser.parse_args([
        "summarize",
        "--target", "Case Target",
        "--text", "password leaked in <b>HTML</b>",
    ])

    assert args.mode == "summarize"
    assert args.target == "Case Target"
    assert args.text == "password leaked in <b>HTML</b>"


def test_cmd_summarize_requires_input():
    with pytest.raises(RuntimeError):
        cli_mod._cmd_summarize(argparse.Namespace(target="Case Target", text=None, input_file=None))


def test_parse_export_formats_rejects_invalid_value():
    with pytest.raises(ValueError):
        cli_mod._parse_export_formats("json,xml")


def test_cmd_reset_requires_confirm():
    with pytest.raises(RuntimeError):
        cli_mod._cmd_reset(argparse.Namespace(
            db="/tmp/db.sqlite",
            runs_root="/tmp/runs",
            keep_logs=False,
            keep_reports=False,
            keep_artifacts=False,
            confirm=False,
        ))


def test_export_result_artifacts_passes_chain_html_and_report_mode(monkeypatch, tmp_path):
    calls = []

    def _json_export(_result, output_dir):
        path = Path(output_dir) / "result.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def _stix_export(_result, output_dir):
        path = Path(output_dir) / "result.stix.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def _zip_export(_result, output_dir, html_path=None, report_mode=None):
        calls.append({"output_dir": str(output_dir), "html_path": html_path, "report_mode": report_mode})
        path = Path(output_dir) / "bundle.zip"
        path.write_text("zip", encoding="utf-8")
        return path

    monkeypatch.setattr(cli_mod, "export_run_result_json", _json_export)
    monkeypatch.setattr(cli_mod, "export_run_result_stix", _stix_export)
    monkeypatch.setattr(cli_mod, "export_run_result_zip", _zip_export)

    exported = cli_mod._export_result_artifacts(
        result=object(),
        export_formats=["json", "stix", "zip"],
        export_dir=str(tmp_path),
        html_path="/tmp/dossier.html",
        report_mode="strict",
    )

    assert exported["zip"].endswith("bundle.zip")
    assert calls == [{"output_dir": str(tmp_path), "html_path": "/tmp/dossier.html", "report_mode": "strict"}]