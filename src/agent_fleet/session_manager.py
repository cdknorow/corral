"""Session manager — shared logic for tmux discovery, history parsing, and command execution."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import time
from glob import glob
from pathlib import Path
from typing import Any

LOG_DIR = os.environ.get("TMPDIR", "/tmp").rstrip("/")
LOG_PATTERN = f"{LOG_DIR}/*_fleet_*.log"
STATUS_RE = re.compile(r"\|\|STATUS:\s*(.+?)\|\|")
SUMMARY_RE = re.compile(r"\|\|SUMMARY:\s*(.+?)\|\|")
ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
# Stray control characters (BEL, etc.) that survive ANSI stripping — keep \n \r \t
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

COMMAND_MAP = {
    "claude": {
        "compress": "/compact",
        "clear": "/clear",
    },
    "gemini": {
        "compress": "/compress",
        "clear": "/clear",
    },
}

HISTORY_PATH = Path.home() / ".claude" / "projects"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences, replacing each with a space."""
    text = ANSI_RE.sub(" ", text)
    # Remove stray control characters (BEL \x07, etc.) left after partial sequences
    text = _CONTROL_CHAR_RE.sub("", text)
    return text


def clean_match(text: str) -> str:
    """Collapse whitespace runs into a single space and strip."""
    return " ".join(text.split())


async def discover_fleet_agents() -> list[dict[str, Any]]:
    """Return list of agent dicts from fleet log files, sorted by name.

    Cross-references log files against live tmux sessions and removes
    stale log files whose sessions no longer exist.
    """
    panes = await list_tmux_sessions()
    live_sessions = {s["session_name"].lower() for s in panes}
    # Also collect pane titles and working-dir basenames for matching
    live_tokens: set[str] = set()
    for s in panes:
        live_tokens.add(s["pane_title"].lower())
        live_tokens.add(s["session_name"].lower())
        path_base = os.path.basename(s.get("current_path", "").rstrip("/")).lower()
        if path_base:
            live_tokens.add(path_base)

    results = []
    for log_path in sorted(glob(LOG_PATTERN)):
        p = Path(log_path)
        match = re.search(r"([^_]+)_fleet_(.+)", p.stem)
        if not match:
            continue

        agent_type = match.group(1)
        agent_name = match.group(2)
        agent_low = agent_name.lower()
        norm_name = agent_name.replace("_", "-").lower()

        # Check if any live tmux pane matches this agent
        alive = any(
            agent_low in tok or norm_name in tok
            for tok in live_tokens
        )

        if alive:
            results.append({
                "agent_type": agent_type,
                "agent_name": agent_name,
                "log_path": str(p),
            })
        else:
            # Stale log — remove it
            try:
                p.unlink()
            except OSError:
                pass

    return results


def get_agent_log_path(agent_name: str, agent_type: str | None = None) -> Path | None:
    """Find the log file for a given agent name.

    When *agent_type* is provided the match is narrowed to the log whose
    prefix matches (e.g. ``claude_fleet_X`` vs ``gemini_fleet_X``).
    """
    best: Path | None = None
    for log_path in glob(LOG_PATTERN):
        p = Path(log_path)
        match = re.search(r"([^_]+)_fleet_(.+)", p.stem)
        if match and match.group(2) == agent_name:
            if agent_type and match.group(1).lower() == agent_type.lower():
                return p  # exact match — return immediately
            if best is None:
                best = p  # keep as fallback
    return best


