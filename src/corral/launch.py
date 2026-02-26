"""CLI entry point that executes the bundled launch_agents.sh script."""

import os
import sys
from pathlib import Path


def main():
    script = Path(__file__).parent / "launch_agents.sh"
    if not script.exists():
        print(f"Error: launch_agents.sh not found at {script}", file=sys.stderr)
        sys.exit(1)
    os.execvp("bash", ["bash", str(script)] + sys.argv[1:])
