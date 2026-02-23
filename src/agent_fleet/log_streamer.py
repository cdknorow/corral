"""Async log file tailing for WebSocket streaming."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator

from agent_fleet.session_manager import (
    STATUS_RE,
    SUMMARY_RE,
    strip_ansi,
    clean_match,
)

# Lines that are purely TUI chrome / noise after ANSI stripping
_BOX_LINE_RE = re.compile(r"^[\s─━═╌╍┄┅┈┉╴╶╸╺─]+$")
_SPINNER_RE = re.compile(
    r"^[\s✶✷✸✹✺✻✼✽✾✿⏺⏵⏴⏹⏏⚡●○◉◎◌◐◑◒◓▪▫▸▹►▻⣾⣽⣻⢿⡿⣟⣯⣷⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]*$"
)
_STATUS_BAR_RE = re.compile(
    r"(worktree:|branch:|model:|ctx:|in:\d|out:\d|cache:\d|shift\+tab|accept edits)"
)
_PROMPT_RE = re.compile(r"^\s*[❯›>$#%]\s*$")


def _is_noise_line(line: str) -> bool:
    """Return True if a line is TUI rendering noise that should be filtered."""
    stripped = line.strip()

    # Empty or whitespace-only
    if not stripped:
        return True

    # Box-drawing / horizontal rules
    if _BOX_LINE_RE.match(stripped):
        return True

    # Spinner-only lines
    if _SPINNER_RE.match(stripped):
        return True

    # Status bar fragments
    if _STATUS_BAR_RE.search(stripped):
        return True

    # Bare prompt characters
    if _PROMPT_RE.match(stripped):
        return True

    # Very short lines that are just punctuation/symbols (single stray chars)
    if len(stripped) <= 2 and not stripped.isalnum():
        return True

    return False


async def tail_log(
    log_path: str | Path,
    poll_interval: float = 0.5,
) -> AsyncGenerator[dict[str, str], None]:
    """Async generator that yields new log events as they appear.

    Yields dicts with keys:
      - type: "raw", "status", or "summary"
      - text: the content
    """
    log_path = Path(log_path)
    offset = 0

    # Start from current end of file
    try:
        offset = log_path.stat().st_size
    except OSError:
        pass

    while True:
        try:
            size = log_path.stat().st_size
            if size > offset:
                with open(log_path, "r", errors="replace") as f:
                    f.seek(offset)
                    new_data = f.read()
                offset = size

                text = strip_ansi(new_data)

                # Check for status/summary markers
                for m in STATUS_RE.finditer(text):
                    yield {"type": "status", "text": clean_match(m.group(1))}
                for m in SUMMARY_RE.finditer(text):
                    yield {"type": "summary", "text": clean_match(m.group(1))}

                # Send raw lines, filtering TUI noise
                for line in text.splitlines():
                    if not _is_noise_line(line):
                        yield {"type": "raw", "text": line}

            elif size < offset:
                # File was truncated (recreated), reset
                offset = 0
        except OSError:
            pass

        await asyncio.sleep(poll_interval)


def get_log_snapshot(log_path: str | Path, max_lines: int = 200) -> dict[str, Any]:
    """Return a snapshot of the current log state.

    Returns dict with: status, summary, recent_lines, staleness_seconds.
    """
    log_path = Path(log_path)
    result: dict[str, Any] = {
        "status": None,
        "summary": None,
        "recent_lines": [],
        "staleness_seconds": None,
    }

    try:
        raw = log_path.read_text(errors="replace")
        text = strip_ansi(raw)

        status_matches = STATUS_RE.findall(text)
        if status_matches:
            result["status"] = clean_match(status_matches[-1])

        summary_matches = SUMMARY_RE.findall(text)
        if summary_matches:
            result["summary"] = clean_match(summary_matches[-1])

        lines = [l for l in text.splitlines() if not _is_noise_line(l)]
        result["recent_lines"] = lines[-max_lines:]

        result["staleness_seconds"] = time.time() - log_path.stat().st_mtime
    except OSError:
        pass

    return result
