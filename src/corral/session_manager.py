"""Session manager — shared logic for tmux discovery, history parsing, and command execution."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Any

from corral.utils import run_cmd, LOG_DIR, LOG_PATTERN, HISTORY_PATH

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
STATUS_RE = re.compile(r"\|\|STATUS: (.*?)\|\|")
SUMMARY_RE = re.compile(r"\|\|SUMMARY: (.*?)\|\|")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences, replacing each with a space."""
    text = ANSI_RE.sub(" ", text)
    # Remove stray control characters (BEL \x07, etc.) left after partial sequences
    text = _CONTROL_CHAR_RE.sub("", text)
    return text


def clean_match(text: str) -> str:
    """Collapse whitespace runs into a single space and strip."""
    return " ".join(text.split())


async def discover_corral_agents() -> list[dict[str, Any]]:
    """Return list of agent dicts from corral log files, sorted by name.

    Cross-references log files against live tmux sessions and removes
    stale log files whose sessions no longer exist.
    """
    from glob import glob
    
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
        match = re.search(r"([^_]+)_corral_(.+)", p.stem)
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
    prefix matches (e.g. ``claude_corral_X`` vs ``gemini_corral_X``).
    """
    from glob import glob
    
    best: Path | None = None
    for log_path in glob(LOG_PATTERN):
        p = Path(log_path)
        match = re.search(r"([^_]+)_corral_(.+)", p.stem)
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
        result["staleness_seconds"] = time.time() - log_path.stat().st_mtime
        
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            pos = file_size
            lines = []
            leftover = b""
            chunk_size = 4096

            max_chunks = 1000  # Up to ~4MB backwards
            chunks_read = 0

            while pos > 0 and (len(lines) < 20 or result["status"] is None or result["summary"] is None): 
                if chunks_read >= max_chunks:
                    break

                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size) + leftover

                parts = chunk.split(b"\n")
                if pos > 0:
                    leftover = parts.pop(0)

                for p in reversed(parts):
                    try:
                        need_status = result["status"] is None
                        need_summary = result["summary"] is None
                        need_lines = len(lines) < 20

                        if not (need_status or need_summary or need_lines):
                            break

                        text = p.decode("utf-8", errors="replace")
                        clean_line = strip_ansi(text)
                        
                        if need_status:
                            status_matches = STATUS_RE.findall(clean_line)
                            if status_matches:
                                result["status"] = clean_match(status_matches[-1])

                        if need_summary:
                            summary_matches = SUMMARY_RE.findall(clean_line)
                            if summary_matches:
                                result["summary"] = clean_match(summary_matches[-1])

                        if need_lines:
                            lines.insert(0, clean_line)
                    except Exception:
                        pass
                
                chunks_read += 1
                        
            # Fallback for summary: if not found in the tail, it might be at the very top
            if result["summary"] is None:
                f.seek(0)
                head_chunk = f.read(16384).decode("utf-8", errors="replace")
                head_matches = SUMMARY_RE.findall(strip_ansi(head_chunk))
                if head_matches:
                    result["summary"] = clean_match(head_matches[-1])
            
            result["recent_lines"] = lines
    except OSError:
        pass
    return result


async def list_tmux_sessions() -> list[dict[str, str]]:
    """List all tmux panes with their titles, session names, and targets."""
    try:
        rc, stdout, _ = await run_cmd(
            "tmux", "list-panes", "-a",
            "-F", "#{pane_title}|#{session_name}|#S:#I.#P|#{pane_current_path}",
        )
        if rc != 0:
            return []

        results = []
        for line in stdout.splitlines():
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


async def get_session_info(agent_name: str, agent_type: str | None = None) -> dict[str, Any] | None:
    """Return enriched metadata for a live session (used by the Info modal)."""
    pane = await _find_pane(agent_name, agent_type)
    if not pane:
        return None

    log_path = get_agent_log_path(agent_name, agent_type)
    return {
        "agent_name": agent_name,
        "agent_type": agent_type or "claude",
        "tmux_session_name": pane["session_name"],
        "tmux_target": pane["target"],
        "tmux_command": f"tmux attach -t {pane['session_name']}",
        "working_directory": pane.get("current_path", ""),
        "log_path": str(log_path) if log_path else None,
        "pane_title": pane.get("pane_title", ""),
    }


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
        rc, _, stderr = await run_cmd(
            "tmux", "send-keys", "-t", target, "-l", command
        )
        if rc != 0:
            return f"send-keys failed (rc={rc}): {stderr}"

        # Pause to let tmux deliver keystrokes to the pane
        await asyncio.sleep(0.3)

        # Send Enter
        rc, _, stderr = await run_cmd(
            "tmux", "send-keys", "-t", target, "Enter"
        )
        if rc != 0:
            return f"send Enter failed (rc={rc}): {stderr}"

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
            rc, _, stderr = await run_cmd(
                "tmux", "send-keys", "-t", target, key
            )
            if rc != 0:
                return f"send-keys '{key}' failed (rc={rc}): {stderr}"
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
        rc, stdout, _ = await run_cmd(
            "tmux", "capture-pane", "-t", target, "-p", f"-S-{lines}"
        )
        if rc != 0:
            return None
        return stdout
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
        rc, _, stderr = await run_cmd(
            "tmux", "kill-session", "-t", session_name
        )
        if rc != 0:
            return f"kill-session failed: {stderr}"

        # Remove the log file so the agent disappears from discover_corral_agents
        log_path = get_agent_log_path(agent_name, agent_type)
        if log_path:
            try:
                log_path.unlink()
            except OSError:
                pass

        return None
    except Exception as e:
        return str(e)


def _ensure_session_in_project_dir(session_id: str, working_dir: str) -> None:
    """Copy a Claude session's JSONL file (and companion dir) into the target project dir.

    ``claude --resume`` only searches the current project directory, so if the
    session originated in a different worktree/project we must copy the files
    across before resuming.
    """
    # Build the target project directory for the agent's working dir
    encoded = working_dir.replace("/", "-").replace("_", "-")
    target_project = HISTORY_PATH / encoded
    target_jsonl = target_project / f"{session_id}.jsonl"

    if target_jsonl.exists():
        return  # Already present — nothing to do

    # Search all project dirs for the session file
    source_jsonl: Path | None = None
    for candidate in HISTORY_PATH.iterdir():
        if not candidate.is_dir():
            continue
        f = candidate / f"{session_id}.jsonl"
        if f.exists():
            source_jsonl = f
            break

    if source_jsonl is None:
        return  # Session file not found anywhere

    # Ensure target directory exists
    target_project.mkdir(parents=True, exist_ok=True)

    # Copy the JSONL transcript
    shutil.copy2(source_jsonl, target_jsonl)

    # Copy the companion session-state directory if it exists
    source_dir = source_jsonl.parent / session_id
    target_dir = target_project / session_id
    if source_dir.is_dir() and not target_dir.exists():
        shutil.copytree(source_dir, target_dir)


async def restart_session(agent_name: str, agent_type: str | None = None, resume_session_id: str | None = None) -> dict[str, Any]:
    """Restart the Claude/Gemini session in the same tmux pane.

    Uses ``tmux respawn-pane -k`` to forcefully kill the running process
    and spawn a fresh shell, then re-launches the agent with the same
    system prompt (PROTOCOL.md).

    If *resume_session_id* is provided, Claude is launched with
    ``--resume <session_id>`` to continue a previous conversation.
    Only supported for Claude agents (returns error for Gemini).

    Returns a dict with result info or an ``error`` key.
    """
    pane = await _find_pane(agent_name, agent_type)
    if not pane:
        return {"error": f"Pane '{agent_name}' not found in any tmux session"}

    target = pane["target"]
    session_name = pane["session_name"]
    working_dir = pane.get("current_path", "")
    effective_type = (agent_type or "claude").lower()

    if resume_session_id and effective_type == "gemini":
        return {"error": "Resume is only supported for Claude agents"}

    # If resuming, ensure the session file exists in the target agent's
    # project directory so `claude --resume` can find it.
    if resume_session_id and working_dir:
        _ensure_session_in_project_dir(resume_session_id, working_dir)

    try:
        # 0. Resolve the log file path BEFORE killing the pane so glob lookup
        #    isn't racing against a cleared file.  Fall back to a deterministic
        #    path constructed from the agent info if glob matching fails.
        log_path = get_agent_log_path(agent_name, agent_type)
        if log_path is None:
            log_path = Path(LOG_DIR) / f"{effective_type}_corral_{agent_name}.log"
        log_file = str(log_path)

        # 0b. Explicitly close any existing pipe-pane so respawn-pane doesn't
        #     leave a stale pipe that swallows output.
        await run_cmd("tmux", "pipe-pane", "-t", target)

        # 1. Kill the running process and respawn a fresh shell in the same pane
        rc, _, stderr = await run_cmd(
            "tmux", "respawn-pane", "-k", "-t", target
        )
        if rc != 0:
            return {"error": f"respawn-pane failed: {stderr}"}

        # Wait for the shell to initialise
        await asyncio.sleep(1)

        # 1b. Clear the tmux pane scrollback so capture_pane returns fresh content
        await run_cmd(
            "tmux", "clear-history", "-t", target
        )

        # 2. Clear the log file so the dashboard starts fresh
        try:
            log_path.write_text("")
        except OSError:
            pass

        # 3. Re-establish pipe-pane logging
        await run_cmd(
            "tmux", "pipe-pane", "-t", target, "-o", f"cat >> '{log_file}'"
        )

        # 4. Restore the pane title
        folder_name = os.path.basename(working_dir.rstrip("/")) if working_dir else agent_name
        await run_cmd(
            "tmux", "send-keys", "-t", target,
            f"printf '\\033]2;{folder_name} \\xe2\\x80\\x94 {effective_type}\\033\\\\'", "Enter",
        )
        await asyncio.sleep(0.3)

        # 5. Re-launch the agent with the same system prompt
        script_dir = Path(__file__).parent
        protocol_path = script_dir / "PROTOCOL.md"

        if effective_type == "gemini":
            if protocol_path.exists():
                cmd = f'GEMINI_SYSTEM_MD="{protocol_path}" gemini'
            else:
                cmd = "gemini"
        else:
            parts = ["claude"]
            if resume_session_id:
                parts.append(f"--resume {resume_session_id}")
            if protocol_path.exists():
                parts.append(f"--append-system-prompt \"$(cat '{protocol_path}')\"")
            cmd = " ".join(parts)

        rc, _, stderr = await run_cmd(
            "tmux", "send-keys", "-t", target, "-l", cmd
        )
        if rc != 0:
            return {"error": f"re-launch failed: {stderr}"}

        await asyncio.sleep(0.3)

        await run_cmd(
            "tmux", "send-keys", "-t", target, "Enter"
        )

        return {
            "ok": True,
            "agent_name": agent_name,
            "agent_type": effective_type,
            "working_dir": working_dir,
        }
    except Exception as e:
        return {"error": str(e)}


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
            rc, _, stderr = await run_cmd(
                "osascript", "-e", script
            )
            if rc != 0:
                return f"osascript failed: {stderr}"
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
                    asyncio.create_task(run_cmd(*args))
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

            if not first_human and msg.get("type") in ("human", "user"):
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
    log_file = f"{log_dir}/{agent_type}_corral_{folder_name}.log"

    try:
        # Clear old log
        Path(log_file).write_text("")

        # Create detached session
        rc, _, stderr = await run_cmd(
            "tmux", "new-session", "-d", "-s", session_name, "-c", working_dir
        )
        if rc != 0:
            return {"error": f"tmux new-session failed: {stderr}"}

        # Set up pipe-pane logging
        await run_cmd(
            "tmux", "pipe-pane", "-t", session_name, "-o", f"cat >> '{log_file}'"
        )

        # Set pane title
        await run_cmd(
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
