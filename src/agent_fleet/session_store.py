"""SQLite-backed storage for session notes, auto-summaries, and tags."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _extract_first_header(text: str) -> str:
    """Extract the first markdown header from text, or return empty string."""
    if not text:
        return ""
    m = re.search(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


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

                CREATE TABLE IF NOT EXISTS session_index (
                    session_id      TEXT PRIMARY KEY,
                    source_type     TEXT NOT NULL,
                    source_file     TEXT NOT NULL,
                    first_timestamp TEXT,
                    last_timestamp  TEXT,
                    message_count   INTEGER DEFAULT 0,
                    display_summary TEXT DEFAULT '',
                    indexed_at      TEXT NOT NULL,
                    file_mtime      REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_session_index_last_ts
                    ON session_index(last_timestamp DESC);

                CREATE TABLE IF NOT EXISTS summarizer_queue (
                    session_id   TEXT PRIMARY KEY,
                    status       TEXT DEFAULT 'pending',
                    attempted_at TEXT,
                    error_msg    TEXT
                );

                CREATE TABLE IF NOT EXISTS git_snapshots (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name        TEXT NOT NULL,
                    agent_type        TEXT NOT NULL DEFAULT 'claude',
                    working_directory TEXT NOT NULL,
                    branch            TEXT NOT NULL,
                    commit_hash       TEXT NOT NULL,
                    commit_subject    TEXT DEFAULT '',
                    commit_timestamp  TEXT,
                    session_id        TEXT,
                    recorded_at       TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_git_snap_dedup
                    ON git_snapshots(agent_name, commit_hash);

                CREATE INDEX IF NOT EXISTS idx_git_snap_agent
                    ON git_snapshots(agent_name, recorded_at DESC);

            """)
            # FTS5 virtual table — created separately because CREATE VIRTUAL TABLE
            # cannot be used inside executescript on all SQLite builds.
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
                        session_id UNINDEXED,
                        body,
                        tokenize='porter unicode61'
                    )
                """)
            except Exception:
                pass  # FTS5 may not be compiled in

            # Migrations for existing databases
            try:
                conn.execute("ALTER TABLE git_snapshots ADD COLUMN session_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.execute("CREATE INDEX IF NOT EXISTS idx_git_snap_session ON git_snapshots(session_id)")

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

    # ── Session Index ──────────────────────────────────────────────────────

    def upsert_session_index(
        self,
        session_id: str,
        source_type: str,
        source_file: str,
        first_timestamp: str | None,
        last_timestamp: str | None,
        message_count: int,
        display_summary: str,
        file_mtime: float,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO session_index
                   (session_id, source_type, source_file, first_timestamp, last_timestamp,
                    message_count, display_summary, indexed_at, file_mtime)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, source_type, source_file, first_timestamp, last_timestamp,
                 message_count, display_summary, now, file_mtime),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_fts(self, session_id: str, body: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM session_fts WHERE session_id = ?", (session_id,))
            conn.execute(
                "INSERT INTO session_fts (session_id, body) VALUES (?, ?)",
                (session_id, body),
            )
            conn.commit()
        except Exception:
            pass  # FTS5 may not be available
        finally:
            conn.close()

    def enqueue_for_summarization(self, session_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO summarizer_queue (session_id, status) VALUES (?, 'pending')",
                (session_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_summarized(self, session_id: str, status: str, error: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE summarizer_queue SET status = ?, attempted_at = ?, error_msg = ? WHERE session_id = ?",
                (status, now, error, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_pending_summaries(self, limit: int = 5) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT session_id FROM summarizer_queue WHERE status = 'pending' LIMIT ?",
                (limit,),
            ).fetchall()
            return [r["session_id"] for r in rows]
        finally:
            conn.close()

    def get_indexed_mtimes(self) -> dict[str, float]:
        """Return {source_file: file_mtime} for all indexed sessions."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT source_file, file_mtime FROM session_index"
            ).fetchall()
            result: dict[str, float] = {}
            for r in rows:
                # Keep the max mtime per file (a file can contain multiple sessions)
                existing = result.get(r["source_file"], 0.0)
                if r["file_mtime"] > existing:
                    result[r["source_file"]] = r["file_mtime"]
            return result
        finally:
            conn.close()

    def list_sessions_paged(
        self,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
        tag_id: int | None = None,
        source_type: str | None = None,
    ) -> dict[str, Any]:
        """Paginated session listing with optional full-text search, tag filter, and source filter."""
        conn = self._connect()
        try:
            params: list[Any] = []
            where_clauses: list[str] = []

            # Base: join session_index with optional metadata
            from_clause = "session_index si"
            select_fields = (
                "si.session_id, si.source_type, si.source_file, "
                "si.first_timestamp, si.last_timestamp, si.message_count, "
                "si.display_summary"
            )
            order_clause = "si.last_timestamp DESC"

            if search:
                from_clause += " JOIN session_fts fts ON fts.session_id = si.session_id"
                where_clauses.append("session_fts MATCH ?")
                params.append(search)
                order_clause = "rank"

            if tag_id is not None:
                where_clauses.append(
                    "si.session_id IN (SELECT session_id FROM session_tags WHERE tag_id = ?)"
                )
                params.append(tag_id)

            if source_type:
                where_clauses.append("si.source_type = ?")
                params.append(source_type)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Count total
            count_sql = f"SELECT COUNT(*) as cnt FROM {from_clause}{where_sql}"
            total = conn.execute(count_sql, params).fetchone()["cnt"]

            # Fetch page
            offset = (page - 1) * page_size
            query = (
                f"SELECT {select_fields} FROM {from_clause}{where_sql} "
                f"ORDER BY {order_clause} LIMIT ? OFFSET ?"
            )
            rows = conn.execute(query, params + [page_size, offset]).fetchall()

            session_ids = [r["session_id"] for r in rows]

            # Enrich with metadata (notes/tags)
            meta_map: dict[str, dict[str, Any]] = {}
            if session_ids:
                placeholders = ",".join("?" for _ in session_ids)
                meta_rows = conn.execute(
                    f"SELECT session_id, notes_md, auto_summary, is_user_edited "
                    f"FROM session_meta WHERE session_id IN ({placeholders})",
                    session_ids,
                ).fetchall()
                for r in meta_rows:
                    content = r["notes_md"] or r["auto_summary"] or ""
                    meta_map[r["session_id"]] = {
                        "has_notes": bool(r["notes_md"]) or bool(r["auto_summary"]),
                        "is_user_edited": bool(r["is_user_edited"]),
                        "summary_title": _extract_first_header(content),
                    }

                tag_rows = conn.execute(
                    f"SELECT st.session_id, t.id, t.name, t.color "
                    f"FROM session_tags st JOIN tags t ON t.id = st.tag_id "
                    f"WHERE st.session_id IN ({placeholders}) ORDER BY t.name",
                    session_ids,
                ).fetchall()
                tags_map: dict[str, list[dict[str, Any]]] = {}
                for r in tag_rows:
                    tags_map.setdefault(r["session_id"], []).append({
                        "id": r["id"], "name": r["name"], "color": r["color"],
                    })
            else:
                tags_map = {}

            sessions = []
            for r in rows:
                sid = r["session_id"]
                meta = meta_map.get(sid, {})
                sessions.append({
                    "session_id": sid,
                    "source_type": r["source_type"],
                    "source_file": r["source_file"],
                    "first_timestamp": r["first_timestamp"],
                    "last_timestamp": r["last_timestamp"],
                    "message_count": r["message_count"],
                    "summary": r["display_summary"],
                    "summary_title": meta.get("summary_title", ""),
                    "has_notes": meta.get("has_notes", False),
                    "tags": tags_map.get(sid, []),
                })

            return {
                "sessions": sessions,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    # ── Git Snapshots ─────────────────────────────────────────────────────

    def upsert_git_snapshot(
        self,
        agent_name: str,
        agent_type: str,
        working_directory: str,
        branch: str,
        commit_hash: str,
        commit_subject: str,
        commit_timestamp: str | None,
        session_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO git_snapshots
                   (agent_name, agent_type, working_directory, branch,
                    commit_hash, commit_subject, commit_timestamp, session_id, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_name, agent_type, working_directory, branch,
                 commit_hash, commit_subject, commit_timestamp, session_id, now),
            )
            # Always update branch/working_directory on the latest row for this agent
            # so get_latest_git_state reflects the current branch even without new commits
            update_params = [branch, working_directory, now]
            update_set = "branch = ?, working_directory = ?, recorded_at = ?"
            if session_id is not None:
                update_set += ", session_id = ?"
                update_params.append(session_id)
            update_params.extend([agent_name, commit_hash])
            conn.execute(
                f"""UPDATE git_snapshots
                   SET {update_set}
                   WHERE agent_name = ? AND commit_hash = ?""",
                update_params,
            )
            conn.commit()
        finally:
            conn.close()

    def get_git_snapshots(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT agent_name, agent_type, working_directory, branch,
                          commit_hash, commit_subject, commit_timestamp, session_id, recorded_at
                   FROM git_snapshots
                   WHERE agent_name = ?
                   ORDER BY recorded_at DESC
                   LIMIT ?""",
                (agent_name, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_latest_git_state(self, agent_name: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT agent_name, agent_type, working_directory, branch,
                          commit_hash, commit_subject, commit_timestamp, session_id, recorded_at
                   FROM git_snapshots
                   WHERE agent_name = ?
                   ORDER BY recorded_at DESC
                   LIMIT 1""",
                (agent_name,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_all_latest_git_state(self) -> dict[str, dict[str, Any]]:
        """Return {agent_name: {branch, commit_hash, ...}} for all agents."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT g.*
                   FROM git_snapshots g
                   INNER JOIN (
                       SELECT agent_name, MAX(recorded_at) as max_ts
                       FROM git_snapshots
                       GROUP BY agent_name
                   ) latest ON g.agent_name = latest.agent_name
                              AND g.recorded_at = latest.max_ts"""
            ).fetchall()
            return {r["agent_name"]: dict(r) for r in rows}
        finally:
            conn.close()

    def get_git_snapshots_for_session(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return git commits linked to a session by session_id or by time range."""
        conn = self._connect()
        try:
            # First: direct matches by session_id
            rows = conn.execute(
                """SELECT agent_name, agent_type, working_directory, branch,
                          commit_hash, commit_subject, commit_timestamp, session_id, recorded_at
                   FROM git_snapshots
                   WHERE session_id = ?
                   ORDER BY commit_timestamp ASC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]

            # Fallback: match by time range from session_index
            row = conn.execute(
                "SELECT first_timestamp, last_timestamp FROM session_index WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row or not row["first_timestamp"] or not row["last_timestamp"]:
                return []

            rows = conn.execute(
                """SELECT agent_name, agent_type, working_directory, branch,
                          commit_hash, commit_subject, commit_timestamp, session_id, recorded_at
                   FROM git_snapshots
                   WHERE commit_timestamp >= ? AND commit_timestamp <= ?
                   ORDER BY commit_timestamp ASC
                   LIMIT ?""",
                (row["first_timestamp"], row["last_timestamp"], limit),
            ).fetchall()
            return [dict(r) for r in rows]
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