def get_log_status(log_path: str | Path) -> dict[str, Any]:
    """Read a log file and return current status, summary, staleness, and recent lines."""
    log_path = Path(log_path)
    result: dict[str, Any] = {
        "status": None,
        "summary": None,
        "staleness_seconds": None,
        "recent_lines": [],
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

        result["staleness_seconds"] = time.time() - log_path.stat().st_mtime

        lines = text.splitlines()
        result["recent_lines"] = lines[-200:]
    except OSError:
        pass
    return result


async def list_tmux_sessions() -> list[dict[str, str]]:
    """List all tmux panes with their titles, session names, and targets."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "list-panes", "-a",
            "-F", "#{pane_title}|#{session_name}|#S:#I.#P|#{pane_current_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []

        results = []
        for line in stdout.decode().splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                results.append({
                    "pane_title": parts[0],
                    "session_name": parts[1],
                    "target": parts[2],
                    "current_path": parts[3],
                })
        return results
    except (OSError, FileNotFoundError):
        return []


async def _find_pane(agent_name: str, agent_type: str | None = None) -> dict[str, str] | None:
    """Find the tmux pane dict for a given agent name.

    Matches against pane title, session name, and current working directory.
    When *agent_type* is provided, panes whose title or session name also
    contain the agent type are preferred (disambiguates same-worktree agents).
    """
    sessions = await list_tmux_sessions()
    agent_low = agent_name.lower()
    norm_name = agent_name.replace("_", "-").lower()
    type_low = agent_type.lower() if agent_type else None

    fallback: dict[str, str] | None = None

    for s in sessions:
        title_low = s["pane_title"].lower()
        session_low = s["session_name"].lower()
        path_low = s.get("current_path", "").lower()
        path_base = os.path.basename(path_low.rstrip("/"))

        name_match = (agent_low in title_low or
                      norm_name in title_low or
                      agent_low in session_low or
                      norm_name in session_low or
                      agent_low == path_base or
                      norm_name == path_base)

        if not name_match:
            continue

        if type_low:
            if type_low in title_low or type_low in session_low:
                return s
            if fallback is None:
                fallback = s
        else:
            return s

    return fallback


async def find_pane_target(agent_name: str, agent_type: str | None = None) -> str | None:
    """Find the tmux pane target address for a given agent name."""
    pane = await _find_pane(agent_name, agent_type)
    return pane["target"] if pane else None


async def send_to_tmux(agent_name: str, command: str, agent_type: str | None = None) -> str | None:
    """Send a command to the tmux pane for the given agent. Returns error string or None."""
    target = await find_pane_target(agent_name, agent_type)
    if not target:
        return f"Pane '{agent_name}' not found in any tmux session"

    try:
        # Send the text content
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", target, "-l", command,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return f"send-keys failed (rc={proc.returncode}): {stderr.decode().strip()}"

        # Pause to let tmux deliver keystrokes to the pane
        await asyncio.sleep(0.3)

        # Send Enter
        proc = await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", target, "Enter",
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return f"send Enter failed (rc={proc.returncode}): {stderr.decode().strip()}"

        return None
    except Exception as e:
        return str(e)


async def send_raw_keys(agent_name: str, keys: list[str], agent_type: str | None = None) -> str | None:
    """Send raw tmux key names (e.g. BTab, Escape) to a pane. Returns error string or None."""
    target = await find_pane_target(agent_name, agent_type)
    if not target:
        return f"Pane '{agent_name}' not found in any tmux session"

    try:
        for key in keys:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", target, key,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                return f"send-keys '{key}' failed (rc={proc.returncode}): {stderr.decode().strip()}"
            await asyncio.sleep(0.1)
        return None
    except Exception as e:
        return str(e)


async def capture_pane(agent_name: str, lines: int = 200, agent_type: str | None = None) -> str | None:
    """Capture the current content of a tmux pane. Returns text or None on error."""
    target = await find_pane_target(agent_name, agent_type)
    if not target:
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "capture-pane", "-t", target, "-p", f"-S-{lines}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        return stdout.decode(errors="replace")
    except (OSError, FileNotFoundError):
        return None


async def kill_session(agent_name: str, agent_type: str | None = None) -> str | None:
    """Kill the tmux session for a given agent and remove its log file.

    Returns error string or None.
    """
    pane = await _find_pane(agent_name, agent_type)
    if not pane:
        return f"Pane '{agent_name}' not found in any tmux session"

    session_name = pane["session_name"]
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux", "kill-session", "-t", session_name,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return f"kill-session failed: {stderr.decode().strip()}"

        # Remove the log file so the agent disappears from discover_fleet_agents
        log_path = get_agent_log_path(agent_name, agent_type)
        if log_path:
            try:
                log_path.unlink()
            except OSError:
                pass

        return None
    except Exception as e:
        return str(e)


async def open_terminal_attached(agent_name: str, agent_type: str | None = None) -> str | None:
    """Open a local terminal window attached to the agent's tmux session.

    Returns an error string on failure, or None on success.
    Uses osascript on macOS, or falls back to common terminal emulators on Linux.
    """
    pane = await _find_pane(agent_name, agent_type)
    if not pane:
        return f"Pane '{agent_name}' not found in any tmux session"

    session_name = pane["session_name"]
    attach_cmd = f"tmux attach -t {session_name}"

    try:
        if platform.system() == "Darwin":
            # macOS: use osascript to open Terminal.app
            script = (
                f'tell application "Terminal"\n'
                f'    activate\n'
                f'    do script "{attach_cmd}"\n'
                f'end tell'
            )
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                return f"osascript failed: {stderr.decode().strip()}"
        else:
            # Linux: try common terminal emulators
            for term in ("gnome-terminal", "xfce4-terminal", "konsole", "xterm"):
                if shutil.which(term):
                    if term == "gnome-terminal":
                        args = [term, "--", "bash", "-c", attach_cmd]
                    elif term == "konsole":
                        args = [term, "-e", "bash", "-c", attach_cmd]
                    else:
                        args = [term, "-e", attach_cmd]
                    proc = await asyncio.create_subprocess_exec(
                        *args, stderr=asyncio.subprocess.PIPE,
                    )
                    # Don't wait — terminal runs independently
                    return None
            return "No supported terminal emulator found"

        return None
    except Exception as e:
        return str(e)


def _load_claude_history_sessions() -> list[dict[str, Any]]:
    """Load Claude session history from ~/.claude/projects/**/history.jsonl files."""
    sessions: dict[str, dict[str, Any]] = {}
    history_base = Path.home() / ".claude" / "projects"

    if not history_base.exists():
        return []

    for history_file in history_base.rglob("*.jsonl"):
        try:
            with open(history_file, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    session_id = entry.get("sessionId")
                    if not session_id:
                        continue

                    if session_id not in sessions:
                        sessions[session_id] = {
                            "session_id": session_id,
                            "messages": [],
                            "first_timestamp": entry.get("timestamp"),
                            "last_timestamp": entry.get("timestamp"),
                            "source_file": str(history_file),
                            "source_type": "claude",
                            "summary": None,
                        }

                    ts = entry.get("timestamp")
                    if ts:
                        if not sessions[session_id]["first_timestamp"] or ts < sessions[session_id]["first_timestamp"]:
                            sessions[session_id]["first_timestamp"] = ts
                        if not sessions[session_id]["last_timestamp"] or ts > sessions[session_id]["last_timestamp"]:
                            sessions[session_id]["last_timestamp"] = ts

                    sessions[session_id]["messages"].append(entry)
        except OSError:
            continue

    # Build summaries: prefer ||SUMMARY:|| marker, fall back to first human message
    result = []
    for sid, data in sessions.items():
        summary_marker = ""
        first_human = ""
        for msg in data["messages"]:
            if not summary_marker and msg.get("type") == "assistant":
                content = msg.get("message", {}).get("content", "")
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                m = SUMMARY_RE.search(text)
                if m:
                    summary_marker = clean_match(m.group(1))

            if not first_human and msg.get("type") == "human":
                content = msg.get("message", {}).get("content", "")
                if isinstance(content, str):
                    first_human = content[:100]
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            first_human = block.get("text", "")[:100]
                            break
        data["summary"] = summary_marker or first_human or "(no messages)"
        data["message_count"] = len(data["messages"])
        listing = {k: v for k, v in data.items() if k != "messages"}
        result.append(listing)

    return result


GEMINI_HISTORY_BASE = Path.home() / ".gemini" / "tmp"


def _extract_gemini_text(content: list[dict]) -> str:
    """Extract plain text from a Gemini message content array."""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("text"):
            parts.append(item["text"])
    return "\n".join(parts)


def _load_gemini_history_sessions() -> list[dict[str, Any]]:
    """Load Gemini session history from ~/.gemini/tmp/*/chats/session-*.json."""
    if not GEMINI_HISTORY_BASE.exists():
        return []

    result = []
    for session_file in GEMINI_HISTORY_BASE.rglob("session-*.json"):
        try:
            data = json.loads(session_file.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue

        session_id = data.get("sessionId")
        if not session_id:
            continue

        messages = data.get("messages", [])
        first_ts = data.get("startTime")
        last_ts = data.get("lastUpdated")

        # Build summary: prefer ||SUMMARY:|| in gemini messages, fall back to first user message
        summary_marker = ""
        first_user = ""
        for msg in messages:
            msg_type = msg.get("type", "")
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            text = _extract_gemini_text(content)

            if not summary_marker and msg_type == "gemini":
                m = SUMMARY_RE.search(text)
                if m:
                    summary_marker = clean_match(m.group(1))

            if not first_user and msg_type == "user":
                first_user = text[:100]

        result.append({
            "session_id": session_id,
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "source_file": str(session_file),
            "source_type": "gemini",
            "summary": summary_marker or first_user or "(no messages)",
            "message_count": len(messages),
        })

    return result


def load_history_sessions() -> list[dict[str, Any]]:
    """Load session history from both Claude and Gemini.

    Returns list of session summaries sorted by last timestamp descending.
    """
    result = _load_claude_history_sessions() + _load_gemini_history_sessions()
    result.sort(key=lambda x: x.get("last_timestamp") or "", reverse=True)
    return result


def _load_claude_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Load all messages for a specific Claude historical session."""
    history_base = Path.home() / ".claude" / "projects"
    if not history_base.exists():
        return []

    messages = []
    for history_file in history_base.rglob("*.jsonl"):
        try:
            with open(history_file, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("sessionId") == session_id:
                        messages.append(entry)
        except OSError:
            continue

    return messages


def _normalize_gemini_message(msg: dict) -> dict[str, Any]:
    """Convert a Gemini message to the Claude-compatible format used by the UI."""
    msg_type = msg.get("type", "unknown")
    content = msg.get("content", [])
    text = _extract_gemini_text(content) if isinstance(content, list) else ""

    # Map Gemini types to the human/assistant convention the UI expects
    if msg_type == "user":
        role = "human"
    elif msg_type in ("gemini", "error", "info"):
        role = "assistant"
    else:
        role = "assistant"

    return {
        "sessionId": msg.get("id", ""),
        "timestamp": msg.get("timestamp"),
        "type": role,
        "message": {"content": text},
    }


def _load_gemini_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Load all messages for a specific Gemini historical session."""
    if not GEMINI_HISTORY_BASE.exists():
        return []

    for session_file in GEMINI_HISTORY_BASE.rglob("session-*.json"):
        try:
            data = json.loads(session_file.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue

        if data.get("sessionId") != session_id:
            continue

        return [_normalize_gemini_message(m) for m in data.get("messages", [])]

    return []


def load_history_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Load all messages for a specific historical session (Claude or Gemini)."""
    # Try Claude first
    messages = _load_claude_session_messages(session_id)
    if messages:
        messages.sort(key=lambda x: x.get("timestamp") or "")
        return messages

    # Try Gemini
    messages = _load_gemini_session_messages(session_id)
    if messages:
        return messages

    return []


async def launch_claude_session(working_dir: str, agent_type: str = "claude") -> dict[str, str]:
    """Launch a new tmux session with a Claude/Gemini agent.

    Returns dict with session_name, log_file, and any error.
    """
    working_dir = os.path.abspath(working_dir)
    if not os.path.isdir(working_dir):
        return {"error": f"Directory not found: {working_dir}"}

    folder_name = os.path.basename(working_dir)
    log_dir = os.environ.get("TMPDIR", "/tmp").rstrip("/")

    # Find next available agent index
    existing = await list_tmux_sessions()
    existing_names = {s["session_name"] for s in existing}
    idx = 1
    while f"{agent_type}-agent-{idx}" in existing_names:
        idx += 1

    session_name = f"{agent_type}-agent-{idx}"
    log_file = f"{log_dir}/{agent_type}_fleet_{folder_name}.log"

    try:
        # Clear old log
        Path(log_file).write_text("")

        # Create detached session
        proc = await asyncio.create_subprocess_exec(
            "tmux", "new-session", "-d", "-s", session_name, "-c", working_dir,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"error": f"tmux new-session failed: {stderr.decode()}"}

        # Set up pipe-pane logging
        await asyncio.create_subprocess_exec(
            "tmux", "pipe-pane", "-t", session_name, "-o", f"cat >> '{log_file}'"
        )

        # Set pane title
        await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{session_name}.0",
            f"printf '\\033]2;{folder_name} \\xe2\\x80\\x94 {agent_type}\\033\\\\'", "Enter"
        )

        await asyncio.sleep(0.3)

        # Launch the agent
        script_dir = Path(__file__).parent
        protocol_path = script_dir / "PROTOCOL.md"

        if agent_type == "gemini":
            if protocol_path.exists():
                cmd = f'GEMINI_SYSTEM_MD="{protocol_path}" gemini'
            else:
                cmd = "gemini"
        else:
            if protocol_path.exists():
                cmd = f"claude --append-system-prompt \"$(cat '{protocol_path}')\""
            else:
                cmd = "claude"

        await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", f"{session_name}.0", cmd, "Enter"
        )

        return {
            "session_name": session_name,
            "log_file": log_file,
            "working_dir": working_dir,
            "agent_type": agent_type,
        }
    except Exception as e:
        return {"error": str(e)}
