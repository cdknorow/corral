"""CLI entry point that executes the bundled launch_agents.sh script."""

import os
import shutil
import sys
from pathlib import Path


def main():
    if not shutil.which("tmux"):
        print("Error: tmux is not installed. Coral requires tmux for agent management.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Install tmux:", file=sys.stderr)
        print("  macOS:  brew install tmux", file=sys.stderr)
        print("  Ubuntu: sudo apt install tmux", file=sys.stderr)
        print("  Fedora: sudo dnf install tmux", file=sys.stderr)
        sys.exit(1)

    # Handle --data-dir before exec'ing into bash so subprocesses inherit it
    remaining_args = list(sys.argv[1:])
    if "--data-dir" in remaining_args:
        idx = remaining_args.index("--data-dir")
        if idx + 1 < len(remaining_args):
            data_dir = str(Path(remaining_args[idx + 1]).expanduser().resolve())
            os.environ["CORAL_DATA_DIR"] = data_dir
            # Remove --data-dir and its value from args passed to bash
            remaining_args.pop(idx)  # remove --data-dir
            remaining_args.pop(idx)  # remove the value

    from coral.tools.utils import get_package_dir
    script = get_package_dir() / "launch_agents.sh"
    if not script.exists():
        print(f"Error: launch_agents.sh not found at {script}", file=sys.stderr)
        sys.exit(1)
    os.execvp("bash", ["bash", str(script)] + remaining_args)
