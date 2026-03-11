# Live Sessions

Live Sessions is the core real-time monitoring and control interface for Corral. It lets you observe and interact with AI coding agents (Claude and Gemini) as they work in parallel git worktrees — all from a single browser tab.

Each live session represents one agent running in a tmux session. The dashboard provides a browser-based view of the agent's terminal output, activity timeline, tasks, notes, and conversation history, all updating in real time.

---

## Getting started

### Start the dashboard

```bash
# Dashboard only
corral

# Dashboard + agents for all worktrees in current directory
launch-corral
```

Open `http://localhost:8420` in your browser. The sidebar shows **Live Sessions** at the top with any running agents grouped by worktree name.

### Launch a new session

1. Click the **+ New** button in the Live Sessions sidebar header.
2. Fill in the **Launch New Session** modal:
    - **Agent Name** (optional) — A display name like "Auth Feature"
    - **Working Directory** — The git repo path (click **Browse** to navigate)
    - **Agent Type** — Claude or Gemini
    - **Flags** (optional) — CLI flags like `--verbose`. Use the shortcut buttons for `--chrome` and `--dangerously-skip-permissions`.
3. Click **Launch**.

The new session appears in the sidebar. Click it to select.

!!! tip
    You can also launch agents from the command line with `launch-corral <path-to-worktrees>`, which discovers subdirectories and creates one agent per worktree automatically.

---

## Session view

When you select a live session, the main panel shows three areas: the **session header**, the **terminal area**, and the **command pane**.

### Session header

The header displays:

- **Status dot** — Color-coded: green (active), yellow (waiting for input), gray (stale)
- **Agent type badge** — `CLAUDE` or `GEMINI` with distinct styling
- **Session name** — Display name or worktree folder name
- **Branch** — Current git branch with a copy-to-clipboard button
- **Goal** — High-level objective parsed from `||PULSE:SUMMARY||` markers
- **Status** — Current task parsed from `||PULSE:STATUS||` markers

The header also contains action buttons:

| Button | Description |
|--------|-------------|
| **Info** | View session metadata (tmux session name, attach command, working directory, log path, branch, latest commit) |
| **Attach** | Open a native terminal window attached to the agent's tmux session |
| **Restart** | Restart the agent in the same working directory (optionally add new flags) |
| **Kill** | Terminate the tmux session and stop the agent |

### Waiting for input banner

When the agent needs a response, a yellow banner appears above the terminal:

> ⏳ Agent is waiting for input

The sidebar also shows a **NEEDS INPUT** badge on that session.

### Terminal area

The terminal area shows the agent's live output. Two rendering modes are available:

- **xterm.js** — Full terminal emulation with colors and formatting (default for Claude)
- **Semantic blocks** — Parsed output blocks (default for Gemini)

You can change the default renderer per agent type in **Settings** (gear icon, top right).

!!! info
    When you select text in the terminal, updates pause automatically to prevent the selection from being lost. A "Updates paused — text selected" badge appears until you deselect.

### Command pane

The command pane at the bottom has a resizable toolbar and a text input area.

**Toolbar buttons (left to right):**

| Section | Buttons | Description |
|---------|---------|-------------|
| Mode toggles | Plan Mode, Accept Edits, Bash Mode | Toggle Claude Code modes via Shift+Tab |
| Macros | `/compact`, `/clear`, custom macros | Send common commands with one click |
| Add macro | **+** | Create a custom macro button with a label and command |
| Navigation | **Esc**, **↑**, **↓**, **↵**, **Send** | Send navigation keys or submit the typed command |

Type any command in the textarea and click **Send** (or press Enter) to send it to the agent.

!!! tip
    Your input text is preserved per-session — switch between sessions without losing what you were typing.

---

## Side panel

The right-side panel has four tabs: **Activity**, **Tasks**, **Notes**, and **History**. The panel is resizable by dragging its left edge.

### Activity

The Activity tab shows a real-time event timeline of everything the agent is doing. Each event has an icon, description, and timestamp.

Event types include:

