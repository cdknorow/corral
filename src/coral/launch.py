"""CLI entry point that executes the bundled launch_agents.sh script."""

import os
import shutil
import sys


def main():
    if not shutil.which("tmux"):
        print("Error: tmux is not installed. Coral requires tmux for agent management.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Install tmux:", file=sys.stderr)
        print("  macOS:  brew install tmux", file=sys.stderr)
        print("  Ubuntu: sudo apt install tmux", file=sys.stderr)
        print("  Fedora: sudo dnf install tmux", file=sys.stderr)
        sys.exit(1)
    from coral.tools.utils import get_package_dir
    script = get_package_dir() / "launch_agents.sh"
    if not script.exists():
        print(f"Error: launch_agents.sh not found at {script}", file=sys.stderr)
        sys.exit(1)
    os.execvp("bash", ["bash", str(script)] + sys.argv[1:])
