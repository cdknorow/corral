# Fighting AI Developer Fatigue: Building a Control Plane with FastAPI and tmux

The world is quickly filling up with autonomous AI coding agents, and managing their output effectively is a crucial skill for modern developers. This article provides a hands-on guide to solving "AI terminal fatigue" by building a robust control plane to orchestrate your agents. We’ll walk you through the architecture of Corral, an open-source tool that wraps agents like Claude Code and Gemini in parallel git worktrees. By the end of this article, you will understand how to use `tmux` and `FastAPI` to regain control of your AI workflow and stop feeling overwhelmed by terminal sprawl.

## Project Overview

When a human looks at a deer, they see a simple creature going about its life, completely unaware of the complex world building up around it. We tolerate the deer, and the deer grazes on, indifferent and oblivious to the vast gap in intelligence. Lately, sitting next to the hum of a datacenter and managing AI coding agents, it has started to feel eerily similar—except now, we are the deer. The AI operates at a speed and scale so vast that we are often left just watching the terminal scroll by, dimly grasping the sheer volume of thought happening in front of us.

Corral is an attempt to bridge that gap. In this article, we will:

*   Explain how to isolate AI agents using `tmux` and parallel git worktrees.
*   Build an asynchronous log-tailing system using Python.
*   Create a local web dashboard using `FastAPI` to monitor and control agents in real-time.
*   Implement full-text search across historical AI sessions using `SQLite` and FTS5.

## The Tools

To build a reliable control plane that doesn't interfere with the AI agents themselves, we rely on a specific stack:

*   **tmux:** A terminal multiplexer. It allows us to launch agents in detached sessions in the background. Crucially, we use `tmux pipe-pane` to silently stream the standard output of the agents to external log files without breaking the interactive terminal experience.
*   **FastAPI:** A modern, fast web framework for building APIs with Python 3.8+ based on standard Python type hints. We use it to serve the web dashboard and handle real-time WebSocket connections.
*   **aiosqlite:** A library that provides an asynchronous interface to SQLite databases. We use this, configured in WAL (Write-Ahead Logging) mode, to securely log agent activity, sync git states, and provide FTS5 (Full-Text Search) capabilities across thousands of lines of terminal output.
*   **Claude Code / Gemini CLI:** The actual coding agents we are orchestrating. 

## Step-by-Step Guide:

### 1. Isolating the Agents

The first step to regaining control is stopping the agents from stepping on your active workspace or each other. Corral achieves this by discovering your git repository and automatically creating a separate git worktree for each agent session.

Next, instead of running the agent directly in your current terminal, Corral wraps the launch command in a detached `tmux` session.

```bash
# Example of launching an agent in a detached tmux session
tmux new-session -d -s "claude-agent-1" -c "/path/to/worktree" "claude"
```

### 2. Capturing the Output Asynchronously

Once the agent is running in the background, we need a way to see what it is doing without manually attaching to the `tmux` session. We use `tmux pipe-pane` to pipe the output to a log file in the `/tmp/` directory.

```bash
# Pipe the pane output to a log file
tmux pipe-pane -t "claude-agent-1" "cat > /tmp/claude_corral_myproject.log"
```

In our Python backend, we then use asynchronous file readers (like `aiofiles`) to tail this log file. This allows our FastAPI server to read the AI's output in real-time without blocking the main event loop.

*(Press enter or click to view image in full size)*
*(Insert Image: Architecture diagram showing tmux -> log file -> FastAPI)*

### 3. The Pulse Protocol

Tailing the raw logs provides a complete picture, but it's often too noisy for a dashboard overview. We needed a way for the AI to explicitly communicate its high-level status (e.g., "Running tests" or "Modifying database schema"). 

To solve this, we inject a system prompt (or use tool hooks, like Claude Code's `settings.json`) that forces the agent to emit structured markdown tokens:

```text
||PULSE:STATUS Running the test suite||
```

Our FastAPI log tailer uses regular expressions to scan for these `||PULSE:STATUS||` tokens. When one is found, it immediately broadcasts the state change over a WebSocket to the UI dashboard.

### 4. Search and Summarization

All captured logs, statuses, and associated git commit information are saved to our local SQLite database. By enabling FTS5 (Full-Text Search), we can rapidly query past sessions to find highly specific code snippets or architectural decisions the AI made weeks ago.

## Conclusion

In this guide, we walked through the architecture of Corral, demonstrating how `tmux` and `FastAPI` can be combined to tame the chaos of parallel AI coding agents. By isolating agents in worktrees and asynchronously tracking their output, you are able to step back from the terminal screen and manage the workload from a higher-level dashboard. 

If you want to view the full source code or try out the tool yourself, you can install it via pip:

```bash
pip install agent-corral
```

The complete project is open source and available directly on GitHub here: [https://github.com/cdknorow/Corral](https://github.com/cdknorow/Corral).
