"""Trusted runtime bootstrap executed before the generated analysis script.

The seccomp profile intentionally blocks process/thread creation. Matplotlib's
first-run font discovery normally starts a timer thread, so the image contains a
prebuilt cache that is copied into the writable per-run tmpfs before imports.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


_CACHE_SOURCE = Path("/opt/matplotlib-cache")
_CACHE_TARGET = Path(os.environ.get("MPLCONFIGDIR", "/tmp/matplotlib"))
_ANALYSIS_SCRIPT = "/work/analysis.py"


def _seed_matplotlib_cache() -> None:
    _CACHE_TARGET.mkdir(mode=0o700, parents=True, exist_ok=True)
    for source in _CACHE_SOURCE.glob("fontlist-v*.json"):
        target = _CACHE_TARGET / source.name
        if not target.exists():
            target.write_bytes(source.read_bytes())


def main() -> None:
    _seed_matplotlib_cache()
    os.execv(sys.executable, [sys.executable, _ANALYSIS_SCRIPT])


if __name__ == "__main__":
    main()
