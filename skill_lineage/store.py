"""Locked JSONL files, the per-install hashing key and the plugin data directory.

Standard library only. The lock is exclusive across threads and processes (fcntl on POSIX,
msvcrt on Windows) and is held for every read-modify-append.
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

PLUGIN_NAME = "skill-lineage"
KEY_FILE = "install.key"
DATA_DIR_ENV = "SKILL_LINEAGE_DATA_DIR"  # tests and the standalone tools only


def data_dir() -> Path:
    """``<HERMES_HOME>/plugin-data/skill-lineage``, resolved on every call (profile-aware)."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir(PLUGIN_NAME)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    return (moment or utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


# --- locking -------------------------------------------------------------------------------

_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _thread_locks_guard:
        return _thread_locks.setdefault(key, threading.Lock())


LOCK_TIMEOUT_SECONDS = 30.0
LOCK_RETRY_SECONDS = 0.05
_CONTENTION_ERRNOS = frozenset({errno.EACCES, getattr(errno, "EDEADLOCK", 36), getattr(errno, "EDEADLK", 35),
                                errno.EAGAIN, getattr(errno, "EWOULDBLOCK", errno.EAGAIN)})


def lock_with_retry(try_lock: Callable[[], None], timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            try_lock()
            return
        except OSError as exc:
            if exc.errno not in _CONTENTION_ERRNOS:
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(f"lock still held after {timeout:.0f}s") from exc
            time.sleep(LOCK_RETRY_SECONDS)


if os.name == "nt":  # pragma: no cover - exercised on the Windows CI runners
    import msvcrt

    def _lock_fd(fd: int) -> None:
        def attempt() -> None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        lock_with_retry(attempt)

    def _unlock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_fd(fd: int) -> None:
        lock_with_retry(lambda: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB))

    def _unlock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold the exclusive lock for ``path`` (in-process and cross-process)."""
    lock_path = path.with_name(path.name + ".lock")
    with _thread_lock(path):
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock_fd(fd)
            try:
                yield
            finally:
                _unlock_fd(fd)
        finally:
            os.close(fd)


# --- JSONL ---------------------------------------------------------------------------------

def encode_row(row: dict) -> bytes:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def append_rows(path: Path, rows: list[dict]) -> None:
    """Append rows; caller holds the lock when ordering matters."""
    if not rows:
        return
    with open(path, "ab") as handle:
        handle.write(b"".join(encode_row(row) for row in rows))


def read_rows(path: Path) -> list[dict]:
    """Every parseable row; a torn last line (crash mid-write) is skipped."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_bytes().split(b"\n"):
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


# --- per-install key -----------------------------------------------------------------------

def install_key(directory: Path) -> bytes:
    """32 random bytes created on first use (mode 0600). Never written to the chain."""
    path = directory / KEY_FILE
    with locked(path):
        if path.exists():
            data = path.read_bytes()
            if len(data) == 32:
                return data
        data = secrets.token_bytes(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return data
