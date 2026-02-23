"""Agent manager — SDK-based agent lifecycle, replacing tmux pipe-pane."""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from claude_agent_sdk.types import StreamEvent

STATUS_RE = re.compile(r"\|\|STATUS:\s*(.+?)\|\|")
SUMMARY_RE = re.compile(r"\|\|SUMMARY:\s*(.+?)\|\|")

PROTOCOL_PATH = Path(__file__).parent / "PROTOCOL.md"


@dataclass
class AgentState:
    """In-memory state for a single agent."""

    name: str
    working_dir: str
    status: str = "Idle"
    summary: str = ""
    last_activity: float = field(default_factory=time.time)
    is_busy: bool = False
    session_id: str | None = None
    total_cost_usd: float = 0.0
    recent_messages: deque = field(default_factory=lambda: deque(maxlen=500))


class AgentHandle:
    """Wraps a ClaudeSDKClient + AgentState + background reader task."""

    def __init__(self, name: str, client: ClaudeSDKClient, state: AgentState):
        self.name = name
        self.client = client
        self.state = state
        self.reader_task: asyncio.Task | None = None


class AgentManager:
    """Central manager for SDK-based agent lifecycle and pub/sub."""

    def __init__(self):
        self._agents: dict[str, AgentHandle] = {}
        # Pub/sub: per-agent subscribers and fleet-wide subscribers
        self._agent_subs: dict[str, list[asyncio.Queue]] = {}
        self._fleet_subs: list[asyncio.Queue] = []

    # ── Launch / Stop ──────────────────────────────────────────────────────

    async def launch_agent(
        self,
        name: str,
        working_dir: str,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Launch a new agent with the SDK client."""
        if name in self._agents:
            return {"error": f"Agent '{name}' already exists"}

        working_dir_resolved = str(Path(working_dir).resolve())
        if not Path(working_dir_resolved).is_dir():
            return {"error": f"Directory not found: {working_dir}"}

        # Build system prompt from PROTOCOL.md + optional extra
        prompt_parts = []
        if PROTOCOL_PATH.exists():
            prompt_parts.append(PROTOCOL_PATH.read_text())
        if system_prompt:
            prompt_parts.append(system_prompt)
        full_system_prompt = "\n\n".join(prompt_parts) if prompt_parts else None

        options = ClaudeAgentOptions(
            system_prompt=full_system_prompt,
            permission_mode="acceptEdits",
            cwd=working_dir_resolved,
            include_partial_messages=True,
            model=model,
        )

        state = AgentState(name=name, working_dir=working_dir_resolved)
        client = ClaudeSDKClient(options=options)

        try:
            await client.connect()
        except Exception as e:
            return {"error": f"Failed to connect: {e}"}

        handle = AgentHandle(name=name, client=client, state=state)
        self._agents[name] = handle
        self._agent_subs.setdefault(name, [])

        # Start background reader
        handle.reader_task = asyncio.create_task(self._message_reader(name))

        self._broadcast_fleet_update()

        return {
            "ok": True,
            "name": name,
            "working_dir": working_dir_resolved,
        }

    async def send_command(self, name: str, command: str) -> dict[str, Any]:
        """Send a command/query to an agent."""
        handle = self._agents.get(name)
        if not handle:
            return {"error": f"Agent '{name}' not found"}

        try:
            handle.state.is_busy = True
            handle.state.last_activity = time.time()
            self._broadcast_fleet_update()
            await handle.client.query(command)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    async def interrupt_agent(self, name: str) -> dict[str, Any]:
        """Interrupt a running agent."""
        handle = self._agents.get(name)
        if not handle:
            return {"error": f"Agent '{name}' not found"}

        try:
            await handle.client.interrupt()
            handle.state.is_busy = False
            handle.state.status = "Interrupted"
            handle.state.last_activity = time.time()
            self._broadcast_fleet_update()
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    async def stop_agent(self, name: str) -> dict[str, Any]:
        """Stop and remove an agent."""
        handle = self._agents.pop(name, None)
        if not handle:
            return {"error": f"Agent '{name}' not found"}

        if handle.reader_task:
            handle.reader_task.cancel()
            try:
                await handle.reader_task
            except asyncio.CancelledError:
                pass

        try:
            await handle.client.disconnect()
        except Exception:
            pass

        # Clean up subscriptions
        for q in self._agent_subs.pop(name, []):
            await q.put(None)  # signal close

        self._broadcast_fleet_update()
        return {"ok": True}

    async def stop_all(self):
        """Stop all agents."""
        names = list(self._agents.keys())
        for name in names:
            await self.stop_agent(name)

    # ── Query ──────────────────────────────────────────────────────────────

    def list_agents_names(self) -> set[str]:
        """Return set of current agent names."""
        return set(self._agents.keys())

    def list_agents(self) -> list[dict[str, Any]]:
        """Return list of agent state dicts for fleet view."""
        results = []
        for handle in self._agents.values():
            s = handle.state
            results.append({
                "name": s.name,
                "working_dir": s.working_dir,
                "status": s.status,
                "summary": s.summary,
                "is_busy": s.is_busy,
                "session_id": s.session_id,
                "total_cost_usd": s.total_cost_usd,
                "last_activity": s.last_activity,
            })
        return results

    def get_agent_snapshot(self, name: str) -> dict[str, Any] | None:
        """Return state + recent_messages for initial WebSocket load."""
        handle = self._agents.get(name)
        if not handle:
            return None

        s = handle.state
        return {
            "name": s.name,
            "working_dir": s.working_dir,
            "status": s.status,
            "summary": s.summary,
            "is_busy": s.is_busy,
            "session_id": s.session_id,
            "total_cost_usd": s.total_cost_usd,
            "recent_messages": list(s.recent_messages),
        }

    # ── Pub/Sub ────────────────────────────────────────────────────────────

    def subscribe_agent(self, name: str) -> asyncio.Queue:
        """Subscribe to events for a specific agent. Returns a queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._agent_subs.setdefault(name, []).append(q)
        return q

    def unsubscribe_agent(self, name: str, q: asyncio.Queue):
        """Remove an agent subscription."""
        subs = self._agent_subs.get(name, [])
        if q in subs:
            subs.remove(q)

    def subscribe_fleet(self) -> asyncio.Queue:
        """Subscribe to fleet-wide updates. Returns a queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._fleet_subs.append(q)
        return q

    def unsubscribe_fleet(self, q: asyncio.Queue):
        """Remove a fleet subscription."""
        if q in self._fleet_subs:
            self._fleet_subs.remove(q)

    def _publish_agent_event(self, name: str, event: dict[str, Any]):
        """Push an event to all subscribers of a specific agent."""
        for q in self._agent_subs.get(name, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop if consumer is too slow

    def _broadcast_fleet_update(self):
        """Push current fleet state to all fleet subscribers."""
        state = self.list_agents()
        event = {"type": "fleet_update", "sessions": state}
        for q in self._fleet_subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # ── Message Reader ─────────────────────────────────────────────────────

    async def _message_reader(self, name: str):
        """Background task consuming client.receive_messages(), dispatching events."""
        handle = self._agents.get(name)
        if not handle:
            return

        try:
            async for message in handle.client.receive_messages():
                events = self._process_message(name, message)
                for event in events:
                    handle.state.recent_messages.append(event)
                    self._publish_agent_event(name, event)
                handle.state.last_activity = time.time()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error_event = {"type": "error", "text": f"Reader error: {e}"}
            handle.state.recent_messages.append(error_event)
            self._publish_agent_event(name, error_event)

    def _process_message(self, name: str, message: Any) -> list[dict[str, Any]]:
        """Convert SDK message types to WebSocket event dicts."""
        handle = self._agents.get(name)
        if not handle:
            return []

        state = handle.state
        events: list[dict[str, Any]] = []

        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                session_id = message.data.get("session_id")
                if session_id:
                    state.session_id = session_id
                events.append({
                    "type": "system",
                    "subtype": message.subtype,
                    "session_id": session_id,
                })

        elif isinstance(message, AssistantMessage):
            state.is_busy = True
            self._broadcast_fleet_update()

            for block in message.content:
                if isinstance(block, TextBlock):
                    text = block.text
                    events.append({"type": "text", "text": text})

                    # Parse ||STATUS:|| and ||SUMMARY:|| from text
                    for m in STATUS_RE.finditer(text):
                        status = " ".join(m.group(1).split())
                        state.status = status
                        events.append({"type": "status", "text": status})

                    for m in SUMMARY_RE.finditer(text):
                        summary = " ".join(m.group(1).split())
                        state.summary = summary
                        events.append({"type": "summary", "text": summary})

                elif isinstance(block, ToolUseBlock):
                    events.append({
                        "type": "tool_use",
                        "tool": block.name,
                        "tool_use_id": block.id,
                        "input": block.input,
                    })

                elif isinstance(block, ToolResultBlock):
                    content = block.content
                    if isinstance(content, list):
                        # Extract text from content blocks
                        content = "\n".join(
                            b.get("text", str(b))
                            for b in content
                            if isinstance(b, dict)
                        )
                    events.append({
                        "type": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": content or "",
                        "is_error": bool(block.is_error),
                    })

        elif isinstance(message, ResultMessage):
            state.is_busy = False
            if message.total_cost_usd is not None:
                state.total_cost_usd = message.total_cost_usd
            if message.session_id:
                state.session_id = message.session_id
            events.append({
                "type": "result",
                "total_cost_usd": message.total_cost_usd,
                "duration_ms": message.duration_ms,
                "num_turns": message.num_turns,
                "session_id": message.session_id,
                "is_error": message.is_error,
            })
            self._broadcast_fleet_update()

        elif isinstance(message, StreamEvent):
            events.append({
                "type": "stream",
                "event": message.event,
            })

        return events


# ── CLI Entry Point ────────────────────────────────────────────────────────


def launch_fleet_cli():
    """CLI entry point: scan a worktree directory and launch agents + web server."""
    import argparse
    import os
    import uvicorn

    parser = argparse.ArgumentParser(description="Launch Agent Fleet agents and web dashboard")
    parser.add_argument("worktree_dir", nargs="?", help="Directory containing git worktrees to launch agents in")
    parser.add_argument("--host", default="0.0.0.0", help="Web server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8420, help="Web server port (default: 8420)")
    parser.add_argument("--model", default=None, help="Model to use for agents")
    args = parser.parse_args()

    async def _launch_and_serve():
        from agent_fleet.web_server import app, agent_manager

        if args.worktree_dir:
            worktree_dir = os.path.abspath(args.worktree_dir)
            if not os.path.isdir(worktree_dir):
                print(f"Error: {worktree_dir} is not a directory")
                return

            # Scan for subdirectories (worktrees)
            for entry in sorted(os.listdir(worktree_dir)):
                full_path = os.path.join(worktree_dir, entry)
                if os.path.isdir(full_path) and not entry.startswith("."):
                    print(f"Launching agent: {entry} -> {full_path}")
                    result = await agent_manager.launch_agent(
                        name=entry,
                        working_dir=full_path,
                        model=args.model,
                    )
                    if result.get("error"):
                        print(f"  Error: {result['error']}")
                    else:
                        print(f"  OK")

        config = uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(_launch_and_serve())
