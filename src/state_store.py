"""Persistent state for API/MCP settings and rename rollback history."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

DB_PATH = Path("config/app_state.db")
API_DEFAULTS_PATH = Path("config/api_settings.yaml")
API_BASE_URL_ENV = "PDF_READER_API_BASE_URL"

API_SETTINGS_TABLE = "api_settings"
ROLLBACK_TABLE = "file_rollback_history"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_api_base_url_default(config_path: Path = API_DEFAULTS_PATH) -> str:
    env_value = os.getenv(API_BASE_URL_ENV, "").strip()
    if env_value:
        return env_value

    if not config_path.exists():
        return ""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return ""

    if not isinstance(loaded, dict):
        return ""
    return str(loaded.get("api_base_url") or "").strip()


@contextmanager
def _connect(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {API_SETTINGS_TABLE} (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                api_base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                api_model TEXT NOT NULL DEFAULT '',
                use_external_api INTEGER NOT NULL DEFAULT 0,
                mcp_server_name TEXT NOT NULL DEFAULT 'context7',
                mcp_server_url TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ROLLBACK_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                directory_path TEXT NOT NULL,
                before_name TEXT NOT NULL,
                after_name TEXT NOT NULL,
                changed_at TEXT NOT NULL
            )
            """
        )
        exists = conn.execute(
            f"SELECT 1 FROM {API_SETTINGS_TABLE} WHERE id = 1"
        ).fetchone()
        if not exists:
            conn.execute(
                f"""
                INSERT INTO {API_SETTINGS_TABLE}
                (id, api_base_url, api_key, api_model, use_external_api, mcp_server_name, mcp_server_url, updated_at)
                VALUES (1, '', '', '', 0, 'context7', '', ?)
                """,
                (_utc_now(),),
            )


def load_api_settings(db_path: Path = DB_PATH) -> dict:
    init_db(db_path)
    api_base_url_default = _load_api_base_url_default()
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {API_SETTINGS_TABLE} WHERE id = 1"
        ).fetchone()
    if row is None:
        return {
            "api_base_url": api_base_url_default,
            "api_key": "",
            "api_model": "",
            "use_external_api": False,
            "mcp_server_name": "context7",
            "mcp_server_url": "",
        }
    base_url = (row["api_base_url"] or "").strip() or api_base_url_default
    return {
        "api_base_url": base_url,
        "api_key": row["api_key"] or "",
        "api_model": row["api_model"] or "",
        "use_external_api": bool(row["use_external_api"]),
        "mcp_server_name": row["mcp_server_name"] or "context7",
        "mcp_server_url": row["mcp_server_url"] or "",
    }


def save_api_settings(settings: dict, db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            f"""
            UPDATE {API_SETTINGS_TABLE}
            SET
                api_base_url = ?,
                api_key = ?,
                api_model = ?,
                use_external_api = ?,
                mcp_server_name = ?,
                mcp_server_url = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                settings.get("api_base_url", "").strip(),
                settings.get("api_key", "").strip(),
                settings.get("api_model", "").strip(),
                1 if settings.get("use_external_api", False) else 0,
                settings.get("mcp_server_name", "context7").strip() or "context7",
                settings.get("mcp_server_url", "").strip(),
                _utc_now(),
            ),
        )


def log_rename(
    directory_path: Path,
    before_name: str,
    after_name: str,
    db_path: Path = DB_PATH,
) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {ROLLBACK_TABLE} (directory_path, before_name, after_name, changed_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(directory_path), before_name, after_name, _utc_now()),
        )


def get_recent_rename_logs(
    directory_path: Path,
    limit: int = 20,
    db_path: Path = DB_PATH,
) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, directory_path, before_name, after_name, changed_at
            FROM {ROLLBACK_TABLE}
            WHERE directory_path = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(directory_path), limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "directory_path": row["directory_path"],
            "before_name": row["before_name"],
            "after_name": row["after_name"],
            "changed_at": row["changed_at"],
        }
        for row in rows
    ]


def rollback_last_rename(directory_path: Path, db_path: Path = DB_PATH) -> tuple[bool, str]:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT id, before_name, after_name
            FROM {ROLLBACK_TABLE}
            WHERE directory_path = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(directory_path),),
        ).fetchone()
        if row is None:
            return False, "롤백 이력이 없습니다."

        before_name = row["before_name"]
        after_name = row["after_name"]
        current_path = directory_path / after_name
        restore_path = directory_path / before_name

        if not current_path.exists():
            return False, f"롤백할 수 없습니다. 현재 파일이 없습니다: {after_name}"
        if restore_path.exists():
            return False, f"롤백할 수 없습니다. 대상 이름이 이미 존재합니다: {before_name}"

        current_path.rename(restore_path)
        conn.execute(
            f"DELETE FROM {ROLLBACK_TABLE} WHERE id = ?",
            (row["id"],),
        )
    return True, f"롤백 완료: {after_name} -> {before_name}"
