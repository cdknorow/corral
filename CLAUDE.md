# CLAUDE.md - Project Guide

## Project Overview
**Claude Fleet** is a multi-agent orchestration system for managing AI coding agents (Claude and Gemini) running in parallel git worktrees using tmux, with a web-based dashboard for monitoring, control, and session history.

## Project Structure
- `src/agent_fleet/`: Main package directory
  - **Backend (Python)**
    - `web_server.py`: FastAPI web dashboard — REST API, WebSocket endpoints, serves the SPA.
    - `session_manager.py`: Core logic for tmux discovery, pane targeting, history loading, session launch/kill/restart.
    - `session_store.py`: SQLite-backed storage for session notes, auto-summaries, and tags (`~/.agent-fleet/sessions.db`).
    - `auto_summarizer.py`: AI-powered session auto-summarization using Claude.
    - `log_streamer.py`: Async log file tailing and snapshot for streaming live agent output.
    - `launch_agents.sh`: Bash script to discover worktrees, launch tmux sessions, and start the web server.
    - `PROTOCOL.md`: Protocol for agents to follow (status/summary reporting).
  - **Frontend (JavaScript ES Modules)**
    - `templates/index.html`: Main SPA template (Jinja2).
    - `static/app.js`: App entry point — initializes event listeners and global functions.
    - `static/state.js`: Shared application state (current session, etc.).
    - `static/api.js`: API client functions for REST endpoints.
    - `static/websocket.js`: WebSocket connection management for live fleet updates.
    - `static/render.js`: Rendering functions for session lists, chat history, and status updates.
    - `static/sessions.js`: Session selection and loading logic.
    - `static/sidebar.js`: Sidebar toggle, search/filter, and history list management.
    - `static/notes.js`: Session notes loading, editing, rendering, and tab switching.
    - `static/tags.js`: Tag management UI (create, assign, remove, sidebar dots).
    - `static/controls.js`: Live session controls (send commands, kill, restart, attach).
    - `static/capture.js`: Tmux pane capture display and refresh.
    - `static/modals.js`: Modal dialogs (info, launch session, directory browser).
    - `static/browser.js`: Directory browser for launching new sessions.
    - `static/syntax.js`: Syntax highlighting for code blocks.
    - `static/utils.js`: Shared utilities (escapeHtml, showToast, etc.).
    - `static/style.css`: All dashboard styles.
- `pyproject.toml`: Project configuration and dependencies.
- `.gitignore`: Ignoring `src/agent_fleet.egg-info/`.

## Key Commands

### Setup & Installation
```bash
# Install the package in editable mode
pip install -e .
```

### Launching the Fleet
```bash
# Launch agents and web dashboard for worktrees in a target directory
./src/agent_fleet/launch_agents.sh /path/to/worktrees

# Override the web dashboard port (default: 8420)
FLEET_PORT=9000 ./src/agent_fleet/launch_agents.sh /path/to/worktrees
```

### Running the Web Dashboard (standalone)
```bash
# Start the web dashboard
agent-fleet

# Custom host/port
agent-fleet --host 127.0.0.1 --port 9000
```

### Managing Agents
- **Attach to tmux:** `tmux attach -t claude-agent-1`
- **Attach to web server:** `tmux attach -t fleet-web-server`
- **Switch window:** `Ctrl+b n` (next) / `Ctrl+b p` (previous)
- **Detach tmux:** `Ctrl+b d`

## Agent Protocol
Agents must emit status and summary lines for the dashboard to track:
- `||SUMMARY: <Goal Description>||`: High-level goal (emit once at start or when goal changes).
- `||STATUS: <Task Description>||`: Current task (emit before/after subtasks).

## Development Guidelines
- **Build System:** Setuptools with `pyproject.toml`.
- **Dependencies:** `fastapi`, `uvicorn[standard]`, `jinja2` (Python 3.8+).
- **Frontend:** Vanilla JavaScript ES modules (no build step). Uses `marked.js` for markdown rendering and `highlight.js` for syntax highlighting (loaded from CDN).
- **Database:** SQLite via `session_store.py`, stored at `~/.agent-fleet/sessions.db`. Stores notes, auto-summaries, tags, and session metadata.
- **Logs:** Agents stream output to `/tmp/claude_fleet_[folder_name].log` via `tmux pipe-pane`.
- **API Pattern:** FastAPI REST endpoints under `/api/`, single WebSocket at `/ws/fleet` for live updates. Synchronous SQLite calls wrapped with `asyncio.to_thread()`.
