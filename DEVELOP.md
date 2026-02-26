# Developer Documentation

Welcome to the development guide for Corral! This document covers the project structure, API endpoints, and database schema to help you understand how the system works and how to contribute.

## Project Structure

```
src/corral/
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
    ├── websocket.js      # Corral WebSocket subscription
    ├── syntax.js         # Syntax highlighting for code blocks
    └── utils.js          # Escape functions, toast notifications
```

## API Endpoints

The dashboard is powered by a FastAPI backend:

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard |
| `GET` | `/api/sessions/live` | List active corral agents with status and git branch |
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
| `WS` | `/ws/corral` | Real-time corral status updates (polls every 3s) |

## Database

All persistent state is stored in a SQLite database at `~/.corral/sessions.db` (using WAL mode for concurrent access):

| Table | Purpose |
|---|---|
| `session_index` | Session metadata, source type, file paths, timestamps, message counts |
| `session_fts` | FTS5 virtual table for full-text search (porter stemming, unicode61) |
| `session_meta` | Notes, auto-summaries, edit timestamps |
| `tags` | Tag definitions with colors |
| `session_tags` | Many-to-many tag-to-session assignments |
| `summarizer_queue` | Pending and completed auto-summarization jobs |
| `git_snapshots` | Git branch, commit hash, subject, timestamp, and remote URL per agent |
