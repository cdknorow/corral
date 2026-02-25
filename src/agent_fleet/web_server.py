"""FastAPI web server for the Agent Fleet Dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from agent_fleet.session_manager import (
    COMMAND_MAP,
    discover_fleet_agents,
    get_agent_log_path,
    get_log_status,
    get_session_info,
    send_to_tmux,
    send_raw_keys,
    capture_pane,
    kill_session,
    restart_session,
    open_terminal_attached,
    load_history_sessions,
    load_history_session_messages,
    launch_claude_session,
)
from agent_fleet.log_streamer import get_log_snapshot
from agent_fleet.session_store import SessionStore

log = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background indexer, batch summarizer, and git poller on server startup."""
    from agent_fleet.session_indexer import SessionIndexer, BatchSummarizer
    from agent_fleet.git_poller import GitPoller

    indexer = SessionIndexer(store)
    summarizer = BatchSummarizer(store)
    git_poller = GitPoller(store)

    indexer_task = asyncio.create_task(indexer.run_forever(interval=120))
    summarizer_task = asyncio.create_task(summarizer.run_forever())
    git_task = asyncio.create_task(git_poller.run_forever(interval=120))

    # Store indexer on app state so endpoints can trigger refresh
    app.state.indexer = indexer

    yield

    indexer_task.cancel()
    summarizer_task.cancel()
    git_task.cancel()


app = FastAPI(title="Agent Fleet Dashboard", lifespan=lifespan)
store = SessionStore()

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ── REST Endpoints ──────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the fleet dashboard SPA."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/sessions/live")
async def get_live_sessions():
    """List active fleet agents with their current status."""
    agents = await discover_fleet_agents()
    git_state = await asyncio.to_thread(store.get_all_latest_git_state)
    results = []
    for agent in agents:
        log_info = get_log_status(agent["log_path"])
        git = git_state.get(agent["agent_name"])
        entry = {
            "name": agent["agent_name"],
            "agent_type": agent["agent_type"],
            "log_path": agent["log_path"],
            "status": log_info["status"],
            "summary": log_info["summary"],
            "staleness_seconds": log_info["staleness_seconds"],
            "commands": COMMAND_MAP.get(agent["agent_type"].lower(), COMMAND_MAP["claude"]),
            "branch": git["branch"] if git else None,
        }
        results.append(entry)
    return results


@app.get("/api/sessions/live/{name}")
async def get_live_session_detail(name: str, agent_type: str | None = None):
    """Get detailed info for a specific live session."""
    log_path = get_agent_log_path(name, agent_type)
    if not log_path:
        return {"error": f"Agent '{name}' not found"}

    snapshot = get_log_snapshot(str(log_path))
    pane_text = await capture_pane(name, agent_type=agent_type)

    return {
        "name": name,
        "status": snapshot["status"],
        "summary": snapshot["summary"],
        "recent_lines": snapshot["recent_lines"],
        "staleness_seconds": snapshot["staleness_seconds"],
        "pane_capture": pane_text,
    }


@app.get("/api/sessions/live/{name}/capture")
async def get_pane_capture(name: str, agent_type: str | None = None):
    """Capture current tmux pane content."""
    text = await capture_pane(name, agent_type=agent_type)
    if text is None:
        return {"error": f"Could not capture pane for '{name}'"}
    return {"name": name, "capture": text}


@app.get("/api/sessions/live/{name}/info")
async def get_live_session_info(name: str, agent_type: str | None = None):
    """Return enriched metadata for a live session (Info modal)."""
    info = await get_session_info(name, agent_type)
    if not info:
        return {"error": f"Agent '{name}' not found"}
    git = await asyncio.to_thread(store.get_latest_git_state, name)
    if git:
        info["git_branch"] = git["branch"]
        info["git_commit_hash"] = git["commit_hash"]
        info["git_commit_subject"] = git["commit_subject"]
    return info


@app.get("/api/sessions/live/{name}/git")
async def get_live_session_git(name: str, limit: int = Query(20, ge=1, le=100)):
    """Return recent git snapshots (commit history) for a live agent."""
    snapshots = await asyncio.to_thread(store.get_git_snapshots, name, limit)
    return {"agent_name": name, "snapshots": snapshots}


