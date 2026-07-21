from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from smart_home_sim.simulation.locking import (
    InterProcessFileLock,
    LockUnavailableError,
    WindowsByteRangeLockBackend,
)


class _FakeWindowsApi:
    LK_NBLCK = 1
    LK_UNLCK = 2

    def __init__(self, failure_errno: int | None = None) -> None:
        self.failure_errno = failure_errno
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, file_descriptor: int, mode: int, byte_count: int) -> None:
        position = os.lseek(file_descriptor, 0, os.SEEK_CUR)
        self.calls.append((mode, byte_count, position))
        if self.failure_errno is not None:
            raise OSError(self.failure_errno, "lock failed")


class _FakeBackend:
    name = "fake"

    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self, _handle) -> None:
        self.acquired += 1

    def release(self, _handle) -> None:
        self.released += 1


def test_windows_backend_locks_exactly_one_byte_from_offset_zero(tmp_path: Path) -> None:
    api = _FakeWindowsApi()
    backend = WindowsByteRangeLockBackend(api=api)
    with (tmp_path / "lock").open("w+b") as handle:
        handle.write(b"reserved")
        handle.seek(5)
        backend.acquire(handle)
        handle.seek(7)
        backend.release(handle)

    assert api.calls == [
        (api.LK_NBLCK, 1, 0),
        (api.LK_UNLCK, 1, 0),
    ]


def test_windows_backend_translates_contention_and_preserves_other_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lock"
    path.write_bytes(b"\0")
    with path.open("r+b") as handle:
        with pytest.raises(LockUnavailableError):
            WindowsByteRangeLockBackend(api=_FakeWindowsApi(failure_errno=errno.EACCES)).acquire(
                handle
            )
        with pytest.raises(OSError, match="lock failed") as unexpected:
            WindowsByteRangeLockBackend(api=_FakeWindowsApi(failure_errno=errno.EIO)).acquire(
                handle
            )
    assert unexpected.value.errno == errno.EIO


def test_interprocess_lock_reserves_lock_byte_and_releases_once(tmp_path: Path) -> None:
    backend = _FakeBackend()
    path = tmp_path / "nested" / "lock"
    lock = InterProcessFileLock(path, backend=backend)

    with pytest.raises(RuntimeError, match="must be acquired"):
        lock.write_metadata("pid=1\n")
    with lock:
        lock.write_metadata("pid=123\nbackend=fake\n")
        with pytest.raises(RuntimeError, match="already acquired"):
            lock.acquire()

    assert path.read_bytes() == b"#pid=123\nbackend=fake\n"
    assert backend.acquired == 1
    assert backend.released == 1
    lock.release()
    assert backend.released == 1
