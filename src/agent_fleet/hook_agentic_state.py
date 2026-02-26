"""CLI entry point for agentic state hooks — tracks all tool use, stops, and notifications."""

import json
import os
import re
import sys
import urllib.request


def _api(base: str, method: str, path: str, data=None):
    url = base + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _cache_dir() -> str:
    d = os.path.join(os.environ.get("TMPDIR", "/tmp"), "fleet_task_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_write(task_id: str, subject: str) -> None:
    try:
        with open(os.path.join(_cache_dir(), f"task_{task_id}"), "w") as f:
            f.write(subject)
    except OSError:
        pass


def _cache_read(task_id: str) -> str:
    try:
        with open(os.path.join(_cache_dir(), f"task_{task_id}")) as f:
            return f.read().strip()
    except OSError:
        return ""


def _parse_response(resp) -> dict:
    """Extract task id and subject from tool_response (may be dict or string)."""
    result = {"task_id": "", "subject": ""}
    if isinstance(resp, dict):
        task = resp.get("task", {})
        if isinstance(task, dict):
            result["task_id"] = str(task.get("id", ""))
            result["subject"] = task.get("subject", "")
        if not result["task_id"]:
            result["task_id"] = str(resp.get("taskId", ""))
    resp_str = resp if isinstance(resp, str) else json.dumps(resp)
    if not result["task_id"]:
        m = re.search(r"Task #(\d+)", resp_str)
        if m:
            result["task_id"] = m.group(1)
    return result


def _debug_log(msg: str) -> None:
    if not os.environ.get("FLEET_HOOK_DEBUG"):
        return
    try:
        with open(os.path.join(_cache_dir(), "debug.log"), "a") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


def _make_summary(tool_name: str, inp: dict, resp) -> str:
    """Generate a human-readable one-liner for a tool use event."""
    if tool_name == "Read":
        fp = inp.get("file_path", "")
        name = os.path.basename(fp) if fp else "file"
        offset = inp.get("offset")
        limit = inp.get("limit")
        if offset and limit:
            return f"Read {name} (lines {offset}-{offset + limit})"
        return f"Read {name}"

    if tool_name == "Write":
        fp = inp.get("file_path", "")
        name = os.path.basename(fp) if fp else "file"
        return f"Wrote {name}"

    if tool_name == "Edit":
        fp = inp.get("file_path", "")
        name = os.path.basename(fp) if fp else "file"
        return f"Edited {name}"

    if tool_name == "Bash":
        cmd = inp.get("command", "")
        return f"Ran: {_truncate(cmd, 80)}"

    if tool_name == "Grep":
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        dir_name = os.path.basename(path.rstrip("/")) if path else ""
        suffix = f" in {dir_name}/" if dir_name else ""
        return f"Searched for '{_truncate(pattern, 40)}'{suffix}"

    if tool_name == "Glob":
        pattern = inp.get("pattern", "")
        return f"Glob: {_truncate(pattern, 60)}"

    if tool_name == "WebFetch":
        url = inp.get("url", "")
        return f"Fetched {_truncate(url, 80)}"

    if tool_name == "WebSearch":
        query = inp.get("query", "")
        return f"Searched: {_truncate(query, 80)}"

    if tool_name == "TaskCreate":
        subject = inp.get("subject", "")
        return f"Created task: {_truncate(subject, 60)}"

    if tool_name == "TaskUpdate":
        task_id = inp.get("taskId", "")
        status = inp.get("status", "")
        return f"Updated task #{task_id} -> {status}" if task_id else "Updated task"

    if tool_name == "Task":
        desc = inp.get("description", "")
        return f"Launched subagent: {_truncate(desc, 60)}"

    if tool_name == "TaskList":
        return "Listed tasks"

    if tool_name == "TaskGet":
        return f"Got task #{inp.get('taskId', '?')}"

    return f"Used {tool_name}"


def _make_detail_json(tool_name: str, inp: dict) -> str | None:
    """Build a compact detail_json for the event."""
    detail = {}
    if tool_name in ("Read", "Write", "Edit"):
        fp = inp.get("file_path", "")
        if fp:
            detail["file_path"] = fp
    elif tool_name == "Bash":
        cmd = inp.get("command", "")
        if cmd:
            detail["command"] = _truncate(cmd, 200)
    elif tool_name == "Grep":
        detail["pattern"] = inp.get("pattern", "")
        if inp.get("path"):
            detail["path"] = inp["path"]
    elif tool_name == "Glob":
        detail["pattern"] = inp.get("pattern", "")
    elif tool_name == "WebFetch":
        url = inp.get("url", "")
        if url:
            detail["url"] = _truncate(url, 200)
    elif tool_name == "WebSearch":
        detail["query"] = inp.get("query", "")
    elif tool_name == "Task":
        detail["description"] = _truncate(inp.get("description", ""), 100)
        if inp.get("subagent_type"):
            detail["subagent_type"] = inp["subagent_type"]
    else:
        return None

    if not detail:
        return None
    raw = json.dumps(detail)
    return raw[:500] if len(raw) > 500 else raw


def _handle_task_sync(tool: str, inp: dict, resp_parsed: dict, agent_name: str, base: str):
    """Delegate task sync logic for TaskCreate/TaskUpdate (preserves existing behavior)."""
    task_id = str(inp.get("taskId", ""))
    subject = inp.get("subject", "")
    status = inp.get("status", "")

    if tool == "TaskCreate" and subject:
        _api(base, "POST", f"/api/sessions/live/{agent_name}/tasks", {"title": subject})
        cache_id = resp_parsed["task_id"] or task_id
        if cache_id:
            _cache_write(cache_id, subject)

    elif tool == "TaskUpdate":
        if task_id and subject:
            _cache_write(task_id, subject)
        if status in ("completed", "in_progress"):
            title = subject or resp_parsed.get("subject", "") or (_cache_read(task_id) if task_id else "")
            completed_value = 1 if status == "completed" else 2
            if title:
                tasks = _api(base, "GET", f"/api/sessions/live/{agent_name}/tasks")
                if tasks:
                    for t in tasks:
                        if t.get("title") == title and t.get("completed") != 1:
                            _api(base, "PATCH", f"/api/sessions/live/{agent_name}/tasks/{t['id']}",
                                 {"completed": completed_value})
                            break


def main():
    """Read hook JSON from stdin, create event + sync tasks."""
    try:
        raw = sys.stdin.read()
        d = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return

    _debug_log(f"AGENTIC_STATE INPUT: {raw[:500]}")

    port = os.environ.get("FLEET_PORT", "8420")
    base = f"http://localhost:{port}"

    cwd = d.get("cwd", "")
    agent_name = os.path.basename(cwd.rstrip("/"))
    if not agent_name:
        return

    session_id = d.get("session_id")
    hook_type = d.get("type", "")

    # Determine event_type and build summary
    tool = d.get("tool_name", "")
    inp = d.get("tool_input", {}) if isinstance(d.get("tool_input"), dict) else {}

    if tool:
        # PostToolUse event
        event_type = "tool_use"
        summary = _make_summary(tool, inp, d.get("tool_response"))
        detail_json = _make_detail_json(tool, inp)

        # Create event
        _api(base, "POST", f"/api/sessions/live/{agent_name}/events", {
            "event_type": event_type,
            "tool_name": tool,
            "summary": summary,
            "session_id": session_id,
            "detail_json": detail_json,
        })

        # Delegate task sync for TaskCreate/TaskUpdate
        if tool in ("TaskCreate", "TaskUpdate"):
            resp_parsed = _parse_response(d.get("tool_response", ""))
            _handle_task_sync(tool, inp, resp_parsed, agent_name, base)

    elif hook_type == "Stop" or d.get("stop_hook_active"):
        event_type = "stop"
        reason = d.get("reason", "unknown")
        summary = f"Agent stopped: {reason}"
        _api(base, "POST", f"/api/sessions/live/{agent_name}/events", {
            "event_type": event_type,
            "summary": summary,
            "session_id": session_id,
        })

    elif hook_type == "Notification" or d.get("message"):
        event_type = "notification"
        message = d.get("message", "")
        summary = f"Notification: {_truncate(message, 100)}"
        _api(base, "POST", f"/api/sessions/live/{agent_name}/events", {
            "event_type": event_type,
            "summary": summary,
            "session_id": session_id,
        })

    _debug_log(f"DONE: agent={agent_name} tool={tool} hook_type={hook_type}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # Never block the agent
