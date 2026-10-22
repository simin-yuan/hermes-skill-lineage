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
REPAIR_KIND = "repair"


class TornTail(Exception):
    """The last line(s) do not parse. Carries the last entry that did.

    A torn line is what a crash mid-write, a truncated copy or a plain text
    editor leaves behind. The reader already skipped it; the writer used to
    give up on the whole write and keep doing so on every later write, with
    nothing in ``status`` to say so.
    """

    def __init__(self, seq: int, digest: str, lines: list[bytes]) -> None:
        super().__init__(f"{len(lines)} torn trailing line(s) after seq {seq}")
        self.seq = seq
        self.hash = digest
        self.lines = lines


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_hash(entry: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k != "hash"})).hexdigest()


def _scan_tail(path: Path) -> tuple[int, str, list[bytes]]:
    """(seq, hash, torn trailing lines) of the last entry that parses.

    Reading stops at the first parseable line from the end, so a non-empty torn
    list means the tail itself is damaged — the case the writer must survive.
    """
    if not path.exists():
        return 0, GENESIS, []
    try:
        data = path.read_bytes()
    except OSError:
        return 0, GENESIS, []
    lines = [line for line in data.split(b"\n") if line.strip()]
    torn: list[bytes] = []
    for raw in reversed(lines):
        try:
            entry = json.loads(raw.decode("utf-8"))
            return int(entry["seq"]), str(entry["hash"]), torn
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            torn.append(raw)
    return 0, GENESIS, torn


def head(path: Path) -> tuple[int, str]:
    """(seq, hash) of the last entry, or (0, GENESIS) for an empty chain.

    Raises ``TornTail`` when the trailing line does not parse, so callers that
    only print a head can say so instead of reporting a stale one as current.
    """
    seq, digest, torn = _scan_tail(path)
    if torn:
        raise TornTail(seq, digest, torn)
    return seq, digest


def _ends_with_newline(path: Path) -> bool:
    """True for a missing or empty file: nothing to separate the next line from."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                return True
            handle.seek(-1, 2)
            return handle.read(1) == b"\n"
    except OSError:
        return True


def append(path: Path, bodies: list[dict], ts: str) -> list[dict]:
    """Append entries after the current head. The caller holds the chain lock.

    A torn trailing line does not stop the write. The damaged line is left in
    place — ``verify`` must still be able to point at it — and a ``repair``
    entry records how much was skipped and where the chain resumed, so the
    damage stays visible in ``status`` instead of turning into silence.
    """
    torn: list[bytes] = []
    try:
        seq, prev = head(path)
    except TornTail as exc:
        seq, prev, torn = exc.seq, exc.hash, exc.lines
    if torn:
        skipped = b"\n".join(torn)
        bodies = [{
            "kind": REPAIR_KIND,
            "reason": "torn trailing line did not parse as JSON; write resumed after the last entry that did",
            "skipped_lines": len(torn),
            "skipped_bytes": len(skipped),
            "skipped_sha256": hashlib.sha256(skipped).hexdigest(),
            "resumed_from_seq": seq,
        }] + list(bodies)
    written = []
    for body in bodies:
        seq += 1
        entry = dict(body)
        entry.update(seq=seq, ts=ts, prev=prev)
        entry["hash"] = entry_hash(entry)
        prev = entry["hash"]
        written.append(entry)
    with open(path, "ab") as handle:
        if not _ends_with_newline(path):
            # The torn line has no terminator; without this the repair entry
            # would be glued onto it and be unreadable too.
            handle.write(b"\n")
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
