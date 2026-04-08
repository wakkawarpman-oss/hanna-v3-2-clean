from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

import cli as cli_mod
from models import RunResult
from preflight import PreflightCheck


def test_cli_parser_accepts_export_flags_for_chain():
    parser = cli_mod._build_parser()
    args = parser.parse_args([
        "chain",
        "--target", "Target",
        "--export-formats", "json,metadata,stix,zip",
        "--export-dir", "/tmp/out",
        "--metadata-file", "/tmp/run.metadata.json",
        "--report-mode", "strict",
        "--json-summary-only",
    ])

    assert args.mode == "chain"
    assert args.export_formats == "json,metadata,stix,zip"
    assert args.export_dir == "/tmp/out"
    assert args.metadata_file == "/tmp/run.metadata.json"
    assert args.report_mode == "strict"
    assert args.json_summary_only is True


def test_cli_parser_accepts_preflight_json_summary_only():
    parser = cli_mod._build_parser()
    args = parser.parse_args(["preflight", "--modules", "ua_phone", "--json-only"])

    assert args.mode == "preflight"
    assert args.modules == "ua_phone"
    assert args.json_only is True


def test_cli_parser_accepts_reset_subcommand():
    parser = cli_mod._build_parser()
    args = parser.parse_args(["reset", "--confirm", "--json-only", "--output-file", "/tmp/reset.json"])

    assert args.mode == "reset"
    assert args.confirm is True
    assert args.json_only is True
    assert args.output_file == "/tmp/reset.json"


def test_cli_parser_accepts_list_json_summary_only():
    parser = cli_mod._build_parser()
    args = parser.parse_args(["list", "--json-only", "--output-file", "/tmp/list.json"])

    assert args.mode == "list"
    assert args.json_only is True
    assert args.output_file == "/tmp/list.json"


def test_cli_parser_accepts_manual_json_only_alias():
    parser = cli_mod._build_parser()
    args = parser.parse_args(["manual", "--module", "nuclei", "--target", "https://example.com", "--json-only"])

    assert args.mode == "manual"
    assert args.json_only is True


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


def test_cli_parser_accepts_short_aliases():
    parser = cli_mod._build_parser()

    assert parser.parse_args(["ls"]).mode == "ls"
    assert parser.parse_args(["pf"]).mode == "pf"
    assert parser.parse_args(["ui", "--plain"]).mode == "ui"
    assert parser.parse_args(["agg", "--target", "case"]).mode == "agg"
    assert parser.parse_args(["ch", "--target", "case"]).mode == "ch"
    assert parser.parse_args(["man", "--module", "nuclei", "--target", "https://example.com"]).mode == "man"
    assert parser.parse_args(["sum", "--target", "Case", "--text", "x"]).mode == "sum"
    assert parser.parse_args(["rs", "--confirm"]).mode == "rs"


def test_cli_main_dispatches_short_alias(monkeypatch, capsys):
    called = []

    def fake_list(_args):
        called.append("list")

    monkeypatch.setattr(cli_mod, "_cmd_list", fake_list)
    monkeypatch.setattr(sys, "argv", ["hanna", "ls"])

    cli_mod.main()

    assert called == ["list"]
    assert capsys.readouterr().out == ""


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


def test_export_result_artifacts_updates_runtime_summary_exports(monkeypatch, tmp_path):
    def _json_export(_result, output_dir):
        path = Path(output_dir) / "result.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def _metadata_export(metadata, output_dir, *, target_name, mode, timestamp, output_path=None):
        path = Path(output_path) if output_path else Path(output_dir) / "result.metadata.json"
        path.write_text(json.dumps({
            "metadata": metadata,
            "target_name": target_name,
            "mode": mode,
            "timestamp": timestamp,
        }), encoding="utf-8")
        return path

    monkeypatch.setattr(cli_mod, "export_run_result_json", _json_export)
    monkeypatch.setattr(cli_mod, "export_run_metadata_json", _metadata_export)

    result = RunResult(
        target_name="Case",
        mode="manual",
        started_at="2026-04-08T00:00:00",
        finished_at="2026-04-08T00:00:01",
        extra={"queued_modules": ["nuclei"]},
    )

    exported = cli_mod._export_result_artifacts(
        result=result,
        export_formats=["json", "metadata"],
        export_dir=str(tmp_path),
    )

    assert exported["json"].endswith("result.json")
    assert exported["metadata"].endswith("result.metadata.json")
    assert result.runtime_summary()["exports"] == ["json", "metadata"]

    payload = json.loads(Path(exported["metadata"]).read_text(encoding="utf-8"))
    assert payload["metadata"]["runtime_summary"]["mode"] == "manual"
    assert payload["metadata"]["artifacts"]["exports"]["json"].endswith("result.json")


