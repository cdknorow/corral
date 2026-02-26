# CLAUDE.md - Project Guide

## Project Overview
**Agent Fleet** is a multi-agent orchestration system for managing AI coding agents (Claude and Gemini) running in parallel git worktrees using tmux. It features a web dashboard, real-time logging, complete session history with FTS5 search, and git state polling.

## Project Structure Highlights
- `src/agent_fleet/`: Main package directory
  - `launch_agents.sh`: Bash script to discover worktrees, launch tmux sessions, and start the web server.
  - `web_server.py`: FastAPI web dashboard (REST + WebSocket endpoints).
  - `session_manager.py`: Core logic for tmux discovery, pane targeting, history loading, session launch/kill.
  - `session_store.py`: SQLite storage (WAL mode) for notes, tags, session index, FTS, and summarizer queue.
  - `PROTOCOL.md`: Protocol for agents to follow (status/summary reporting).
- `DEVELOP.md`: Detailed developer guide containing full project structure, API endpoints, and database schema.
- `pyproject.toml`: Project configuration and dependencies.

## Key Commands

### Setup & Installation
```bash
# Install the package in editable mode
pip install -e .
```

### Launching the Fleet
```bash
# Launch Claude agents and web dashboard for worktrees in the current directory
./src/agent_fleet/launch_agents.sh .

# Launch Gemini agents from a specific path
./src/agent_fleet/launch_agents.sh <path-to-root> gemini

# Override the web dashboard port (default: 8420)
FLEET_PORT=9000 ./src/agent_fleet/launch_agents.sh .
```

### Running the Web Dashboard (standalone)
```bash
# Start the web dashboard (default: http://localhost:8420)
agent-fleet

# Custom host/port
agent-fleet --host 127.0.0.1 --port 9000
```

### Managing Agents
- **Attach to tmux (Claude):** `tmux attach -t claude-agent-1`
- **Attach to tmux (Gemini):** `tmux attach -t gemini-agent-1`
- **Attach to web server:** `tmux attach -t fleet-web-server`
- **Switch window:** `Ctrl+b n` (next) / `Ctrl+b p` (previous)
- **Detach tmux:** `Ctrl+b d`

## Agent Protocol
Agents must emit status and summary lines for the dashboard to track:
- `||SUMMARY: <Goal Description>||`: High-level goal (emit once at start or when goal changes).
- `||STATUS: <Task Description>||`: Current task (emit before/after subtasks).

## Development Guidelines
- **Build System:** Setuptools with `pyproject.toml`.
- **Dependencies:** `fastapi`, `uvicorn`, `jinja2` (Python 3.8+).
- **Database:** SQLite (`~/.agent-fleet/sessions.db`) using WAL mode.
- **Logs:** Agents stream output to `/tmp/<agent_type>_fleet_<folder_name>.log` via `tmux pipe-pane`.
