# CLAUDE.md - Project Guide

## Project Overview
**Claude Fleet** is a multi-agent orchestration system for managing AI coding agents running in parallel git worktrees using tmux.

## Project Structure
- `src/agent_fleet/`: Main package directory
  - `launch_agents.sh`: Bash script to discover worktrees, launch tmux sessions, and start the web server.
  - `web_server.py`: FastAPI web dashboard (REST + WebSocket endpoints).
  - `session_manager.py`: Core logic for tmux discovery, pane targeting, history loading, session launch/kill.
  - `log_streamer.py`: Async log file tailing and snapshot for streaming.
  - `PROTOCOL.md`: Protocol for agents to follow (status/summary reporting).
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
- **Dependencies:** `fastapi`, `uvicorn`, `jinja2` (Python 3.8+).
- **Logs:** Agents stream output to `/tmp/claude_fleet_[folder_name].log` via `tmux pipe-pane`.
