"""Pytest fixtures and configuration."""

import sys
from pathlib import Path

# Ensure src/ is on path for codess package
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
