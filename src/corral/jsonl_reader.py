"""Efficient incremental JSONL reader for live Claude session transcripts."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from corral.utils import HISTORY_PATH

log = logging.getLogger(__name__)

PULSE_RE = re.compile(r"\|\|PULSE:\w+[^|]*\|\|")


@dataclass
class _SessionCache:
    path: Path | None = None
    offset: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    # Map tool_use_id → tool_name for labeling results
    tool_use_names: dict[str, str] = field(default_factory=dict)


def _encode_dir(directory: str) -> str:
    """Encode a working directory path to the Claude projects folder name."""
    return directory.replace("/", "-")


def _summarize_tool_input(name: str, inp: dict[str, Any]) -> str:
    """Compact summary of tool input for display."""
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return inp.get("file_path", inp.get("notebook_path", ""))
    if name == "Bash":
        cmd = inp.get("command", "")
        return cmd[:120] + ("..." if len(cmd) > 120 else "")
    if name in ("Grep", "Glob"):
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        return f"{pattern}" + (f" in {path}" if path else "")
    if name == "Agent":
        return inp.get("description", inp.get("prompt", ""))[:120]
    if name in ("TaskCreate", "TaskUpdate"):
        return inp.get("subject", inp.get("taskId", ""))
    if name == "WebSearch":
        return inp.get("query", "")
    if name == "WebFetch":
        return inp.get("url", "")
    # Fallback: first string value
    for v in inp.values():
        if isinstance(v, str) and v:
            return v[:100]
    return ""


def _parse_entry(
    entry: dict[str, Any], cache: _SessionCache | None = None
) -> list[dict[str, Any]] | dict[str, Any] | None:
    """Convert a raw JSONL entry into normalized frontend message(s).

    When *cache* is provided, tool_use_id → tool_name mapping is used to
    label tool_result messages.  May return a list of messages when a user
    entry contains multiple tool_results.
    """
    etype = entry.get("type")
    timestamp = entry.get("timestamp", "")

    if etype == "user":
        msg = entry.get("message", {})
        content = msg.get("content", "")
        # User messages can be a string or list with tool_result blocks
        if isinstance(content, list):
            text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
            results: list[dict[str, Any]] = []
            for b in content:
                if b.get("type") == "tool_result":
                    tool_use_id = b.get("tool_use_id", "")
                    result_content = b.get("content", "")
                    is_error = b.get("is_error", False)
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            p.get("text", "") for p in result_content if p.get("type") == "text"
                        )
                    if not result_content:
                        continue
                    # Truncate very long results
                    if len(result_content) > 10000:
                        result_content = result_content[:10000] + "\n... (truncated)"
                    # Look up tool name from cache
                    tool_name = ""
                    if cache and tool_use_id:
                        tool_name = cache.tool_use_names.get(tool_use_id, "")
                    results.append({
                        "type": "tool_result",
                        "timestamp": timestamp,
                        "content": result_content,
                        "tool_name": tool_name,
                        "tool_use_id": tool_use_id,
                        "is_error": is_error,
                    })
            if results:
                return results
            # Otherwise treat as normal user text
            if not text_parts:
                return None
            content = "\n".join(text_parts)
        if not content.strip():
            return None
        return {"type": "user", "timestamp": timestamp, "content": content}

    if etype == "assistant":
        msg = entry.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, str):
            text = content
            tool_uses = []
        elif isinstance(content, list):
            text_parts = []
            tool_uses = []
            for block in content:
                bt = block.get("type")
                if bt == "text":
                    text_parts.append(block.get("text", ""))
                elif bt == "tool_use":
                    tool_name = block.get("name", "")
                    tool_use_id = block.get("id", "")
                    tool_input = block.get("input", {})
                    tool_entry: dict[str, Any] = {
                        "name": tool_name,
                        "tool_use_id": tool_use_id,
                        "input_summary": _summarize_tool_input(tool_name, tool_input),
                    }
                    # Include full command and description for Bash
                    if tool_name == "Bash":
                        tool_entry["command"] = tool_input.get("command", "")
                        desc = tool_input.get("description", "")
                        if desc:
                            tool_entry["description"] = desc
                    # Include structured question data for AskUserQuestion
                    elif tool_name == "AskUserQuestion":
                        questions = tool_input.get("questions", [])
                        if questions:
                            tool_entry["questions"] = questions
                    # Include diff data for Edit tools
                    elif tool_name == "Edit":
                        old = tool_input.get("old_string", "")
                        new = tool_input.get("new_string", "")
                        if old or new:
                            tool_entry["old_string"] = old
                            tool_entry["new_string"] = new
                    # Include content for Write tools
                    elif tool_name == "Write":
                        content_str = tool_input.get("content", "")
                        if content_str:
                            if len(content_str) > 10000:
                                content_str = content_str[:10000] + "\n... (truncated)"
                            tool_entry["write_content"] = content_str
                    tool_uses.append(tool_entry)
            text = "\n".join(text_parts)
        else:
            return None

        # Strip PULSE markers from text
        text = PULSE_RE.sub("", text).strip()

        if not text and not tool_uses:
            return None

        return {
            "type": "assistant",
            "timestamp": timestamp,
            "text": text,
            "tool_uses": tool_uses,
        }

    # Skip file-history-snapshot, progress, etc.
    return None


class JsonlSessionReader:
    """Incrementally reads JSONL session files for live chat display."""

    def __init__(self) -> None:
        self._cache: dict[str, _SessionCache] = {}

    def _resolve_path(self, session_id: str, working_directory: str = "") -> Path | None:
        """Find the JSONL file for a session. Uses working_directory hint for fast lookup."""
        # Try direct path using encoded working directory
        if working_directory:
            encoded = _encode_dir(working_directory)
            candidate = HISTORY_PATH / encoded / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate

        # Fallback: search all project directories
        for jsonl_path in HISTORY_PATH.rglob(f"{session_id}.jsonl"):
            return jsonl_path

        return None

    def read_new_messages(
        self, session_id: str, working_directory: str = ""
    ) -> tuple[list[dict[str, Any]], int]:
        """Read new messages since last call.

        Returns (new_messages, total_count).
        """
        cache = self._cache.get(session_id)
        if cache is None:
            cache = _SessionCache()
            self._cache[session_id] = cache

        # Resolve path on first call or if not found yet
        if cache.path is None:
            cache.path = self._resolve_path(session_id, working_directory)
            if cache.path is None:
                return [], 0

        # Read new data from file
        try:
            with open(cache.path, "r", errors="replace") as f:
                f.seek(cache.offset)
                new_data = f.read()
                cache.offset = f.tell()
        except OSError:
            return [], len(cache.messages)

        if not new_data:
            return [], len(cache.messages)

        # Parse new lines
        new_messages = []
        for line in new_data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed = _parse_entry(entry, cache)
            if parsed is None:
                continue
            # _parse_entry may return a list (multiple tool_results) or a single dict
            items = parsed if isinstance(parsed, list) else [parsed]
            for item in items:
                # Register tool_use IDs for name lookup
                if item["type"] == "assistant":
                    for tool in item.get("tool_uses", []):
                        tid = tool.get("tool_use_id")
                        if tid:
                            cache.tool_use_names[tid] = tool.get("name", "")
                new_messages.append(item)

        cache.messages.extend(new_messages)
        return new_messages, len(cache.messages)

    def clear_session(self, session_id: str) -> None:
        """Remove cached state for a session (e.g. on restart)."""
        self._cache.pop(session_id, None)
