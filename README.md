# Agent Fleet

<img width="1512" height="824" alt="image" src="https://github.com/user-attachments/assets/0e1b1291-f288-4e13-baae-5ed382f88e84" />

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

## Project Structure

```
src/agent_fleet/
├── launch_agents.sh      # Shell script to discover worktrees, launch tmux sessions,
│                         #   and start the web server
├── web_server.py         # FastAPI server (REST + WebSocket endpoints)
├── session_manager.py    # Core logic: tmux discovery, pane targeting, history loading,
│                         #   session launch/kill, terminal attach
├── session_store.py      # SQLite storage: notes, tags, session index, FTS, summarizer queue
├── session_indexer.py    # Background indexer + batch summarizer
├── auto_summarizer.py    # AI-powered session summarization via Claude CLI
├── git_poller.py         # Background git branch/commit polling for live agents
├── log_streamer.py       # Async log file tailing + snapshot for streaming
├── PROTOCOL.md           # Agent status/summary reporting protocol
├── templates/
│   └── index.html        # Dashboard HTML
└── static/
    ├── style.css         # Dark theme CSS
    ├── app.js            # Entry point
    ├── state.js          # Client state management
    ├── api.js            # REST API fetch functions
    ├── render.js         # DOM rendering (session lists, chat, pagination)
    ├── sessions.js       # Session selection and management
    ├── controls.js       # Quick actions, mode toggling, session controls
    ├── capture.js        # Real-time pane text rendering
    ├── commits.js        # Git commit history display
    ├── tags.js           # Tag CRUD and UI
    ├── notes.js          # Notes editing and markdown rendering
    ├── modals.js         # Launch and info modal dialogs
    ├── browser.js        # Directory browser for launch dialog
    ├── sidebar.js        # Sidebar and command pane resizing
    ├── websocket.js      # Fleet WebSocket subscription
    ├── syntax.js         # Syntax highlighting for code blocks
    └── utils.js          # Escape functions, toast notifications
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard |
| `GET` | `/api/sessions/live` | List active fleet agents with status and git branch |
| `GET` | `/api/sessions/live/{name}` | Detailed info for a live session (`?agent_type=`) |
| `GET` | `/api/sessions/live/{name}/capture` | Capture tmux pane content |
| `GET` | `/api/sessions/live/{name}/info` | Enriched session metadata (git branch, commit info) |
| `GET` | `/api/sessions/live/{name}/git` | Git commit snapshots for a live agent (`?limit=`) |
| `POST` | `/api/sessions/live/{name}/send` | Send a command to an agent |
| `POST` | `/api/sessions/live/{name}/keys` | Send raw tmux keys (Escape, BTab, etc.) |
| `POST` | `/api/sessions/live/{name}/kill` | Kill a tmux session |
| `POST` | `/api/sessions/live/{name}/restart` | Restart the agent in the same pane |
| `POST` | `/api/sessions/live/{name}/attach` | Open a terminal attached to the session |
| `POST` | `/api/sessions/launch` | Launch a new agent session |
| `GET` | `/api/sessions/history` | Paginated history (`?page=`, `?page_size=`, `?q=`, `?tag_id=`, `?source_type=`) |
| `GET` | `/api/sessions/history/{id}` | Get messages for a historical session |
| `GET` | `/api/sessions/history/{id}/git` | Git commits during a session's time range |
| `GET` | `/api/sessions/history/{id}/notes` | Get notes and auto-summary |
| `PUT` | `/api/sessions/history/{id}/notes` | Save notes |
| `POST` | `/api/sessions/history/{id}/resummarize` | Force re-summarization |
| `GET` | `/api/sessions/history/{id}/tags` | Get tags for a session |
| `POST` | `/api/sessions/history/{id}/tags` | Add a tag to a session |
| `DELETE` | `/api/sessions/history/{id}/tags/{tag_id}` | Remove a tag from a session |
| `GET` | `/api/tags` | List all tags |
| `POST` | `/api/tags` | Create a new tag |
| `DELETE` | `/api/tags/{tag_id}` | Delete a tag |
| `POST` | `/api/indexer/refresh` | Trigger immediate re-index |
| `GET` | `/api/filesystem/list` | List directories for the launch browser |
| `WS` | `/ws/fleet` | Real-time fleet status updates (polls every 3s) |

## Database

All persistent state is stored in a SQLite database at `~/.agent-fleet/sessions.db` (WAL mode):

| Table | Purpose |
|---|---|
| `session_index` | Session metadata, source type, file paths, timestamps, message counts |
| `session_fts` | FTS5 virtual table for full-text search (porter stemming, unicode61) |
| `session_meta` | Notes, auto-summaries, edit timestamps |
| `tags` | Tag definitions with colors |
| `session_tags` | Many-to-many tag-to-session assignments |
| `summarizer_queue` | Pending and completed auto-summarization jobs |
| `git_snapshots` | Git branch, commit hash, subject, timestamp, and remote URL per agent |

## Dependencies

- Python 3.8+
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) — Web server
- [Jinja2](https://jinja.palletsprojects.com/) — HTML templating
- tmux — Session management
- Claude CLI (optional) — Powers auto-summarization
