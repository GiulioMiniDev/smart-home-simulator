from __future__ import annotations

import errno
import importlib
import os
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, Protocol, Self


class LockUnavailableError(OSError):
    """Raised when another process already owns a non-blocking file lock."""


class LockBackend(Protocol):
    name: str

    def acquire(self, handle: BinaryIO) -> None: ...

    def release(self, handle: BinaryIO) -> None: ...


def _translate_contention(error: OSError) -> LockUnavailableError | None:
    if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
        return LockUnavailableError(error.errno, error.strerror)
    return None


class PosixFlockBackend:
    name = "posix-flock"

    def __init__(self, api: ModuleType | None = None) -> None:
        self.api = api or importlib.import_module("fcntl")

    def acquire(self, handle: BinaryIO) -> None:
        try:
            self.api.flock(handle.fileno(), self.api.LOCK_EX | self.api.LOCK_NB)
        except OSError as error:
            translated = _translate_contention(error)
            if translated is not None:
                raise translated from error
            raise

    def release(self, handle: BinaryIO) -> None:
        self.api.flock(handle.fileno(), self.api.LOCK_UN)


class WindowsByteRangeLockBackend:
    name = "windows-msvcrt-byte-range"

    def __init__(self, api: ModuleType | None = None) -> None:
        self.api = api or importlib.import_module("msvcrt")

    def acquire(self, handle: BinaryIO) -> None:
        handle.seek(0)
        try:
            self.api.locking(handle.fileno(), self.api.LK_NBLCK, 1)
        except OSError as error:
            translated = _translate_contention(error)
            if translated is not None:
                raise translated from error
            raise

    def release(self, handle: BinaryIO) -> None:
        handle.seek(0)
        self.api.locking(handle.fileno(), self.api.LK_UNLCK, 1)


def platform_lock_backend() -> LockBackend:
    return WindowsByteRangeLockBackend() if os.name == "nt" else PosixFlockBackend()


class InterProcessFileLock:
    """One-owner, non-blocking lock backed by the host operating system."""

    _METADATA_OFFSET = 1

    def __init__(self, path: Path, backend: LockBackend | None = None) -> None:
        self.path = path
        self.backend = backend or platform_lock_backend()
        self.handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self.handle is not None:
            raise RuntimeError("the lock instance is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"#")
                handle.flush()
                os.fsync(handle.fileno())
            self.backend.acquire(handle)
        except Exception:
            handle.close()
            raise
        self.handle = handle

    def write_metadata(self, content: str) -> None:
        if self.handle is None:
            raise RuntimeError("the lock must be acquired before writing metadata")
        # Byte zero remains allocated and untouched while Windows locks it.
        self.handle.seek(self._METADATA_OFFSET)
        self.handle.truncate()
        self.handle.write(content.encode("utf-8"))
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def release(self) -> None:
        if self.handle is None:
            return
        handle = self.handle
        self.handle = None
        try:
            self.backend.release(handle)
        finally:
            handle.close()

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.release()
