"""Locked JSONL files, the per-install hashing key and the plugin data directory.

Standard library only. The lock is exclusive across threads and processes (fcntl on POSIX,
msvcrt on Windows) and is held for every read-modify-append.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

logger = logging.getLogger(__name__)

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

_KEY_HEX = re.compile(r"[0-9a-f]{64}")


def install_key_ex(directory: Path) -> tuple[bytes, str]:
    """(key, reset_reason). The key is 32 random bytes, stored as 64 hex characters (ASCII text, so no
    platform newline translation can change it), written atomically with mode 0600. ``reset_reason`` is
    "" normally; when an existing key file is unreadable it is kept as ``install.key.bad-<time>``, a new
    key is made and the reason is returned so the caller records the break in the chain."""
    path = directory / KEY_FILE
    with locked(path):
        reason = ""
        if path.exists():
            try:
                text = path.read_bytes().decode("ascii").strip()
            except (OSError, UnicodeDecodeError) as exc:
                text, reason = "", f"key file unreadable ({type(exc).__name__})"
            if _KEY_HEX.fullmatch(text):
                return bytes.fromhex(text), ""
            reason = reason or f"key file malformed ({path.stat().st_size} bytes)"
            kept = path.with_name(f"{KEY_FILE}.bad-{utc_now().strftime('%Y%m%dT%H%M%SZ')}")
            os.replace(path, kept)
            logger.warning("skill-lineage: %s; kept as %s, new key made — lineage before this point "
                           "cannot connect to sources recorded after it", reason, kept.name)
        data = secrets.token_bytes(32)
        tmp = path.with_name(KEY_FILE + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.write(fd, (data.hex() + "\n").encode("ascii"))
        finally:
            os.close(fd)
        os.replace(tmp, path)
        return data, reason


def install_key(directory: Path) -> bytes:
    return install_key_ex(directory)[0]
