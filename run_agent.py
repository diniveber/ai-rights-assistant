"""PyInstaller entry point for agent.exe (same as `python -m agent.cli`)."""

import sys

from agent.cli import main

if __name__ == "__main__":
    sys.exit(main())
