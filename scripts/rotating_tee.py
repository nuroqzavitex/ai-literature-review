#!/usr/bin/env python3
"""Copy stdin to stdout and a size-capped log file without archives."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def rotate(path: Path) -> None:
    path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write stdin to stdout and a rotating log file")
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-bytes", type=int, default=500 * 1024 * 1024)
    args = parser.parse_args()
    if args.max_bytes < 1:
        raise SystemExit("--max-bytes must be positive")

    path = args.path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= args.max_bytes:
        rotate(path)

    size = path.stat().st_size if path.exists() else 0
    destination = path.open("ab", buffering=0)
    try:
        # Process newline-delimited container output incrementally so normal
        # worker logs are flushed promptly and never held in a large buffer.
        for chunk in iter(sys.stdin.buffer.readline, b""):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            offset = 0
            while offset < len(chunk):
                if size >= args.max_bytes:
                    destination.close()
                    rotate(path)
                    destination = path.open("ab", buffering=0)
                    size = 0
                writable = min(args.max_bytes - size, len(chunk) - offset)
                destination.write(chunk[offset : offset + writable])
                offset += writable
                size += writable
    finally:
        destination.close()


if __name__ == "__main__":
    main()
