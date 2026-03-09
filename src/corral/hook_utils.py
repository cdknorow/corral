"""Shared utilities for Corral hooks (lightweight, no heavy imports)."""

import os
import re
import subprocess

_TMUX_UUID_RE = re.compile(
    r"^[a-z]+-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", re.I
)


def resolve_session_id(payload_session_id: str | None) -> str | None:
    """Get the session_id from the tmux session name, falling back to the payload.

    Corral launches Claude with --session-id matching the tmux session UUID,
    but Claude's hook payload may report a different internal session_id.
    The tmux session name is the source of truth for Corral.
    """
    if os.environ.get("TMUX"):
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                name = result.stdout.strip()
                m = _TMUX_UUID_RE.match(name)
                if m:
                    return m.group(1).lower()
        except Exception:
            pass
    return payload_session_id
