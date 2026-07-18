#!/usr/bin/env python3
"""Codess CLI entrypoint; parser and dispatch live in ``codess.project``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from codess.project import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Prevent a second BrokenPipeError while Python flushes stdout during
        # shutdown after a downstream consumer such as ``head`` exits early.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)
