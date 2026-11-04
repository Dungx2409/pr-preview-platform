#!/usr/bin/env python3
"""Thin executable entrypoint for make doctor."""

import sys
from pathlib import Path

# Add repo root to sys.path to load scripts.preview_cli
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from scripts.preview_cli.doctor_cmd import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
