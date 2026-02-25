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
    r"^[\s✶✷✸✹✺✻✼✽✾✿⏺⏵⏴⏹⏏⚡●○◉◎◌◐◑◒◓▪▫▸▹►▻\u2800-\u28FF·•]*$"
)
_STATUS_BAR_RE = re.compile(
    r"(worktree:|branch:|model:|ctx:|in:\d|out:\d|cache:\d|shift\+tab|accept edits)"
)
_PROMPT_RE = re.compile(r"^\s*[❯›>$#%]\s*$")

# OSC title sequence fragments that survive ANSI stripping
# (e.g., "0;⠐ Real-time Output Streaming" from split \x1b]0;...\x07)
_OSC_TITLE_RE = re.compile(r"^\d+;")

# Bare numbers with optional decorators (progress counters / step numbers)
# Matches: "2", "·  3", "  5 ", "· 12"
_BARE_NUMBER_RE = re.compile(r"^[·•.\s]*\d+[·•.\s]*$")

# Known TUI chrome / status labels that leak from terminal UI
_TUI_NOISE_RE = re.compile(
    r"Real-time Output Streaming|Streaming response",
    re.IGNORECASE,
)


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

    # OSC title sequence fragments (e.g., "0;⠐ Real-time Output Streaming")
    if _OSC_TITLE_RE.match(stripped):
        return True

    # Bare numbers / progress counters (e.g., "2", "·  3")
    if _BARE_NUMBER_RE.match(stripped):
        return True

    # Known TUI chrome text that leaks from terminal title / status bar
    if _TUI_NOISE_RE.search(stripped):
        return True

    return False


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
