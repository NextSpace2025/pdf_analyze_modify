"""Development runner: auto-restart app.py when source/config files change."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
POLL_INTERVAL_SEC = 0.7

WATCH_DIRS = [ROOT / "src", ROOT / "config", ROOT / "templates"]
WATCH_FILES = [ROOT / "app.py", ROOT / "main.py", ROOT / "requirements.txt"]
WATCH_SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".json", ".txt"}
IGNORE_DIRS = {"__pycache__", ".git", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


def _iter_watch_files() -> list[Path]:
    files: list[Path] = []

    for file_path in WATCH_FILES:
        if file_path.exists() and file_path.is_file():
            files.append(file_path)

    for watch_dir in WATCH_DIRS:
        if not watch_dir.exists() or not watch_dir.is_dir():
            continue
        for path in watch_dir.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in WATCH_SUFFIXES:
                files.append(path)

    # Preserve order and de-duplicate.
    unique_files: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        if path in seen:
            continue
        seen.add(path)
        unique_files.append(path)
    return unique_files


def _snapshot() -> dict[Path, int]:
    snap: dict[Path, int] = {}
    for path in _iter_watch_files():
        try:
            snap[path] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snap


def _changed_files(before: dict[Path, int], after: dict[Path, int]) -> list[Path]:
    changed: list[Path] = []
    all_paths = set(before) | set(after)
    for path in sorted(all_paths):
        if before.get(path) != after.get(path):
            changed.append(path)
    return changed


def _start_app() -> subprocess.Popen[bytes]:
    print("[dev] starting app.py")
    return subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=str(ROOT))


def _stop_app(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def main() -> None:
    print("[dev] watcher active (Ctrl+C to stop)")
    proc = _start_app()
    prev = _snapshot()

    try:
        while True:
            time.sleep(POLL_INTERVAL_SEC)
            now = _snapshot()
            changed = _changed_files(prev, now)
            if not changed:
                continue

            print("[dev] changed:")
            for p in changed[:8]:
                print(f"  - {p.relative_to(ROOT)}")
            if len(changed) > 8:
                print(f"  - ... and {len(changed) - 8} more")

            _stop_app(proc)
            proc = _start_app()
            prev = now
    except KeyboardInterrupt:
        print("\n[dev] stopping watcher")
    finally:
        _stop_app(proc)


if __name__ == "__main__":
    main()
