from __future__ import annotations

from pathlib import Path

from runtime_ops import reset_workspace


def test_reset_workspace_removes_generated_state(tmp_path):
    db_path = tmp_path / "discovery.db"
    db_path.write_text("db", encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "task.log").write_text("log", encoding="utf-8")

    reports_dir = tmp_path / "exports" / "html" / "dossiers"
    reports_dir.mkdir(parents=True)
    (reports_dir / "dossier.html").write_text("html", encoding="utf-8")

    artifacts_dir = tmp_path / "exports" / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "result.json").write_text("{}", encoding="utf-8")

    result = reset_workspace(str(db_path), str(tmp_path))

    assert not db_path.exists()
    assert not logs_dir.exists()
    assert not reports_dir.exists()
    assert not artifacts_dir.exists()
    assert any(path.endswith("discovery.db") for path in result["removed"])


def test_reset_workspace_preserves_selected_paths(tmp_path):
    db_path = tmp_path / "discovery.db"
    db_path.write_text("db", encoding="utf-8")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    reset_workspace(str(db_path), str(tmp_path), include_logs=False, include_reports=False, include_artifacts=False)

    assert not db_path.exists()
    assert logs_dir.exists()