"""Detect TASK and TASK_DONE markers in agent log files."""

from __future__ import annotations

import re
from pathlib import Path

from agent_fleet.session_manager import strip_ansi, clean_match

TASK_RE = re.compile(r"\|\|TASK:\s*(.+?)\|\|")
TASK_DONE_RE = re.compile(r"\|\|TASK_DONE:\s*(.+?)\|\|")

# Track file positions to avoid re-scanning the same content
_file_positions: dict[str, int] = {}


async def scan_log_for_tasks(store, agent_name: str, log_path: str) -> None:
    """Scan new content in a log file for TASK/TASK_DONE markers and upsert into the store."""
    path = Path(log_path)
    if not path.exists():
        return

    try:
        file_size = path.stat().st_size
    except OSError:
        return

    last_pos = _file_positions.get(log_path, 0)
    if file_size <= last_pos:
        if file_size < last_pos:
            # File was truncated (e.g. restart), reset
            _file_positions[log_path] = 0
            last_pos = 0
        else:
            return

    try:
        with open(path, "r", errors="replace") as f:
            f.seek(last_pos)
            new_content = f.read()
            _file_positions[log_path] = f.tell()
    except OSError:
        return

    clean = strip_ansi(new_content)

    for match in TASK_RE.finditer(clean):
        title = clean_match(match.group(1))
        if title:
            await store.create_agent_task_if_not_exists(agent_name, title)

    for match in TASK_DONE_RE.finditer(clean):
        title = clean_match(match.group(1))
        if title:
            await store.complete_agent_task_by_title(agent_name, title)
