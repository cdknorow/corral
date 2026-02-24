"""SQLite-backed storage for session notes, auto-summaries, and tags."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DB_DIR = Path.home() / ".agent-fleet"
DB_PATH = DB_DIR / "sessions.db"


class SessionStore:
    """Synchronous SQLite store — call methods via asyncio.to_thread() from FastAPI."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS session_meta (
                    session_id   TEXT PRIMARY KEY,
                    notes_md     TEXT DEFAULT '',
                    auto_summary TEXT DEFAULT '',
                    is_user_edited INTEGER DEFAULT 0,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tags (
                    id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    name  TEXT UNIQUE NOT NULL,
                    color TEXT NOT NULL DEFAULT '#58a6ff'
                );

                CREATE TABLE IF NOT EXISTS session_tags (
                    session_id TEXT NOT NULL,
                    tag_id     INTEGER NOT NULL,
                    PRIMARY KEY (session_id, tag_id),
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                );
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Notes ───────────────────────────────────────────────────────────────

    def get_session_notes(self, session_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT notes_md, auto_summary, is_user_edited, updated_at "
                "FROM session_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row:
                return {
                    "notes_md": row["notes_md"],
                    "auto_summary": row["auto_summary"],
                    "is_user_edited": bool(row["is_user_edited"]),
                    "updated_at": row["updated_at"],
                }
            return {
                "notes_md": "",
                "auto_summary": "",
                "is_user_edited": False,
                "updated_at": None,
            }
        finally:
            conn.close()

    def save_session_notes(self, session_id: str, notes_md: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO session_meta (session_id, notes_md, is_user_edited, created_at, updated_at)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       notes_md = excluded.notes_md,
                       is_user_edited = 1,
                       updated_at = excluded.updated_at""",
                (session_id, notes_md, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def save_auto_summary(self, session_id: str, summary: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            # Only upsert if the user hasn't manually edited
            conn.execute(
                """INSERT INTO session_meta (session_id, auto_summary, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       auto_summary = excluded.auto_summary,
                       updated_at = excluded.updated_at
                   WHERE session_meta.is_user_edited = 0""",
                (session_id, summary, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Tags ────────────────────────────────────────────────────────────────

    def list_tags(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id, name, color FROM tags ORDER BY name").fetchall()
            return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]
        finally:
            conn.close()

    def create_tag(self, name: str, color: str = "#58a6ff") -> dict[str, Any]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO tags (name, color) VALUES (?, ?)", (name, color)
            )
            conn.commit()
            return {"id": cur.lastrowid, "name": name, "color": color}
        finally:
            conn.close()

    def delete_tag(self, tag_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            conn.commit()
        finally:
            conn.close()

    def get_session_tags(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT t.id, t.name, t.color
                   FROM session_tags st
                   JOIN tags t ON t.id = st.tag_id
                   WHERE st.session_id = ?
                   ORDER BY t.name""",
                (session_id,),
            ).fetchall()
            return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]
        finally:
            conn.close()

    def add_session_tag(self, session_id: str, tag_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO session_tags (session_id, tag_id) VALUES (?, ?)",
                (session_id, tag_id),
            )
            conn.commit()
        finally:
            conn.close()

    def remove_session_tag(self, session_id: str, tag_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM session_tags WHERE session_id = ? AND tag_id = ?",
                (session_id, tag_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Bulk queries for enriching history list ─────────────────────────────

    def get_all_session_metadata(self) -> dict[str, dict[str, Any]]:
        """Return {session_id: {tags: [...], has_notes: bool}} for all known sessions."""
        conn = self._connect()
        try:
            # Get all session notes info
            meta_rows = conn.execute(
                "SELECT session_id, notes_md, auto_summary, is_user_edited FROM session_meta"
            ).fetchall()

            result: dict[str, dict[str, Any]] = {}
            for r in meta_rows:
                has_notes = bool(r["notes_md"]) or bool(r["auto_summary"])
                result[r["session_id"]] = {
                    "has_notes": has_notes,
                    "is_user_edited": bool(r["is_user_edited"]),
                    "tags": [],
                }

            # Get all session tags
            tag_rows = conn.execute(
                """SELECT st.session_id, t.id, t.name, t.color
                   FROM session_tags st
                   JOIN tags t ON t.id = st.tag_id
                   ORDER BY t.name"""
            ).fetchall()

            for r in tag_rows:
                sid = r["session_id"]
                if sid not in result:
                    result[sid] = {"has_notes": False, "is_user_edited": False, "tags": []}
                result[sid]["tags"].append({
                    "id": r["id"],
                    "name": r["name"],
                    "color": r["color"],
                })

            return result
        finally:
            conn.close()