def test_export_result_artifacts_respects_explicit_metadata_file(monkeypatch, tmp_path):
    def _metadata_export(metadata, output_dir, *, target_name, mode, timestamp, output_path=None):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata), encoding="utf-8")
        return path

    monkeypatch.setattr(cli_mod, "export_run_metadata_json", _metadata_export)

    result = RunResult(
        target_name="Case",
        mode="manual",
        started_at="2026-04-08T00:00:00",
        finished_at="2026-04-08T00:00:01",
        extra={"queued_modules": ["nuclei"]},
    )
    metadata_path = tmp_path / "nested" / "explicit.metadata.json"

    exported = cli_mod._export_result_artifacts(
        result=result,
        export_formats=["metadata"],
        export_dir=None,
        metadata_file=str(metadata_path),
    )

    assert exported["metadata"] == str(metadata_path)
    assert metadata_path.exists()


def test_print_runtime_summary_block_for_compact_json(capsys):
    result = RunResult(
        target_name="Case",
        mode="aggregate",
        started_at="2026-04-08T00:00:00",
        finished_at="2026-04-08T00:00:01",
        extra={"queued_modules": ["a", "b"], "report_mode": "strict", "exports": {"json": "/tmp/result.json"}},
    )

    cli_mod._print_runtime_summary_block(result)

    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == "Runtime summary JSON:"
    payload = json.loads(out[1])
    assert payload["mode"] == "aggregate"
    assert payload["exports"] == ["json"]


def test_print_runtime_summary_block_includes_new_error_kinds(capsys):
    result = RunResult(
        target_name="Case",
        mode="aggregate",
        errors=[
            {"module": "nuclei", "error": "missing binary: nuclei", "error_kind": "missing_binary"},
            {"module": "foo", "error": "dependency unavailable: broken dylib", "error_kind": "dependency_unavailable"},
            {"module": "bar", "error": "worker_crash: boom", "error_kind": "worker_crash"},
        ],
        started_at="2026-04-08T00:00:00",
        finished_at="2026-04-08T00:00:01",
        extra={"queued_modules": ["nuclei", "foo", "bar"]},
    )

    cli_mod._print_runtime_summary_block(result)

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[1])
    assert payload["missing_binary"] == 1
    assert payload["dependency_unavailable"] == 1
    assert payload["worker_crash"] == 1


def test_cmd_manual_json_summary_only_emits_compact_json(monkeypatch, capsys):
    class FakeRunner:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            print("noise from runner")
            return RunResult(
                target_name="Case",
                mode="manual",
                started_at="2026-04-08T00:00:00",
                finished_at="2026-04-08T00:00:01",
                extra={"queued_modules": ["ua_phone"]},
            )

    monkeypatch.setattr("runners.manual.ManualRunner", FakeRunner)
    monkeypatch.setattr(cli_mod, "_export_result_artifacts", lambda *args, **kwargs: {})

    args = argparse.Namespace(
        module="ua_phone",
        target="Case",
        phones=None,
        usernames=None,
        proxy=None,
        leak_dir=None,
        nuclei_profile=None,
        export_formats=None,
        export_dir=None,
        json_summary=False,
        json_summary_only=True,
        json_only=False,
    )

    cli_mod._cmd_manual(args)

    out = capsys.readouterr().out.strip().splitlines()
    assert out == ['{"target_name":"Case","mode":"manual","queued":1,"completed":0,"failed":0,"timed_out":0,"skipped_missing_credentials":0,"missing_binary":0,"dependency_unavailable":0,"worker_crash":0,"exports":[],"report_mode":null}']