@app.get("/api/sessions/history")
async def get_history_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None),
    tag_id: Optional[int] = Query(None),
    source_type: Optional[str] = Query(None),
):
    """Paginated history sessions from the index, with search/tag/source filters.

    Falls back to scanning files if the index is empty (cold start).
    """
    result = await asyncio.to_thread(
        store.list_sessions_paged, page, page_size, q, tag_id, source_type
    )

    if result["total"] == 0 and not q and not tag_id and not source_type:
        # Cold start — index hasn't run yet; trigger immediate index and fall back
        indexer = getattr(app.state, "indexer", None)
        if indexer:
            try:
                await indexer.run_once()
                result = await asyncio.to_thread(
                    store.list_sessions_paged, page, page_size, q, tag_id, source_type
                )
            except Exception:
                pass

        # If still empty, fall back to old file-scan method
        if result["total"] == 0:
            sessions = load_history_sessions()
            metadata = await asyncio.to_thread(store.get_all_session_metadata)
            for s in sessions:
                meta = metadata.get(s["session_id"])
                if meta:
                    s["tags"] = meta["tags"]
                    s["has_notes"] = meta["has_notes"]
                else:
                    s["tags"] = []
                    s["has_notes"] = False
            return {"sessions": sessions, "total": len(sessions), "page": 1, "page_size": len(sessions)}

    return result


@app.post("/api/indexer/refresh")
async def trigger_indexer_refresh():
    """Trigger an immediate re-index."""
    indexer = getattr(app.state, "indexer", None)
    if not indexer:
        return {"error": "Indexer not available"}
    result = await indexer.run_once()
    return result


@app.get("/api/sessions/history/{session_id}/git")
async def get_history_session_git(session_id: str):
    """Return git commits that occurred during a historical session's time range."""
    snapshots = await asyncio.to_thread(store.get_git_snapshots_for_session, session_id)
    return {"session_id": session_id, "commits": snapshots}


@app.get("/api/sessions/history/{session_id}")
async def get_history_session_detail(session_id: str):
    """Get all messages for a historical session."""
    messages = load_history_session_messages(session_id)
    if not messages:
        return {"error": f"Session '{session_id}' not found"}
    return {"session_id": session_id, "messages": messages}


@app.post("/api/sessions/live/{name}/send")
async def send_command(name: str, body: dict):
    """Send a command to a live tmux session."""
    command = body.get("command", "").strip()
    if not command:
        return {"error": "No command provided"}

    agent_type = body.get("agent_type") or None
    error = await send_to_tmux(name, command, agent_type=agent_type)
    if error:
        return {"error": error}
    return {"ok": True, "command": command}


@app.post("/api/sessions/live/{name}/keys")
async def send_keys(name: str, body: dict):
    """Send raw tmux key names (e.g. BTab, Escape) to a live session."""
    keys = body.get("keys", [])
    if not keys or not isinstance(keys, list):
        return {"error": "keys must be a non-empty list of tmux key names"}

    agent_type = body.get("agent_type") or None
    error = await send_raw_keys(name, keys, agent_type=agent_type)
    if error:
        return {"error": error}
    return {"ok": True, "keys": keys}


@app.post("/api/sessions/live/{name}/kill")
async def kill_live_session(name: str, body: dict | None = None):
    """Kill the tmux session for a live agent."""
    agent_type = (body or {}).get("agent_type") or None
    error = await kill_session(name, agent_type=agent_type)
    if error:
        return {"error": error}
    return {"ok": True}


@app.post("/api/sessions/live/{name}/restart")
async def restart_live_session(name: str, body: dict | None = None):
    """Restart the agent session: exit the current session and launch a fresh one in the same pane."""
    agent_type = (body or {}).get("agent_type") or None
    result = await restart_session(name, agent_type=agent_type)
    return result


@app.post("/api/sessions/live/{name}/attach")
async def attach_terminal(name: str, body: dict | None = None):
    """Open a local terminal window attached to the agent's tmux session."""
    agent_type = (body or {}).get("agent_type") or None
    error = await open_terminal_attached(name, agent_type=agent_type)
    if error:
        return {"error": error}
    return {"ok": True}


@app.get("/api/filesystem/list")
async def list_filesystem(path: str = "~"):
    """List directories at a given path for the directory browser."""
    import os

    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        return {"error": f"Not a directory: {path}", "entries": []}

    entries = []
    try:
        for name in sorted(os.listdir(expanded), key=str.lower):
            full = os.path.join(expanded, name)
            if os.path.isdir(full) and not name.startswith("."):
                entries.append(name)
    except PermissionError:
        return {"error": "Permission denied", "entries": []}

    return {"path": expanded, "entries": entries}


