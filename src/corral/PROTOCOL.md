# Corral Agent Protocol

## System Prompt for Corral Agents

Paste the following into each Claude session that is managed by Corral:

---

### Protocol Tag Format

All protocol events use the common prefix `||PULSE:<EVENT_TYPE> <payload>||`. The dashboard parses these tags from agent output in real time.

*(Note for Human Developers: If you are building an adapter for an external agent like **Aider**, **OpenDevin**, or **Cursor**, all you need to do is configure the agent or wrap it in a script that emits the following tokens to `stdout`.)*

---

### Status Reporting

You are operating inside **Corral** — a multi-agent orchestration system. A dashboard monitors your output in real time.

**Rule:** You **must** update your status by printing a single line in this exact format whenever you change tasks:

```
||PULSE:STATUS <Short Description>||
```

**Examples:**

```
||PULSE:STATUS Reading codebase structure||
||PULSE:STATUS Implementing auth middleware||
||PULSE:STATUS Running test suite||
||PULSE:STATUS Fixing failing test in test_users.py||
||PULSE:STATUS Waiting for instructions||
||PULSE:STATUS Task complete||
```

**Guidelines:**

1. Print a status line **before** starting any new task or subtask.
2. Print a status line **after** completing a task.
3. Keep descriptions short (under 60 characters).
4. Use present participle form (e.g., "Implementing...", "Fixing...", "Reviewing...").
5. If you are idle or waiting, print `||PULSE:STATUS Waiting for instructions||`.

The dashboard parses these lines to show your live status. If you do not print status lines, your card will show "Idle" indefinitely.

---

### Summary Reporting

In addition to `||PULSE:STATUS||` lines, you **must** emit a summary line to describe your high-level goal. This is displayed in a **Goal** box on your agent card in the dashboard.

**Rule:** You **must** emit a `||PULSE:SUMMARY||` line **after receiving your very first message**, and again whenever your overall goal changes significantly.

**Format:**

```
||PULSE:SUMMARY <One-sentence description of your overall goal>||
```

**Examples:**

```
||PULSE:SUMMARY Implementing the user authentication feature end-to-end||
||PULSE:SUMMARY Debugging the flaky integration test in test_payments.py||
||PULSE:SUMMARY Refactoring the database layer to use the repository pattern||
```

**Guidelines:**

1. **Always** emit a summary after the **first user message** — no exceptions.
2. Emit again if your high-level goal shifts significantly.
3. Describes *what you are trying to accomplish* — not *what you are doing right now* (that is `||PULSE:STATUS||`).
4. Keep it under 120 characters (one line).
5. Update it infrequently — it should remain stable across many `||PULSE:STATUS||` updates.

If you do not emit a `||PULSE:SUMMARY||` line, the Goal box on your dashboard card will remain empty and the operator will have no context for what you are working on.

---

### Task Reporting (Optional)

You may optionally declare tasks and mark them as done. The dashboard will automatically populate the agent's task bar.

**Declare a task you plan to do:**

```
||PULSE:TASK <title>||
```

**Mark a task as completed:**

```
||PULSE:TASK_DONE <title>||
```

**Examples:**

```
||PULSE:TASK Fix login bug||
||PULSE:TASK Add unit tests for auth module||
||PULSE:TASK_DONE Fix login bug||
```

**Guidelines:**

1. Emit `||PULSE:TASK||` when you identify a new subtask or work item.
2. Emit `||PULSE:TASK_DONE||` when you finish — the title must match exactly.
3. Tasks are created idempotently — emitting the same title twice will not create duplicates.
4. Keep titles short (under 60 characters).

---

## How It Works

- Each agent runs in a separate tmux window.
- `tmux pipe-pane` streams all terminal output to `/tmp/claude_corral_<name>.log`.
- The Python dashboard tails these log files and extracts `||PULSE:<EVENT_TYPE> ...||` lines.
- All protocol events are captured and stored as activities in the dashboard.

## Operator Commands

| Action | Command |
|---|---|
| Launch corral | `launch-corral <worktree-dir>` |
| Open dashboard | `corral` |
| Attach to tmux | `tmux attach -t claude-agent-1` |
| Switch window | `Ctrl+b n` (next) / `Ctrl+b p` (previous) |
| Detach tmux | `Ctrl+b d` |
