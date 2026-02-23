"""FastAPI web server for the Claude Fleet Web Dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from agent_fleet.session_manager import (
    COMMAND_MAP,
    discover_fleet_agents,
    get_agent_log_path,
    get_log_status,
    send_to_tmux,
    send_raw_keys,
    capture_pane,
    load_history_sessions,
    load_history_session_messages,
    launch_claude_session,
)
from agent_fleet.log_streamer import get_log_snapshot

BASE_DIR = Path(__file__).parent
app = FastAPI(title="Claude Fleet Web Dashboard")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ── REST Endpoints ──────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the SPA."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/sessions/live")
async def get_live_sessions():
    """List active fleet agents with their current status."""
    agents = discover_fleet_agents()
    results = []
    for agent in agents:
        log_info = get_log_status(agent["log_path"])
        results.append({
            "name": agent["agent_name"],
            "agent_type": agent["agent_type"],
            "log_path": agent["log_path"],
            "status": log_info["status"],
            "summary": log_info["summary"],
            "staleness_seconds": log_info["staleness_seconds"],
            "commands": COMMAND_MAP.get(agent["agent_type"].lower(), COMMAND_MAP["claude"]),
        })
    return results


@app.get("/api/sessions/live/{name}")
async def get_live_session_detail(name: str):
    """Get detailed info for a specific live session."""
    log_path = get_agent_log_path(name)
    if not log_path:
        return {"error": f"Agent '{name}' not found"}

    snapshot = get_log_snapshot(str(log_path))
    pane_text = await capture_pane(name)

    return {
        "name": name,
        "status": snapshot["status"],
        "summary": snapshot["summary"],
        "recent_lines": snapshot["recent_lines"],
        "staleness_seconds": snapshot["staleness_seconds"],
        "pane_capture": pane_text,
    }


@app.get("/api/sessions/live/{name}/capture")
async def get_pane_capture(name: str):
    """Capture current tmux pane content."""
    text = await capture_pane(name)
    if text is None:
        return {"error": f"Could not capture pane for '{name}'"}
    return {"name": name, "capture": text}


@app.get("/api/sessions/history")
async def get_history_sessions():
    """List historical sessions from history.jsonl files."""
    return load_history_sessions()


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

    error = await send_to_tmux(name, command)
    if error:
        return {"error": error}
    return {"ok": True, "command": command}


@app.post("/api/sessions/live/{name}/keys")
async def send_keys(name: str, body: dict):
    """Send raw tmux key names (e.g. BTab, Escape) to a live session."""
    keys = body.get("keys", [])
    if not keys or not isinstance(keys, list):
        return {"error": "keys must be a non-empty list of tmux key names"}

    error = await send_raw_keys(name, keys)
    if error:
        return {"error": error}
    return {"ok": True, "keys": keys}


@app.post("/api/sessions/launch")
async def launch_session(body: dict):
    """Launch a new Claude/Gemini session."""
    working_dir = body.get("working_dir", "").strip()
    agent_type = body.get("agent_type", "claude").strip()

    if not working_dir:
        return {"error": "working_dir is required"}

    result = await launch_claude_session(working_dir, agent_type)
    return result


# ── WebSocket Endpoints ─────────────────────────────────────────────────────


@app.websocket("/ws/fleet")
async def ws_fleet(websocket: WebSocket):
    """Stream fleet-wide session list updates (polls every 3s)."""
    await websocket.accept()

    last_state = None
    try:
        while True:
            agents = discover_fleet_agents()
            results = []
            for agent in agents:
                log_info = get_log_status(agent["log_path"])
                results.append({
                    "name": agent["agent_name"],
                    "agent_type": agent["agent_type"],
                    "status": log_info["status"],
                    "summary": log_info["summary"],
                    "staleness_seconds": log_info["staleness_seconds"],
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

    parser = argparse.ArgumentParser(description="Claude Fleet Web Dashboard")
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
