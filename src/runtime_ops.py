from __future__ import annotations

import shutil
from pathlib import Path


def reset_workspace(
    db_path: str,
    runs_root: str,
    *,
    include_logs: bool = True,
    include_reports: bool = True,
    include_artifacts: bool = True,
) -> dict[str, object]:
    """Remove generated runtime state while preserving raw exports by default."""
    removed: list[str] = []
    missing: list[str] = []

    def _remove_path(path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            missing.append(str(path))
            return
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path))

    db_file = Path(db_path)
    _remove_path(db_file)

    root = Path(runs_root)
    if include_logs:
        _remove_path(root / "logs")
    if include_reports:
        _remove_path(root / "exports" / "html" / "dossiers")
    if include_artifacts:
        _remove_path(root / "exports" / "artifacts")

    return {
        "removed": removed,
        "missing": missing,
    }