- **Read**, **Write**, **Edit** — File operations
- **Bash** — Shell commands
- **Grep**, **Glob** — Search operations
- **Web** — Web fetches
- **Tasks**, **Subagents** — Task and sub-agent activity
- **Status**, **Goal**, **Confidence** — PULSE protocol events
- **Stop/Notify** — Agent pause events

Use the **Filter** dropdown to toggle event categories on or off. An **activity chart** at the bottom shows the event distribution over time.

### Tasks

Create and manage task checklists for each session. Tasks are drag-reorderable and synchronized with Claude Code via hooks.

- Click to add a new task
- Check the box to mark complete
- Drag to reorder

!!! tip
    Configure the `corral-hook-task-sync` hook in your Claude Code settings to keep tasks in sync between the agent and the dashboard. See the [home page](index.md#claude-code-hooks) for hook configuration.

### Notes

Write markdown notes about each session. Click the notes area to edit, and the content renders as formatted markdown when you click away.

### History

The History tab shows the live JSONL conversation log — the full chat transcript between you and the agent. It displays:

- **User messages** — Your prompts and commands
- **Assistant messages** — Agent responses
- **Tool cards** — Expandable cards for Bash commands, Edit diffs, Read file contents, and other tool uses

The transcript polls for updates every second while the tab is active.

---

## Session management

### Renaming a session

Right-click a session in the sidebar to open the context menu and set a custom display name.

### Restarting a session

Click **Restart** in the session header. A modal appears where you can optionally add new CLI flags. The agent restarts in the same working directory with a new session UUID.

### Resuming a historical session

You can pick up where a previous session left off:

1. Find the completed session in the **History** section of the sidebar.
2. Click the **Resume** button in the historical session's header.
3. The Resume modal shows a list of currently live agents. Select which agent should continue the session.
4. Corral restarts the selected agent with `--resume`, loading the full conversation context from the previous session.

!!! warning
    Resume is supported for **Claude agents only**. Gemini does not support session resume.

!!! info
    If Corral restarts, resumed sessions are automatically re-resumed via `resume_persistent_sessions()`. The resume linkage is stored in the database.

---

## Session info modal

Click **Info** to view full session metadata:

| Field | Description |
|-------|-------------|
| Agent Name | Display name of the session |
| Agent Type | `claude` or `gemini` |
| Tmux Session | Full tmux session name (e.g., `claude-<uuid>`) |
| Attach Command | `tmux attach -t <session>` with a Copy button |
| Working Directory | Filesystem path for the agent's repo |
| Log Path | Path to the agent's log file |
| Pane Title | tmux pane title |
| Branch | Current git branch |
| Latest Commit | Most recent commit hash and message |

---

## How it works

- Each session maps to one tmux session running one agent in one working directory
- Sessions are identified by UUIDs (tmux session name: `{agent_type}-{uuid}`)
- The dashboard auto-discovers sessions by querying tmux for panes matching the UUID naming convention
- WebSocket `/ws/corral` provides corral-wide session list updates every 3 seconds
- WebSocket `/ws/terminal/{name}` streams raw terminal content at 0.5-second intervals
- Sessions persist across Corral restarts — the `live_sessions` database table tracks registered sessions and relaunches them on startup

---

## Configuration

| Setting | Method | Default | Description |
|---------|--------|---------|-------------|
| Dashboard port | `CORRAL_PORT` env var or `--port` | `8420` | Web dashboard port |
| Dashboard host | `--host` flag | `0.0.0.0` | Bind address |
| Default renderer | Settings modal | `xterm` (Claude), `blocks` (Gemini) | Terminal rendering mode per agent type |
| Default agent type | Settings modal | `claude` | Default for new sessions |
| Default working directory | Settings modal | Corral root | Pre-filled path in launch modal |
| Fit pane width | Settings modal | off | Auto-resize tmux pane to match browser width |
| Custom macros | Toolbar **+** button | `/compact`, `/clear`, `Reset` | Configurable command buttons |
| Log directory | `TMPDIR` env var | `/tmp` | Agent log file location |

**Database location:** `~/.corral/sessions.db` (SQLite, WAL mode)
