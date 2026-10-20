"""The hash chain: one JSON object per line, each linked to the previous one by full sha256.

Standard library only, so ``python -m skill_lineage.verify chain.jsonl`` runs on a machine
without Hermes. ``hash`` = sha256 of the canonical JSON of the entry without ``hash``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

GENESIS = "0" * 64
CHAIN_FILE = "chain.jsonl"


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_hash(entry: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k != "hash"})).hexdigest()


def _last_line(path: Path) -> bytes:
    if not path.exists():
        return b""
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        block, data = 4096, b""
        while size > 0:
            step = min(block, size)
            size -= step
            handle.seek(size)
            data = handle.read(step) + data
            lines = [line for line in data.split(b"\n") if line.strip()]
            if len(lines) >= 2 or (lines and size == 0):
                return lines[-1]
        return b""


def head(path: Path) -> tuple[int, str]:
    """(seq, hash) of the last entry, or (0, GENESIS) for an empty chain."""
    line = _last_line(path)
    if not line:
        return 0, GENESIS
    entry = json.loads(line.decode("utf-8"))
    return int(entry["seq"]), str(entry["hash"])


def append(path: Path, bodies: list[dict], ts: str) -> list[dict]:
    """Append entries after the current head. The caller holds the chain lock."""
    seq, prev = head(path)
    written = []
    for body in bodies:
        seq += 1
        entry = dict(body)
        entry.update(seq=seq, ts=ts, prev=prev)
        entry["hash"] = entry_hash(entry)
        prev = entry["hash"]
        written.append(entry)
    with open(path, "ab") as handle:
        handle.write(b"".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                              for e in written))
    return written


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    head_seq: int
    head_hash: str
    bad_seq: int | None = None
    reason: str = ""
    after_given_head: int | None = None


def verify(path: Path, given_head: str | None = None) -> VerifyResult:
    """Every line parses, seq is contiguous from 1, prev links, hashes recompute; optional head check."""
    if not path.exists():
        return VerifyResult(False, 0, 0, GENESIS, None, "chain file not found")
    lines = [line for line in path.read_bytes().split(b"\n") if line.strip()]
    prev, seen = GENESIS, {}
    for index, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return VerifyResult(False, index - 1, index - 1, prev, index, "line does not parse as JSON")
        if not isinstance(entry, dict):
            return VerifyResult(False, index - 1, index - 1, prev, index, "line is not a JSON object")
        if entry.get("seq") != index:
            return VerifyResult(False, index - 1, index - 1, prev, index,
                                f"seq is {entry.get('seq')!r}, expected {index} (line missing, added or reordered)")
        if entry.get("prev") != prev:
            return VerifyResult(False, index - 1, index - 1, prev, index, "prev does not match the previous hash")
        if entry.get("hash") != entry_hash(entry):
            return VerifyResult(False, index - 1, index - 1, prev, index, "hash does not match the entry content")
        prev = entry["hash"]
        seen[prev] = index
    result = VerifyResult(True, len(lines), len(lines), prev)
    if given_head:
        if given_head not in seen:
            result.ok = False
            result.reason = "the given head hash is not in this chain (truncated or rewritten)"
        else:
            result.after_given_head = len(lines) - seen[given_head]
    return result
