"""Local development object storage with atomic, traversal-safe writes."""

import os
from pathlib import Path, PurePosixPath
import tempfile


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never expose a partially written artifact to another request.  The
        # temporary file lives on the same filesystem so os.replace is atomic.
        handle, temporary_name = tempfile.mkstemp(prefix=".sandbox-object-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return key

    async def get_bytes(self, *, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    async def delete(self, *, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def _resolve(self, key: str) -> Path:
        # Object keys are canonical POSIX paths on every host. A backslash is
        # therefore never a separator we normalize: accepting it on Linux
        # would make the same key a traversal path when moved to Windows.
        if not key or "\\" in key or "\x00" in key:
            raise ValueError("Object storage key must use canonical POSIX separators")
        clean_key = PurePosixPath(key)
        if (
            clean_key.is_absolute()
            or ".." in clean_key.parts
            or not clean_key.parts
            or clean_key.as_posix() != key
        ):
            raise ValueError("Object storage key must be a relative, traversal-free path")
        raw_candidate = self._root / Path(*clean_key.parts)
        # Reject symlink aliases even when they ultimately resolve back inside
        # the root; object keys must have one stable canonical location.
        current = self._root
        for part in clean_key.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Object storage key contains a symlink")
        candidate = raw_candidate.resolve()
        if self._root not in candidate.parents and candidate != self._root:
            raise ValueError("Object storage key escapes configured root")
        return candidate
