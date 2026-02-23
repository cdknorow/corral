"""FastAPI web server for the Claude Fleet Web Dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from agent_fleet.agent_manager import AgentManager
from agent_fleet.session_manager import (
    load_history_sessions,
    load_history_session_messages,
)

BASE_DIR = Path(__file__).parent

# Module-level singleton
agent_manager = AgentManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for the app."""
    yield
    await agent_manager.stop_all()


app = FastAPI(title="Claude Fleet Web Dashboard", lifespan=lifespan)

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
    return agent_manager.list_agents()


@app.get("/api/sessions/live/{name}")
async def get_live_session_detail(name: str):
    """Get detailed info for a specific live session."""
    snapshot = agent_manager.get_agent_snapshot(name)
    if not snapshot:
        return {"error": f"Agent '{name}' not found"}
    return snapshot


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
    """Send a command to a live agent session."""
    command = body.get("command", "").strip()
    if not command:
        return {"error": "No command provided"}

    result = await agent_manager.send_command(name, command)
    if result.get("error"):
        return result
    return {"ok": True, "command": command}


@app.post("/api/sessions/live/{name}/interrupt")
async def interrupt_session(name: str):
    """Interrupt a running agent."""
    return await agent_manager.interrupt_agent(name)


@app.delete("/api/sessions/live/{name}")
async def delete_session(name: str):
    """Stop and remove an agent."""
    return await agent_manager.stop_agent(name)


@app.post("/api/sessions/launch")
async def launch_session(body: dict):
    """Launch a new agent session via the SDK."""
    working_dir = body.get("working_dir", "").strip()
    name = body.get("name", "").strip()

    if not working_dir:
        return {"error": "working_dir is required"}

    # Auto-generate name from directory basename if not provided
    if not name:
        name = Path(working_dir).name

    # Deduplicate names
    existing = set(agent_manager.list_agents_names())
    if name in existing:
        idx = 2
        while f"{name}-{idx}" in existing:
            idx += 1
        name = f"{name}-{idx}"

    result = await agent_manager.launch_agent(
        name=name,
        working_dir=working_dir,
        model=body.get("model"),
    )
    if result.get("ok"):
        result["session_name"] = name
    return result


# ── WebSocket Endpoints ─────────────────────────────────────────────────────


@app.websocket("/ws/session/{name}")
async def ws_session(websocket: WebSocket, name: str):
    """Stream real-time SDK events for a specific session."""
    await websocket.accept()

    snapshot = agent_manager.get_agent_snapshot(name)
    if not snapshot:
        await websocket.send_json({"type": "error", "text": f"Agent '{name}' not found"})
        await websocket.close()
        return

    # Send initial snapshot
    await websocket.send_json({"type": "snapshot", **snapshot})

    # Subscribe to live events
    q = agent_manager.subscribe_agent(name)
    try:
        while True:
            event = await q.get()
            if event is None:
                break  # agent was stopped
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        agent_manager.unsubscribe_agent(name, q)


@app.websocket("/ws/fleet")
async def ws_fleet(websocket: WebSocket):
    """Stream fleet-wide session list updates via pub/sub."""
    await websocket.accept()

    # Send initial state
    await websocket.send_json({
        "type": "fleet_update",
        "sessions": agent_manager.list_agents(),
    })

    # Subscribe to live updates
    q = agent_manager.subscribe_fleet()
    try:
        while True:
            event = await q.get()
            if event is None:
                break
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        agent_manager.unsubscribe_fleet(q)


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
