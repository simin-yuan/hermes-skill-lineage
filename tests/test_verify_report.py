"""Standalone verifier output: an empty chain must not be reported as intact.

``INTACT: 0 entries`` is the one line a person reads to conclude "the record is
fine". When a chain has been truncated to zero bytes — ``truncate -s 0``, a
shell redirect, an editor save, ``git checkout`` restoring an empty file — the
file looks exactly like a fresh install, and the verifier used to print
``INTACT: 0 entries, head seq 0 hash 000...`` and exit 0.

These tests pin the reporting rule: an empty chain is reported as empty, with
the ambiguity stated, and never as intact. A non-empty chain keeps its
``INTACT`` line, which is the control.
"""

import io
from pathlib import Path

import pytest

from skill_lineage import chain
from skill_lineage.verify import report


def write(path: Path, n: int) -> None:
    for i in range(n):
        chain.append(path, [{"kind": "note", "i": i}], "2026-10-22T00:00:00Z")


def out_of(result) -> str:
    buf = io.StringIO()
    report(result, buf)
    return buf.getvalue()


def test_zero_byte_chain_is_not_intact(tmp_path):
    p = tmp_path / "chain.jsonl"
    p.write_bytes(b"")

    result = chain.verify(p)
    text = out_of(result)

    assert result.ok and result.entries == 0
    assert "INTACT" not in text, f"an empty chain was reported as intact:\n{text}"
    assert "EMPTY" in text
    assert "truncated" in text.lower(), "the empty-vs-truncated ambiguity must be stated"


def test_chain_truncated_to_zero_after_writes_is_not_intact(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 2)
    assert chain.verify(p).entries == 2

    p.write_bytes(b"")  # truncate -s 0

    text = out_of(chain.verify(p))
    assert "INTACT" not in text, f"a truncated chain was reported as intact:\n{text}"
    assert "EMPTY" in text


def test_empty_chain_mentions_how_to_detect_truncation(tmp_path):
    p = tmp_path / "chain.jsonl"
    p.write_bytes(b"")

    text = out_of(chain.verify(p))
    assert "--head" in text, "should point at the one check that can tell them apart"


def test_non_empty_chain_still_reports_intact(tmp_path):
    """Control: the ordinary path keeps its wording."""
    p = tmp_path / "chain.jsonl"
    write(p, 3)

    result = chain.verify(p)
    text = out_of(result)

    assert result.ok
    assert "INTACT: 3 entries" in text
    assert "EMPTY" not in text


def test_internal_consistency_note_is_not_skipped_on_empty(tmp_path):
    """The note used to be gated on ``result.entries``, so the emptiest case lost it."""
    p = tmp_path / "chain.jsonl"
    p.write_bytes(b"")

    text = out_of(chain.verify(p))
    assert "consistency only" in text or "internal consistency" in text


def test_missing_file_is_still_broken(tmp_path):
    """A file that was never created is a different statement from an empty one."""
    result = chain.verify(tmp_path / "nope.jsonl")
    text = out_of(result)

    assert not result.ok
    assert "BROKEN" in text
    assert "not found" in text
