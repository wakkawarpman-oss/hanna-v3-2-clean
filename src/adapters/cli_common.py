"""Shared helpers for CLI-based HANNA adapters."""
from __future__ import annotations

import os
import signal
import subprocess
from shutil import which
from pathlib import Path

from adapters.base import DependencyUnavailableError, MissingBinaryError
from config import CLI_TIMEOUT_SAFETY_MARGIN, MODULE_WORKER_TIMEOUT, REQUIRE_PROXY, WORKER_TIMEOUT


COMMON_BIN_DIRS: tuple[str, ...] = (
    str(Path.home() / "go" / "bin"),
    str(Path.home() / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
)


def _augment_path(path_value: str | None) -> str:
    """Append common user-level binary directories to PATH if missing."""
    parts = [p for p in (path_value or "").split(":") if p]
    for d in COMMON_BIN_DIRS:
        if d not in parts:
            parts.append(d)
    return ":".join(parts)


def _resolve_executable(exe: str, path_value: str) -> str:
    """Resolve executable name to an absolute path when possible."""
    if not exe or "/" in exe:
        return exe
    resolved = which(exe, path=path_value)
    if not resolved:
        raise MissingBinaryError(exe)
    return resolved


def resolve_cli_timeout(module_name: str, adapter_timeout: float, multiplier: float) -> float:
    """Bound subprocess timeout so it stays below the worker hard timeout."""
    worker_timeout = float(MODULE_WORKER_TIMEOUT.get(module_name, WORKER_TIMEOUT))
    desired = max(float(adapter_timeout), float(adapter_timeout) * float(multiplier))
    if worker_timeout <= CLI_TIMEOUT_SAFETY_MARGIN:
        return max(1.0, desired)
    return max(1.0, min(desired, worker_timeout - float(CLI_TIMEOUT_SAFETY_MARGIN)))


def kill_process_group(exc: subprocess.TimeoutExpired) -> None:
    """Kill the entire process group spawned by a timed-out subprocess."""
    try:
        pid = getattr(exc, "pid", None)
        if pid:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def run_cli(
    cmd: list[str],
    timeout: float,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    proxy: str | None = None,
    proxy_cli_flag: str | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run a CLI tool safely and return completed process or None when unavailable."""
    if REQUIRE_PROXY and not proxy:
        raise RuntimeError("HANNA_REQUIRE_PROXY=1 but no proxy provided for CLI execution")

    final_cmd = list(cmd)
    final_env = dict(os.environ)
    if env:
        final_env.update(env)
    final_env["PATH"] = _augment_path(final_env.get("PATH"))
    if final_cmd:
        final_cmd[0] = _resolve_executable(final_cmd[0], final_env["PATH"])

    if proxy:
        final_env.update({
            "HTTP_PROXY": proxy,
            "HTTPS_PROXY": proxy,
            "ALL_PROXY": proxy,
            "http_proxy": proxy,
            "https_proxy": proxy,
            "all_proxy": proxy,
        })
        if proxy_cli_flag and proxy_cli_flag not in final_cmd:
            final_cmd.extend([proxy_cli_flag, proxy])

    try:
        return subprocess.run(
            final_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,
            cwd=str(cwd) if cwd else None,
            env=final_env,
        )
    except subprocess.TimeoutExpired as exc:
        kill_process_group(exc)
        return subprocess.CompletedProcess(
            args=final_cmd,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=((exc.stderr or "") + "\n[timeout]"),
        )
    except FileNotFoundError as exc:
        raise MissingBinaryError(final_cmd[0] if final_cmd else "unknown") from exc
    except OSError as exc:
        raise DependencyUnavailableError(str(exc)) from exc
    return None
