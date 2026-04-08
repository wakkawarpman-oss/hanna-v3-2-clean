from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import os


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_run_discovery_wrapper_delegates(monkeypatch):
    module = _load_module(Path(__file__).resolve().parents[1] / "run_discovery.py", "root_run_discovery")
    called = []

    class _LegacyModule:
        @staticmethod
        def main():
            called.append("main")

    monkeypatch.setattr(module, "_load_legacy_module", lambda: _LegacyModule())

    module.main()

    assert called == ["main"]


def test_hanna_ui_normalizes_to_tui():
    module = _load_module(Path(__file__).resolve().parents[1] / "hanna_ui.py", "root_hanna_ui")

    assert module._normalized_argv(["--plain"]) == ["tui", "--plain"]
    assert module._normalized_argv(["ui", "--plain"]) == ["ui", "--plain"]
    assert module._normalized_argv(["tui", "--plain"]) == ["tui", "--plain"]


def test_hanna_ui_wrapper_delegates_to_cli(monkeypatch):
    module = _load_module(Path(__file__).resolve().parents[1] / "hanna_ui.py", "root_hanna_ui_delegate")
    observed = []

    class _CliModule:
        @staticmethod
        def main():
            import sys

            observed.append(list(sys.argv))

    monkeypatch.setattr(module, "_load_cli_module", lambda: _CliModule())

    module.main(["--plain"])

    assert observed and observed[0][1:] == ["tui", "--plain"]


def test_symlinked_hanna_wrapper_resolves_repo_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    link_path = tmp_path / "hanna"
    link_path.symlink_to(repo_root / "scripts" / "hanna")

    result = subprocess.run([str(link_path), "--help"], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert "HANNA OSINT" in result.stdout


def test_hanna_wrapper_sets_safe_term_for_tui_when_terminal_is_dumb(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    temp_root = tmp_path / "repo"
    scripts_dir = temp_root / "scripts"
    src_dir = temp_root / "src"
    venv_bin_dir = temp_root / ".venv" / "bin"
    scripts_dir.mkdir(parents=True)
    src_dir.mkdir(parents=True)
    venv_bin_dir.mkdir(parents=True)

    wrapper_source = (repo_root / "scripts" / "hanna").read_text(encoding="utf-8")
    wrapper_path = scripts_dir / "hanna"
    wrapper_path.write_text(wrapper_source, encoding="utf-8")
    wrapper_path.chmod(0o755)

    fake_python = venv_bin_dir / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'TERM=%s\\n' \"${TERM:-}\"\n"
        "printf 'ARGV=%s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    (src_dir / "cli.py").write_text("print('cli stub')\n", encoding="utf-8")

    env = os.environ.copy()
    env["TERM"] = "dumb"

    result = subprocess.run(
        [str(wrapper_path), "ui", "--plain"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "TERM=xterm-256color" in result.stdout
    assert str(src_dir / "cli.py") in result.stdout