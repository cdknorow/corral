# Corral

**Multi-agent orchestration for AI coding agents.**

Corral brings sanity to coding with AI agents without disrupting your workflow. Activity across all your agents is visible so you can see which ones need attention at a glance.

Corral is an MIT-licensed multi-agent orchestration application built with tmux, FastAPI, and vanilla HTML5/JS for easy extensibility and modification.

---

## Features

- **Multi-agent support** — Launch and manage both Claude and Gemini agents side-by-side across worktrees
- **Web dashboard** — Real-time monitoring with terminal capture, status tracking, and command input
- **Session history** — Browse past sessions with advanced filters (date range, agent type, tags, full-text search)
- **Full-text search** — Search across all session content using SQLite FTS5 with porter stemming
- **Auto-summarization** — Sessions are automatically summarized and indexed for search
- **Scheduled jobs** — Create cron-scheduled tasks that launch agents in isolated worktrees
- **Webhook notifications** — Get notified via webhook when agents need input or complete work
- **Session notes & activity** — Add markdown notes and track activity per session
- **Remote control** — Send commands, navigate modes, and manage agents from the dashboard
- **Git integration & PR linking** — Tracks commits, branches, and remote URLs per agent and session
- **Custom macros** — Add configurable toolbar buttons for frequently used commands

---

## Installation

Install from PyPI:

```bash
pip install agent-corral
```

Or install directly from GitHub:

```bash
pip install git+https://github.com/cdknorow/corral.git
```

---

## Quick Start

Start the web dashboard:

```bash
# Default: http://localhost:8420
corral

# Custom host/port
corral --host 127.0.0.1 --port 9000
```

Or use the launcher to discover worktree subdirectories, create an agent for each one, and start the dashboard:

```bash
# Launch Claude agents and web dashboard for worktrees in the current directory
launch-corral

# Launch Gemini agents from a specific path
launch-corral <path-to-root> gemini
```

---

## Dashboard Overview

The web dashboard provides quick-action buttons for each live session:

| Action | Description |
|---|---|
| **Esc / Arrow / Enter** | Send navigation keys to the agent |
| **Plan Mode** | Toggle Claude Code plan mode |
| **Accept Edits** | Toggle Claude Code auto-accept mode |
| **Bash Mode** | Send `!` command to enter bash mode |
| **/compact / /clear** | Send compress or clear commands |
| **Attach** | Open a local terminal attached to the agent's tmux session |
| **Restart** | Restart the agent in the same tmux pane |
| **Kill** | Terminate the tmux session |

You can also type arbitrary commands in the input bar and send them to the selected agent.

---

## Background Services

On startup, Corral launches three background services:

1. **Session indexer** (every 2 min) — Indexes all Claude sessions from `~/.claude/projects/**/*.jsonl` and Gemini sessions from `~/.gemini/tmp/*/chats/session-*.json`, builds a full-text search index (FTS5), and queues new sessions for auto-summarization
2. **Batch summarizer** — Continuously processes the summarization queue using Claude CLI
3. **Git poller** (every 2 min) — Polls git branch, commit, and remote URL for each live agent and stores snapshots in SQLite

---

## Scheduled Jobs

Corral supports cron-scheduled jobs that automatically launch agents in isolated git worktrees. Create and manage them from the Scheduled section in the sidebar.

Each scheduled job:

- Creates a fresh git worktree from the specified branch
- Launches an agent (Claude or Gemini) with optional CLI flags
- Sends the configured prompt to the agent
- Monitors the session with a configurable timeout
- Cleans up the worktree on completion (optional)
- Tags the session as "scheduled" for easy filtering in history

See the [Jobs API](api/jobs.md) for programmatic access.

---

## Claude Code Hooks

To fully integrate Claude Code's agentic state and task management into the Corral dashboard, configure the provided hook scripts in your Claude Code `settings.json` (usually at `~/.claude.json` or `~/.claude/settings.json`):

```json
"hooks": {
    "PostToolUse": [
      {
        "matcher": "TaskCreate|TaskUpdate",
        "hooks": [
          {
            "type": "command",
            "command": "corral-hook-task-sync"
          }
        ]
      },
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "corral-hook-agentic-state"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "corral-hook-agentic-state"
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "corral-hook-agentic-state"
          }
        ]
      }
    ]
}
```

---

## Agent Protocol

Agents emit structured markers using the `||PULSE:<EVENT_TYPE> <payload>||` format. The dashboard parses these from agent output in real time:

```
||PULSE:STATUS <Short description of current task>||
||PULSE:SUMMARY <One-sentence high-level goal>||
||PULSE:CONFIDENCE <1-5> <short reason>||
```

The protocol is automatically injected via `PROTOCOL.md` when launching agents.

---

## Remote Server (SSH)

If running Corral on a remote server, forward the dashboard port over SSH:

```bash
ssh -L 8420:localhost:8420 user@remote-host
```

Then open `http://localhost:8420` in your local browser. Add to `~/.ssh/config` for persistence:

```
Host my-dev-server
    HostName remote-host
    User user
    LocalForward 8420 localhost:8420
```

---

## Dependencies

- Python 3.8+
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) — Web server
- [Jinja2](https://jinja.palletsprojects.com/) — HTML templating
- [aiosqlite](https://github.com/omnilib/aiosqlite) — Async SQLite (WAL mode)
- tmux — Session management
- Claude CLI (optional) — Powers auto-summarization

---

## Contributing

We welcome contributions! Whether it's adding support for new AI coding agents or improving the web dashboard, please feel free to open an issue or submit a pull request on [GitHub](https://github.com/cdknorow/corral).

## License

MIT License.
