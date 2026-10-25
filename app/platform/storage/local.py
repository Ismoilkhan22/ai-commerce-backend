"""FileStorage — lokal disk adapteri (dev va testlar). Production'da S3-mos adapter (S0-10)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path


class LocalDiskStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        # Kalitni server yaratadi, lekin ochiq URL orqali ham keladi — ildizdan tashqariga chiqib bo'lmasin
        if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
            raise ValueError("invalid storage key")
        root = self.root.resolve()
        path = (root / key).resolve()
        if root not in path.parents:
            raise ValueError("invalid storage key")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(_write_atomic, self._path(key), data)

    async def get(self, key: str) -> bytes | None:
        try:
            path = self._path(key)
        except ValueError:
            return None
        return await asyncio.to_thread(_read, path)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(_unlink, self._path(key))


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Yarim yozilgan fayl hech qachon ko'rinmasin: vaqtinchalik fayl → rename
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
