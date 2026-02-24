# Agent Fleet

<img width="1512" height="824" alt="image" src="https://github.com/user-attachments/assets/0e1b1291-f288-4e13-baae-5ed382f88e84" />

A multi-agent orchestration system for managing AI coding agents (Claude and Gemini) running in parallel git worktrees using tmux.

## Features

- **Multi-agent support** — Launch and manage both Claude and Gemini agents side-by-side
- **Parallel worktrees** — Each agent runs in its own git worktree and tmux session
- **Web dashboard** — Real-time monitoring with pane capture, status tracking, and command input
- **Session history** — Browse past sessions from both Claude (`~/.claude/projects/`) and Gemini (`~/.gemini/tmp/`)
- **Remote control** — Send commands, navigate modes, and manage agents from the dashboard
- **Attach / Kill** — Open a terminal attached to any agent's tmux session, or kill it directly from the UI
- **Stale session cleanup** — Dead sessions are automatically detected and removed

## Installation

Install directly from GitHub:

```bash
pip install git+https://github.com/cdknorow/workflow_orchestration.git
```

Or for local development:

```bash
git clone https://github.com/cdknorow/workflow_orchestration.git
cd workflow_orchestration
pip install -e .
```

## Usage

### Launch agents and web dashboard

The launcher discovers worktree subdirectories, creates a tmux session with an agent for each one, and starts the web dashboard in its own tmux session:

```bash
# Launch Claude agents and web dashboard for worktrees in the current directory
./src/agent_fleet/launch_agents.sh .

# Launch Gemini agents from a specific path
./src/agent_fleet/launch_agents.sh <path-to-root> gemini

# Override the default web dashboard port (default: 8420)
FLEET_PORT=9000 ./src/agent_fleet/launch_agents.sh .

# Skip launching the web server
SKIP_WEB_SERVER=1 ./src/agent_fleet/launch_agents.sh .
```

### Web dashboard (standalone)

```bash
# Start the web dashboard directly (default: http://localhost:8420)
agent-fleet

# Custom host/port
agent-fleet --host 127.0.0.1 --port 9000

# Auto-reload for development
agent-fleet --reload
```

### Managing sessions from the dashboard

The web dashboard provides quick-action buttons for each live session:

| Action | Description |
|---|---|
| **Esc / Arrow / Enter** | Send navigation keys to the agent |
| **Plan Mode** | Toggle Claude Code plan mode |
| **Accept Edits** | Toggle Claude Code auto-accept mode |
| **/compact / /clear** | Send compress or clear commands (adapts per agent type) |
| **Reset** | Compress then clear the session |
| **Attach** | Open a local terminal window attached to the agent's tmux session |
| **Kill** | Terminate the tmux session and remove it from the dashboard |

You can also type arbitrary commands in the input bar and send them to the selected agent.

### Manual tmux management

```bash
# Attach to a specific agent session
tmux attach -t claude-agent-1

# Switch between windows
Ctrl+b n  # next
Ctrl+b p  # previous

# Detach from tmux
Ctrl+b d
```

## Agent Protocol

Agents emit structured markers that the dashboard parses for live status:

```
||STATUS: <Short description of current task>||
||SUMMARY: <One-sentence high-level goal>||
```

The protocol is automatically injected via `PROTOCOL.md` when launching agents. See [`src/agent_fleet/PROTOCOL.md`](src/agent_fleet/PROTOCOL.md) for the full specification.

## Project Structure

```
src/agent_fleet/
├── launch_agents.sh      # Shell script to discover worktrees, launch tmux sessions,
│                         #   and start the web server
├── web_server.py         # FastAPI web dashboard (REST + WebSocket endpoints)
├── session_manager.py    # Core logic: tmux discovery, pane targeting, history loading,
│                         #   session launch/kill, terminal attach
├── log_streamer.py       # Async log file tailing + snapshot for streaming
├── PROTOCOL.md           # Agent status/summary reporting protocol
├── templates/
│   └── index.html        # Single-page web dashboard HTML
└── static/
    ├── style.css         # Dark theme CSS
    └── app.js            # Client-side JS: WebSocket, DOM updates, session management
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/sessions/live` | List active fleet agents with status |
| `GET` | `/api/sessions/live/{name}` | Detailed info for a live session (accepts `?agent_type=`) |
| `GET` | `/api/sessions/live/{name}/capture` | Capture tmux pane content (accepts `?agent_type=`) |
| `POST` | `/api/sessions/live/{name}/send` | Send a command to an agent |
| `POST` | `/api/sessions/live/{name}/keys` | Send raw tmux keys (Escape, BTab, etc.) |
| `POST` | `/api/sessions/live/{name}/kill` | Kill a tmux session |
| `POST` | `/api/sessions/live/{name}/attach` | Open a terminal attached to the session |
| `POST` | `/api/sessions/launch` | Launch a new agent session |
| `GET` | `/api/sessions/history` | List historical sessions (Claude + Gemini) |
| `GET` | `/api/sessions/history/{id}` | Get messages for a historical session |
| `WS` | `/ws/fleet` | Real-time fleet status updates (polls every 3s) |

## Dependencies

- Python 3.8+
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) — Web dashboard
- [Jinja2](https://jinja.palletsprojects.com/) — HTML templating
- tmux — Session management
