"""Short-lived per-session store of what the agent saw: sources and skill reads.

Full shingle sets are kept here (no sketch, no truncation) so overlaps are exact counts. These
files expire: after ``retention_days`` or when the folder passes ``cap_bytes`` (oldest first).
Lineage that was already computed lives in the chain and does not expire with them.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import store

SESSIONS_DIR = "sessions"
DEFAULT_RETENTION_DAYS = 7
DEFAULT_CAP_BYTES = 50 * 1024 * 1024


def session_tag(session_id: str) -> str:
    """12 hex of sha256(session_id): what the chain records instead of the id."""
    return hashlib.sha256((session_id or "").encode("utf-8")).hexdigest()[:12] if session_id else ""


def pack(values: set[bytes]) -> str:
    return base64.b64encode(b"".join(sorted(values))).decode("ascii")


def unpack(blob: str, size: int = 8) -> set[bytes]:
    raw = base64.b64decode(blob or "")
    return {raw[i:i + size] for i in range(0, len(raw), size)}


@dataclass
class Seen:
    """One thing the session saw: a source (user / ext / local / agent) or a skill read."""
    kind: str  # "src" or "read"
    node: str
    cls: str
    shingles: set[bytes] = field(default_factory=set)
    anchors: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)
    tool: str = ""
    skill: str = ""


def _file(directory: Path, session_id: str) -> Path:
    folder = directory / SESSIONS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24] + ".jsonl")


def record(directory: Path, session_id: str, seen: Seen) -> None:
    path = _file(directory, session_id)
    row = {"t": seen.kind, "node": seen.node, "cls": seen.cls, "tool": seen.tool, "skill": seen.skill,
           "sh": pack(seen.shingles), "an": sorted(seen.anchors), "url": sorted(seen.urls), "ts": store.iso()}
    with store.locked(path):
        store.append_rows(path, [row])


def load(directory: Path, session_id: str) -> list[Seen]:
    path = _file(directory, session_id)
    rows = store.read_rows(path)
    out: dict[str, Seen] = {}
    for row in rows:
        node = str(row.get("node") or "")
        if not node:
            continue
        out[node] = Seen(kind=str(row.get("t") or "src"), node=node, cls=str(row.get("cls") or ""),
                         shingles=unpack(str(row.get("sh") or "")), anchors=set(row.get("an") or []),
                         urls=set(row.get("url") or []), tool=str(row.get("tool") or ""),
                         skill=str(row.get("skill") or ""))
    return list(out.values())


def prune(directory: Path, retention_days: int = DEFAULT_RETENTION_DAYS,
          cap_bytes: int = DEFAULT_CAP_BYTES, now: float | None = None) -> int:
    """Delete expired session files, then the oldest until under the cap. Returns files removed."""
    folder = directory / SESSIONS_DIR
    if not folder.exists():
        return 0
    now = time.time() if now is None else now
    files = sorted((p for p in folder.glob("*.jsonl")), key=lambda p: p.stat().st_mtime)
    removed = 0
    keep = []
    for path in files:
        if retention_days > 0 and now - path.stat().st_mtime > retention_days * 86400:
            _remove(path)
            removed += 1
        else:
            keep.append(path)
    total = sum(p.stat().st_size for p in keep)
    for path in keep:
        if total <= cap_bytes:
            break
        total -= path.stat().st_size
        _remove(path)
        removed += 1
    return removed


def _remove(path: Path) -> None:
    for target in (path, path.with_name(path.name + ".lock")):
        try:
            os.remove(target)
        except OSError:  # gone already, or held open on Windows
            pass