@app.post("/api/sessions/launch")
async def launch_session(body: dict):
    """Launch a new Claude/Gemini session."""
    working_dir = body.get("working_dir", "").strip()
    agent_type = body.get("agent_type", "claude").strip()

    if not working_dir:
        return {"error": "working_dir is required"}

    result = await launch_claude_session(working_dir, agent_type)
    return result


# ── Session Notes Endpoints ─────────────────────────────────────────────────


@app.get("/api/sessions/history/{session_id}/notes")
async def get_session_notes(session_id: str):
    """Get notes and auto-summary for a session. Triggers auto-summarization if empty."""
    notes = await asyncio.to_thread(store.get_session_notes, session_id)

    # If no notes and no auto-summary, trigger summarization in background
    if not notes["notes_md"] and not notes["auto_summary"]:
        try:
            from agent_fleet.auto_summarizer import AutoSummarizer

            summarizer = AutoSummarizer(store)
            asyncio.create_task(summarizer.summarize_session(session_id))
            notes["summarizing"] = True
        except ImportError:
            notes["summarizing"] = False

    return notes


@app.put("/api/sessions/history/{session_id}/notes")
async def save_session_notes(session_id: str, body: dict):
    """Save user-edited markdown notes for a session."""
    notes_md = body.get("notes_md", "")
    await asyncio.to_thread(store.save_session_notes, session_id, notes_md)
    return {"ok": True}


@app.post("/api/sessions/history/{session_id}/resummarize")
async def resummarize_session(session_id: str):
    """Force re-generate auto-summary for a session."""
    try:
        from agent_fleet.auto_summarizer import AutoSummarizer

        summarizer = AutoSummarizer(store)
        summary = await summarizer.summarize_session(session_id)
        return {"ok": True, "auto_summary": summary}
    except ImportError:
        return {"error": "claude-agent-sdk not installed"}
    except Exception as e:
        return {"error": str(e)}


# ── Tags Endpoints ─────────────────────────────────────────────────────────


@app.get("/api/tags")
async def list_tags():
    """List all tags."""
    return await asyncio.to_thread(store.list_tags)


@app.post("/api/tags")
async def create_tag(body: dict):
    """Create a new tag."""
    name = body.get("name", "").strip()
    if not name:
        return {"error": "Tag name is required"}
    color = body.get("color", "#58a6ff")
    try:
        tag = await asyncio.to_thread(store.create_tag, name, color)
        return tag
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/tags/{tag_id}")
async def delete_tag(tag_id: int):
    """Delete a tag."""
    await asyncio.to_thread(store.delete_tag, tag_id)
    return {"ok": True}


@app.get("/api/sessions/history/{session_id}/tags")
async def get_session_tags(session_id: str):
    """Get tags for a session."""
    return await asyncio.to_thread(store.get_session_tags, session_id)


@app.post("/api/sessions/history/{session_id}/tags")
async def add_session_tag(session_id: str, body: dict):
    """Add a tag to a session."""
    tag_id = body.get("tag_id")
    if tag_id is None:
        return {"error": "tag_id is required"}
    await asyncio.to_thread(store.add_session_tag, session_id, int(tag_id))
    return {"ok": True}


@app.delete("/api/sessions/history/{session_id}/tags/{tag_id}")
async def remove_session_tag(session_id: str, tag_id: int):
    """Remove a tag from a session."""
    await asyncio.to_thread(store.remove_session_tag, session_id, tag_id)
    return {"ok": True}


# ── WebSocket Endpoints ─────────────────────────────────────────────────────


@app.websocket("/ws/fleet")
async def ws_fleet(websocket: WebSocket):
    """Stream fleet-wide session list updates (polls every 3s)."""
    await websocket.accept()

    last_state = None
    try:
        while True:
            agents = await discover_fleet_agents()
            git_state = await asyncio.to_thread(store.get_all_latest_git_state)
            results = []
            for agent in agents:
                log_info = get_log_status(agent["log_path"])
                git = git_state.get(agent["agent_name"])
                results.append({
                    "name": agent["agent_name"],
                    "agent_type": agent["agent_type"],
                    "status": log_info["status"],
                    "summary": log_info["summary"],
                    "staleness_seconds": log_info["staleness_seconds"],
                    "branch": git["branch"] if git else None,
                })

            current_state = json.dumps(results, sort_keys=True)
            if current_state != last_state:
                await websocket.send_json({"type": "fleet_update", "sessions": results})
                last_state = current_state

            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ── Entry Point ──────────────────────────────────────────────────────────────


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Agent Fleet Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8420, help="Port to bind to (default: 8420)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    uvicorn.run(
        "agent_fleet.web_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
