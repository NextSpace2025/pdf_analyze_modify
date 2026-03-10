"""Non-UI services used by the desktop app."""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Thread

from src.ocr import extract_text
from src.ui.styles import PREVIEW_LENGTH


def normalize_unc(path_str: str) -> str:
    value = path_str.strip()
    if sys.platform == "win32":
        value = value.replace("/", "\\")
    return value


def safe_path(user_path: str) -> Path | None:
    if not user_path or not user_path.strip():
        return None
    raw = normalize_unc(user_path)
    try:
        path = Path(raw)
        if sys.platform == "win32" and raw.startswith("\\\\"):
            pass
        else:
            path = path.resolve()
        return path if path.exists() else None
    except (OSError, RuntimeError):
        return None


def analyze_one_file(pdf_path: Path, timeout_sec: int) -> dict:
    out: list[str | None] = [None]
    err: list[Exception | None] = [None]

    def run():
        try:
            out[0] = extract_text(pdf_path, lang="kor+eng")
        except Exception as exc:  # pragma: no cover - OCR environment dependent
            err[0] = exc

    worker = Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=timeout_sec)

    if worker.is_alive():
        return {
            "name": pdf_path.name,
            "path": pdf_path,
            "preview": "",
            "ok": False,
            "reason": f"Read timeout ({timeout_sec}s).",
        }
    if err[0]:
        reason = str(err[0]).strip() or type(err[0]).__name__
        if len(reason) > 220:
            reason = reason[:220] + "..."
        return {
            "name": pdf_path.name,
            "path": pdf_path,
            "preview": "",
            "ok": False,
            "reason": f"Analyze failed: {reason}",
        }

    text = out[0] or ""
    preview = (text[:PREVIEW_LENGTH] + "...") if len(text) > PREVIEW_LENGTH else text
    if text.strip():
        return {
            "name": pdf_path.name,
            "path": pdf_path,
            "preview": preview,
            "ok": True,
            "reason": "Extracted text successfully.",
        }
    return {
        "name": pdf_path.name,
        "path": pdf_path,
        "preview": "",
        "ok": False,
        "reason": "No text extracted from embedded text or OCR.",
    }


def analyze_folder(folder: Path, timeout_sec: int) -> list[dict]:
    files = [item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".pdf"]
    return [analyze_one_file(pdf_file, timeout_sec) for pdf_file in sorted(files)]


def delete_to_trash(file_path: Path) -> bool:
    try:
        import send2trash

        send2trash.send2trash(str(file_path))
        return True
    except Exception:  # pragma: no cover - OS integration dependent
        return False


def rename_file(file_path: Path, new_name: str) -> tuple[bool, str]:
    new_name = new_name.strip()
    if not new_name:
        return False, "Enter a filename."
    if "\\" in new_name or "/" in new_name or (sys.platform == "win32" and ":" in new_name):
        return False, "Provide only filename, not path."
    if not new_name.lower().endswith(".pdf"):
        new_name = f"{new_name}.pdf"

    new_path = file_path.parent / new_name
    if new_path == file_path:
        return False, "Same filename."
    if new_path.exists():
        return False, "A file with that name already exists."

    try:
        file_path.rename(new_path)
        return True, ""
    except OSError as exc:
        return False, str(exc)

