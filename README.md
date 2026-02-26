# Agent Fleet

<!-- TODO: Add a high-quality GIF here demonstrating launching the fleet and the real-time web dashboard. -->
<img width="1512" height="822" alt="image" src="https://github.com/user-attachments/assets/7534c1c4-5431-4e63-a5e3-4ec667e8bcb5" />


A multi-agent orchestration system for managing AI coding agents (Claude and Gemini) running in parallel git worktrees using tmux.

## Features

- **Multi-agent support** — Launch and manage both Claude and Gemini agents side-by-side
- **Parallel worktrees** — Each agent runs in its own git worktree and tmux session
- **Web dashboard** — Real-time monitoring with pane capture, status tracking, and command input
- **Session history** — Browse past sessions from both Claude (`~/.claude/projects/`) and Gemini (`~/.gemini/tmp/`)
- **Full-text search** — Search across all session content using FTS5
- **Auto-summarization** — Background summarization of sessions using Claude
- **Session notes & tags** — Add markdown notes and color-coded tags to any session
- **Remote control** — Send commands, navigate modes, and manage agents from the dashboard
- **Attach / Kill** — Open a terminal attached to any agent's tmux session, or kill it directly from the UI
- **Git integration** — Background polling tracks branch, commits, and remote URL per agent
- **PR linking** — Stored remote URLs enable linking sessions to pull requests
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

<!-- TODO: Add a GIF here showing the live pane capture updating, sending commands to an agent, and toggling plan/base mode. -->
The web dashboard provides quick-action buttons for each live session:

| Action | Description |
|---|---|
| **Esc / Arrow / Enter** | Send navigation keys to the agent |
| **Plan Mode** | Toggle Claude Code plan mode |
| **Accept Edits** | Toggle Claude Code auto-accept mode |
| **Bash Mode** | Send `!` command to enter bash mode |
| **Base Mode** | Toggle base mode |
| **/compact / /clear** | Send compress or clear commands (adapts per agent type) |
| **Reset** | Compress then clear the session |
| **Attach** | Open a local terminal window attached to the agent's tmux session |
| **Restart** | Restart the agent in the same tmux pane |
| **Kill** | Terminate the tmux session and remove it from the dashboard |

You can also type arbitrary commands in the input bar and send them to the selected agent.

### Session history search and filtering

<!-- TODO: Add a GIF here showing full-text search across past Claude/Gemini sessions and adding notes/tags. -->
The sidebar History section includes a search bar and filters for browsing your entire AI coding session history.

On startup, the server launches three background services:

1. **Session indexer** (every 2 min) — Indexes all Claude sessions from `~/.claude/projects/**/*.jsonl` and Gemini sessions from `~/.gemini/tmp/*/chats/session-*.json`, builds a full-text search index (FTS5), and queues new sessions for auto-summarization
2. **Batch summarizer** — Continuously processes the summarization queue using Claude CLI
3. **Git poller** (every 2 min) — Polls git branch, commit, and remote URL for each live agent and stores snapshots in SQLite

Features:

- **Search** — Type in the search bar to find sessions by content (uses SQLite FTS5 with porter stemming)
- **Filter by tag** — Select a tag from the dropdown to narrow results
- **Filter by source** — Show only Claude or Gemini sessions
- **Pagination** — Browse through all sessions with prev/next controls
- **URL bookmarking** — Session URLs use hash routing (`#session/<id>`) so you can bookmark or share links
- **Notes & tags** — Add markdown notes and color-coded tags to any session, stored in `~/.agent-fleet/sessions.db`

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

## Advanced Information

For information on project structure, API endpoints, and the database schema, please see [DEVELOP.md](DEVELOP.md).

## Dependencies

- Python 3.8+
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) — Web server
- [Jinja2](https://jinja.palletsprojects.com/) — HTML templating
- tmux — Session management
- Claude CLI (optional) — Powers auto-summarization

## Contributing

We welcome contributions! Whether it's adding support for new AI coding agents natively or improving the web dashboard, please feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
