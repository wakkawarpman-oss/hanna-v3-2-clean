"""EyeWitnessAdapter — screenshot and web surface capture via EyeWitness."""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from adapters.base import ReconAdapter, ReconHit
from adapters.cli_common import resolve_cli_timeout, run_cli
from config import EXPORTS_DIR


class EyewitnessAdapter(ReconAdapter):
    """Capture screenshots for discovered URLs and tag them in results."""

    name = "eyewitness"
    region = "global"

    def search(self, target_name: str, known_phones: list[str], known_usernames: list[str]) -> list[ReconHit]:
        urls = self._collect_urls(target_name, known_usernames)
        if not urls:
            return []
        return self._run_eyewitness(urls[:20])

    def _collect_urls(self, target_name: str, known_usernames: list[str]) -> list[str]:
        urls: list[str] = []
        for value in [target_name] + known_usernames:
            value = value.strip()
            if not value:
                continue
            if value.startswith(("http://", "https://")):
                urls.append(value)
            elif "." in value and " " not in value and "@" not in value:
                urls.append(f"https://{value}")
        return list(dict.fromkeys(urls))

    def _run_eyewitness(self, urls: list[str]) -> list[ReconHit]:
        eyewitness_bin = os.environ.get("EYEWITNESS_BIN", "")
        repo_root = Path(__file__).resolve().parents[2] / "tools" / "EyeWitness"
        repo_script = repo_root / "Python" / "EyeWitness.py"
        venv_python = repo_root / "eyewitness-venv" / "bin" / "python"
        env = os.environ.copy()
        chrome_bin = env.get("EYEWITNESS_CHROME_BIN", "").strip()
        if not chrome_bin:
            for candidate in [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                str(Path.home() / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"),
            ]:
                if Path(candidate).exists():
                    chrome_bin = candidate
                    break
        if chrome_bin:
            env["EYEWITNESS_CHROME_BIN"] = chrome_bin
        env.setdefault("PYTHONUNBUFFERED", "1")
        artifact_stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        persistent_root = EXPORTS_DIR / "artifacts" / f"eyewitness-{artifact_stamp}"
        with tempfile.TemporaryDirectory(prefix="hanna-eyewitness-") as tmpdir:
            url_file = Path(tmpdir) / "urls.txt"
            out_dir = Path(tmpdir) / "out"
            url_file.write_text("\n".join(urls), encoding="utf-8")
            cmd = [eyewitness_bin] if eyewitness_bin else []
            if venv_python.exists() and repo_script.exists() and not cmd:
                cmd = [str(venv_python), str(repo_script)]
            elif repo_script.exists() and not cmd:
                cmd = ["python3", str(repo_script)]
            elif not cmd:
                cmd = ["EyeWitness"]
            proc = run_cli(
                cmd + [
                    "--web",
                    "-f", str(url_file),
                    "--threads", "2",
                    "--max-retries", "1",
                    "--timeout", str(int(self.timeout)),
                    "--width", "1600",
                    "--height", "1000",
                    "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "--selenium-log-path", str(Path(tmpdir) / "chromedriver.log"),
                    "--no-prompt",
                    "-d", str(out_dir),
                ],
                timeout=resolve_cli_timeout(self.name, self.timeout, 25),
                cwd=repo_root / "Python",
                env=env,
                proxy=self.proxy,
            )
            if not proc:
                return []
            report = out_dir / "report.html"
            if not report.exists():
                return []
            persistent_root.parent.mkdir(parents=True, exist_ok=True)
            if persistent_root.exists():
                shutil.rmtree(persistent_root)
            shutil.copytree(out_dir, persistent_root)
            persistent_report = persistent_root / "report.html"
            html = persistent_report.read_text(encoding="utf-8", errors="replace")
            hits: list[ReconHit] = []
            for url in urls:
                if url in html:
                    hits.append(ReconHit(
                        observable_type="url",
                        value=url,
                        source_module=self.name,
                        source_detail="eyewitness:screenshot",
                        confidence=0.52,
                        raw_record={
                            "report": str(persistent_report),
                            "artifact_root": str(persistent_root),
                        },
                        timestamp=datetime.now().isoformat(),
                        cross_refs=[str(persistent_report), str(persistent_root)],
                    ))
            return hits