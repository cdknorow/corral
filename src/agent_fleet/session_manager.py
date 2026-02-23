"""Session manager — shared logic for tmux discovery, history parsing, and command execution."""

from __future__ import annotations

import asyncio
import json
import os
import re
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


def discover_fleet_agents() -> list[dict[str, Any]]:
    """Return list of agent dicts from fleet log files, sorted by name."""
    results = []
    for log_path in sorted(glob(LOG_PATTERN)):
        p = Path(log_path)
        match = re.search(r"([^_]+)_fleet_(.+)", p.stem)
        if match:
            results.append({
                "agent_type": match.group(1),
                "agent_name": match.group(2),
                "log_path": str(p),
            })
    return results


def get_agent_log_path(agent_name: str) -> Path | None:
    """Find the log file for a given agent name."""
    for log_path in glob(LOG_PATTERN):
        p = Path(log_path)
        match = re.search(r"([^_]+)_fleet_(.+)", p.stem)
        if match and match.group(2) == agent_name:
            return p
    return None


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


async def find_pane_target(agent_name: str) -> str | None:
    """Find the tmux pane target address for a given agent name.

    Matches against pane title, session name, and current working directory
    to handle cases where the pane title is changed by the running program.
    """
    sessions = await list_tmux_sessions()
    agent_low = agent_name.lower()
    norm_name = agent_name.replace("_", "-").lower()

    for s in sessions:
        title_low = s["pane_title"].lower()
        session_low = s["session_name"].lower()
        path_low = s.get("current_path", "").lower()
        path_base = os.path.basename(path_low.rstrip("/"))

        if (agent_low in title_low or
                norm_name in title_low or
                agent_low in session_low or
                norm_name in session_low or
                agent_low == path_base or
                norm_name == path_base):
            return s["target"]
    return None


async def send_to_tmux(agent_name: str, command: str) -> str | None:
    """Send a command to the tmux pane for the given agent. Returns error string or None."""
    target = await find_pane_target(agent_name)
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


async def send_raw_keys(agent_name: str, keys: list[str]) -> str | None:
    """Send raw tmux key names (e.g. BTab, Escape) to a pane. Returns error string or None."""
    target = await find_pane_target(agent_name)
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


async def capture_pane(agent_name: str, lines: int = 200) -> str | None:
    """Capture the current content of a tmux pane. Returns text or None on error."""
    target = await find_pane_target(agent_name)
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


def load_history_sessions() -> list[dict[str, Any]]:
    """Load Claude session history from ~/.claude/projects/**/history.jsonl files.

    Returns list of session summaries sorted by last timestamp descending.
    """
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

    # Build summaries (use first human message as preview)
    result = []
    for sid, data in sessions.items():
        first_human = ""
        for msg in data["messages"]:
            if msg.get("type") == "human":
                content = msg.get("message", {}).get("content", "")
                if isinstance(content, str):
                    first_human = content[:100]
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            first_human = block.get("text", "")[:100]
                            break
                if first_human:
                    break
        data["summary"] = first_human or "(no messages)"
        data["message_count"] = len(data["messages"])
        # Don't include full messages in the listing
        listing = {k: v for k, v in data.items() if k != "messages"}
        result.append(listing)

    result.sort(key=lambda x: x.get("last_timestamp") or "", reverse=True)
    return result


def load_history_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Load all messages for a specific historical session."""
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

    messages.sort(key=lambda x: x.get("timestamp") or "")
    return messages


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
