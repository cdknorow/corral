"""CLI entry point for the PostToolUse hook that syncs Claude Code tasks to the Fleet dashboard."""

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


def main():
    """Read hook JSON from stdin, call Fleet API to create/complete tasks."""
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    port = os.environ.get("FLEET_PORT", "8420")
    base = f"http://localhost:{port}"

    tool = d.get("tool_name", "")
    inp = d.get("tool_input", {}) if isinstance(d.get("tool_input"), dict) else {}
    task_id = str(inp.get("taskId", ""))
    subject = inp.get("subject", "")
    status = inp.get("status", "")

    resp = d.get("tool_response", "")
    resp_str = resp if isinstance(resp, str) else json.dumps(resp)
    m = re.search(r"Task #(\d+)", resp_str)
    resp_task_id = m.group(1) if m else ""

    cwd = d.get("cwd", "")
    agent_name = os.path.basename(cwd.rstrip("/"))
    if not agent_name:
        return

    if tool == "TaskCreate" and subject:
        _api(base, "POST", f"/api/sessions/live/{agent_name}/tasks", {"title": subject})
        cache_id = resp_task_id or task_id
        if cache_id:
            _cache_write(cache_id, subject)

    elif tool == "TaskUpdate":
        if task_id and subject:
            _cache_write(task_id, subject)
        if status == "completed":
            title = subject or (_cache_read(task_id) if task_id else "")
            if title:
                tasks = _api(base, "GET", f"/api/sessions/live/{agent_name}/tasks")
                if tasks:
                    for t in tasks:
                        if t.get("title") == title and not t.get("completed"):
                            _api(base, "PATCH", f"/api/sessions/live/{agent_name}/tasks/{t['id']}", {"completed": 1})
                            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # Never block Claude
