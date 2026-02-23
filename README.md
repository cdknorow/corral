# Claude Agent Worktree Orchestration
<img width="1483" height="855" alt="image" src="https://github.com/user-attachments/assets/c6bb192f-12f4-4acc-8f39-d356149c0b2a" />

This is a workflow designed for people using worktrees and multiple agents.

## Installation

You can install the tool directly from GitHub:

```bash
pip install git+https://github.com/cdknorow/workflow_orchestration.git
```

Or for local development:

```bash
# Clone the repository
git clone https://github.com/cdknorow/workflow_orchestration.git
cd workflow_orchestration

# Install in editable mode
pip install -e .
```

## Usage

Run the launcher and it will create an agent for each worktree inside a tmux session. The status of each of your models will be displayed inside the Dashboard.

```bash
# Launch agents and dashboard from current directory
agent-fleet

# Launch agents and dashboard from a specific path
agent-fleet <path-to-root> --model gemini

# Or use the script directly
./src/agent_fleet/launch_agents.sh <path-to-root> claude

# Or launch just the dashboard if agents are already running
agent-fleet --no-launch
```




 Files Created

  ┌──────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                 File                 │                                             Purpose                                             │
  ├──────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ src/agent_fleet/session_manager.py   │ Core logic: tmux discovery, history.jsonl parsing, send commands, capture pane, launch sessions │
  ├──────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ src/agent_fleet/log_streamer.py      │ Async log file tailing + snapshot for WebSocket streaming                                       │
  ├──────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ src/agent_fleet/web_server.py        │ FastAPI app with 8 REST endpoints + 2 WebSocket endpoints                                       │
  ├──────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ src/agent_fleet/templates/index.html │ Single-page HTML with sidebar + main content layout                                             │
  ├──────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ src/agent_fleet/static/style.css     │ Dark theme CSS matching the TUI aesthetic                                                       │
  ├──────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ src/agent_fleet/static/app.js        │ Client-side JS: WebSocket client, DOM updates, session switching, command sending               │
  └──────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────┘

  File Modified

  ┌────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │      File      │                                                       Changes                                                       │
  ├────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ pyproject.toml │ Added fastapi, uvicorn[standard], jinja2 deps; agent-fleet-web entry point; templates/*.html, static/* package-data │
  └────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Verification Results

  - All modules import cleanly
  - GET / returns the dashboard HTML (200)
  - GET /api/sessions/live returns 0 sessions (no agents running, expected)
  - GET /api/sessions/history returns 313 historical sessions from ~/.claude/projects/
  - pip install -e . succeeds with all dependencies

  How to Use

  # Start the web dashboard
  agent-fleet-web

  # With custom host/port
  agent-fleet-web --port 9000

  # With auto-reload for development
  agent-fleet-web --reload

  Then open http://localhost:8420 in your browser.
