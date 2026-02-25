"""Background poller that queries git state for live fleet agents."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent_fleet.session_manager import discover_fleet_agents, _find_pane
from agent_fleet.session_store import SessionStore

log = logging.getLogger(__name__)


class GitPoller:
    """Periodically polls git branch/commit info for live agents and stores snapshots."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    async def run_forever(self, interval: float = 30) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                log.exception("GitPoller error")
            await asyncio.sleep(interval)

    async def poll_once(self) -> dict[str, int]:
        agents = await discover_fleet_agents()
        polled = 0
        for agent in agents:
            try:
                pane = await _find_pane(agent["agent_name"], agent["agent_type"])
                if not pane:
                    continue
                workdir = pane.get("current_path", "")
                if not workdir:
                    continue
                git_info = await self._query_git(workdir)
                if git_info:
                    session_id = await self._query_session_id(workdir)
                    await asyncio.to_thread(
                        self._store.upsert_git_snapshot,
                        agent["agent_name"],
                        agent["agent_type"],
                        workdir,
                        git_info["branch"],
                        git_info["commit_hash"],
                        git_info["commit_subject"],
                        git_info["commit_timestamp"],
                        session_id,
                        git_info.get("remote_url"),
                    )
                    polled += 1
            except Exception:
                log.exception("GitPoller error for agent %s", agent["agent_name"])
        return {"polled": polled}

    async def _query_session_id(self, workdir: str) -> str | None:
        """Find the active Claude session ID for a working directory.

        Claude stores session JSONL files under ~/.claude/projects/<encoded-path>/.
        The directory name is the absolute path with '/' replaced by '-'.
        The most recently modified .jsonl file is the active session.
        """
        try:
            encoded = workdir.replace("/", "-")
            project_dir = Path.home() / ".claude" / "projects" / encoded
            if not project_dir.is_dir():
                return None
            jsonl_files = sorted(
                project_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if jsonl_files:
                return jsonl_files[0].stem
        except OSError:
            pass
        return None

    async def _query_git(self, workdir: str) -> dict[str, str] | None:
        """Query git for current branch and latest commit in a working directory."""
        try:
            # Get branch name
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", workdir, "rev-parse", "--abbrev-ref", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return None
            branch = stdout.decode().strip()

            # Get latest commit: hash|subject|timestamp
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", workdir, "log", "-1", "--format=%H|%s|%aI",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return None
            parts = stdout.decode().strip().split("|", 2)
            if len(parts) < 3:
                return None

            # Get remote URL (best-effort)
            remote_url = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "-C", workdir, "remote", "get-url", "origin",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    remote_url = stdout.decode().strip() or None
            except (asyncio.TimeoutError, OSError):
                pass

            return {
                "branch": branch,
                "commit_hash": parts[0],
                "commit_subject": parts[1],
                "commit_timestamp": parts[2],
                "remote_url": remote_url,
            }
        except (asyncio.TimeoutError, OSError, FileNotFoundError):
            return None
