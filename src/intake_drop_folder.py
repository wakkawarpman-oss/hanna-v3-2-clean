#!/usr/bin/env python3
"""
intake_drop_folder.py

Process a dropped folder with TXT/PDF/CSV files into HANNA metadata artifacts,
then optionally build a full HTML dossier via run_discovery.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import RUNS_ROOT

log = logging.getLogger("hanna.intake")


SUPPORTED_EXT = {".txt", ".csv", ".pdf"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf_file(path: Path) -> str:
    # Strategy 1: pypdf (if installed)
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        txt = "\n\n".join(pages).strip()
        if txt:
            return txt
    except Exception:
        pass

    # Strategy 2: pdftotext CLI (if present)
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    except Exception:
        pass

    return ""


def _extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".csv"}:
        return _read_text_file(path)
    if ext == ".pdf":
        return _read_pdf_file(path)
    return ""


def _default_runs_root() -> Path:
    return RUNS_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest dropped txt/pdf/csv folder and build HANNA HTML dossier"
    )
    parser.add_argument("--input-dir", required=True, help="Folder to ingest")
    parser.add_argument("--target", required=True, help="Primary target label")
    parser.add_argument(
        "--profile",
        default="username",
        help="Metadata profile tag for imported files (default: username)",
    )
    parser.add_argument(
        "--runs-root",
        default=str(_default_runs_root()),
        help="Runs root (default: ~/Desktop/ОСІНТ_ВИВІД/runs)",
    )
    parser.add_argument(
        "--mode",
        default="fast-lane",
        help="Deep recon preset for run_discovery (default: fast-lane)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Enable profile verification in run_discovery",
    )
    parser.add_argument(
        "--no-build-dossier",
        action="store_true",
        help="Only ingest files, skip run_discovery dossier build",
    )
    parser.add_argument(
        "--output-html",
        default="",
        help="Optional output HTML path for run_discovery",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="SOCKS5/HTTP proxy passed through to run_discovery",
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"ERROR: input dir not found: {input_dir}", file=sys.stderr)
        return 2

    runs_root = Path(args.runs_root).expanduser().resolve()
    exports_dir = runs_root / "exports"
    logs_dir = runs_root / "logs"
    html_dir = exports_dir / "html" / "dossiers"
    exports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    files = [
        p for p in sorted(input_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXT
    ]

    if not files:
        print(f"No supported files in {input_dir} (expected: txt/pdf/csv)")
        return 1

    imported = 0
    skipped = 0
    for idx, path in enumerate(files, start=1):
        extracted = _extract_text(path)
        if not extracted.strip():
            skipped += 1
            continue

        file_hash = _sha256_file(path)
        safe_stem = path.stem.replace(" ", "_")
        log_path = logs_dir / f"{ts}_intake_{idx:03d}_{safe_stem}.log"
        meta_path = exports_dir / f"{ts}_intake_{idx:03d}_{safe_stem}.json"

        header = [
            f"[INTAKE] source={path}",
            f"[INTAKE] target={args.target}",
            f"[INTAKE] profile={args.profile}",
            f"[INTAKE] sha256={file_hash}",
            "",
        ]
        log_path.write_text("\n".join(header) + extracted, encoding="utf-8")

        meta = {
            "target": args.target,
            "profile": args.profile,
            "status": "success",
            "label": f"intake:{path.suffix.lower().lstrip('.')}",
            "log_file": str(log_path),
            "sha256": file_hash,
            "source_file": str(path),
            "timestamp": datetime.now().isoformat(),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        imported += 1

    print(f"Ingested files: {imported}")
    print(f"Skipped files: {skipped}")
    print(f"Exports dir: {exports_dir}")

    if args.no_build_dossier:
        return 0

    output_html = args.output_html.strip()
    if not output_html:
        safe_target = args.target.strip().lower().replace(" ", "_")
        output_html = str(html_dir / f"{safe_target}_intake_{ts}.html")

    run_discovery = Path(__file__).resolve().parent / "run_discovery.py"
    cmd = [
        sys.executable,
        str(run_discovery),
        "--exports-dir",
        str(exports_dir),
        "--db",
        str(runs_root / "discovery.db"),
        "--target",
        args.target,
        "--mode",
        args.mode,
        "--output",
        output_html,
    ]
    if args.verify:
        cmd.append("--verify")
    if args.proxy:
        cmd.extend(["--proxy", args.proxy])

    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        print(f"run_discovery failed with code {proc.returncode}", file=sys.stderr)
        return proc.returncode

    print(f"HTML dossier: {output_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
