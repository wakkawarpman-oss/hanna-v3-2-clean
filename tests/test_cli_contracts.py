from __future__ import annotations

import argparse

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