def test_cmd_manual_json_summary_emits_block(monkeypatch, capsys):
    class FakeRunner:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            return RunResult(
                target_name="Case",
                mode="manual",
                started_at="2026-04-08T00:00:00",
                finished_at="2026-04-08T00:00:01",
                extra={"queued_modules": ["ua_phone"]},
            )

    monkeypatch.setattr("runners.manual.ManualRunner", FakeRunner)
    monkeypatch.setattr(cli_mod, "_export_result_artifacts", lambda *args, **kwargs: {})

    args = argparse.Namespace(
        module="ua_phone",
        target="Case",
        phones=None,
        usernames=None,
        proxy=None,
        leak_dir=None,
        nuclei_profile=None,
        export_formats=None,
        export_dir=None,
        json_summary=True,
        json_summary_only=False,
        json_only=False,
    )

    cli_mod._cmd_manual(args)

    out = capsys.readouterr().out.strip().splitlines()
    assert "Runtime summary JSON:" in out


def test_cmd_preflight_json_summary_only_emits_structured_json(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "run_preflight", lambda modules=None: [
        PreflightCheck(name="nuclei", status="ok", detail="/usr/local/bin/nuclei")
    ])

    args = argparse.Namespace(strict=False, modules="pd-infra", json_summary_only=False, json_only=True)

    cli_mod._cmd_preflight(args)

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["modules"] == ["pd-infra"]
    assert payload["summary"]["ok"] == 1
    assert payload["summary"]["has_hard_failures"] is False


def test_cmd_list_json_summary_only_emits_structured_json(monkeypatch, capsys):
    class FakeRunner:
        @staticmethod
        def list_modules():
            return [{"name": "nuclei", "region": "global", "lane": "fast", "doc": "ProjectDiscovery"}]

    monkeypatch.setattr("runners.manual.ManualRunner", FakeRunner)
    monkeypatch.setattr(cli_mod, "MODULE_PRESETS", {"pd-infra": ["nuclei", "katana"]})

    cli_mod._cmd_list(argparse.Namespace(json_summary_only=False, json_only=True, output_file=None))

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["modules"][0]["name"] == "nuclei"
    assert payload["presets"][0]["name"] == "pd-infra"


def test_cmd_reset_json_summary_only_emits_structured_json(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "reset_workspace", lambda **kwargs: {
        "removed": ["/tmp/discovery.db"],
        "missing": ["/tmp/runs/logs"],
    })

    cli_mod._cmd_reset(argparse.Namespace(
        db="/tmp/discovery.db",
        runs_root="/tmp/runs",
        keep_logs=False,
        keep_reports=False,
        keep_artifacts=False,
        confirm=True,
        json_summary_only=False,
        json_only=True,
        output_file=None,
    ))

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["db"] == "/tmp/discovery.db"
    assert payload["removed"] == ["/tmp/discovery.db"]
    assert payload["missing"] == ["/tmp/runs/logs"]


def test_cmd_list_json_only_can_write_output_file(monkeypatch, tmp_path, capsys):
    class FakeRunner:
        @staticmethod
        def list_modules():
            return [{"name": "nuclei", "region": "global", "lane": "fast", "doc": "ProjectDiscovery"}]

    monkeypatch.setattr("runners.manual.ManualRunner", FakeRunner)
    monkeypatch.setattr(cli_mod, "MODULE_PRESETS", {"pd-infra": ["nuclei"]})
    out_path = tmp_path / "list.json"

    cli_mod._cmd_list(argparse.Namespace(json_summary_only=False, json_only=True, output_file=str(out_path)))

    assert capsys.readouterr().out == ""
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["modules"][0]["name"] == "nuclei"


def test_cmd_reset_json_only_can_write_output_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_mod, "reset_workspace", lambda **kwargs: {"removed": ["/tmp/discovery.db"], "missing": []})
    out_path = tmp_path / "reset.json"

    cli_mod._cmd_reset(argparse.Namespace(
        db="/tmp/discovery.db",
        runs_root="/tmp/runs",
        keep_logs=False,
        keep_reports=False,
        keep_artifacts=False,
        confirm=True,
        json_summary_only=False,
        json_only=True,
        output_file=str(out_path),
    ))

    assert capsys.readouterr().out == ""
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["removed"] == ["/tmp/discovery.db"]