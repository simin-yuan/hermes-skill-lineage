"""A torn last line must not stop the chain from recording new writes.

The reader already tolerated a truncated final line ("crash mid-write is
skipped"); the writer did not, and one torn line made every later skill write
vanish silently — the SKILL.md landed on disk, the chain stayed put, and
``status`` still looked healthy.

The fix keeps the evidence: the bad line stays where it is, ``verify`` still
reports the chain as broken at that seq, and a ``repair`` entry records what was
skipped and where the chain resumed. Losing the record is the failure; hiding
the damage would be the second one.
"""

import io
import json

from skill_lineage import chain, store
from skill_lineage.cli import cmd_status


def write(path, n, start=0):
    for i in range(start, start + n):
        chain.append(path, [{"kind": "note", "i": i}], "2026-10-22T00:00:00Z")


def tear(path, fragment=b'{"kind":"sou'):
    with open(path, "ab") as handle:
        handle.write(fragment)


def parseable(path):
    rows = []
    for raw in path.read_bytes().split(b"\n"):
        if not raw.strip():
            continue
        try:
            rows.append(json.loads(raw.decode("utf-8")))
        except ValueError:
            continue
    return rows


def test_write_continues_after_torn_line(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 1)
    tear(p)

    chain.append(p, [{"kind": "note", "i": 99}], "2026-10-22T00:00:01Z")

    rows = parseable(p)
    kinds = [r["kind"] for r in rows]
    assert "note" in kinds[1:] or kinds[-1] == "note", f"the write was dropped: {kinds}"


def test_repair_entry_records_what_was_skipped(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 1)
    tear(p, b'{"kind":"sou-broken-fragment')

    chain.append(p, [{"kind": "note", "i": 2}], "2026-10-22T00:00:02Z")

    repairs = [r for r in parseable(p) if r["kind"] == "repair"]
    assert len(repairs) == 1, "a torn tail should leave exactly one repair entry"
    repair = repairs[0]
    assert repair["resumed_from_seq"] == 1
    assert len(repair["skipped_sha256"]) == 64
    assert repair["skipped_bytes"] > 0


def test_new_seq_continues_from_last_good_entry(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 3)
    tear(p)

    chain.append(p, [{"kind": "note", "i": 3}], "2026-10-22T00:00:03Z")

    seqs = [r["seq"] for r in parseable(p)]
    assert seqs == sorted(seqs), f"seq went backwards: {seqs}"
    assert seqs[-1] == 5  # 3 good + repair + the new note


def test_verify_still_reports_the_damage(tmp_path):
    """Repairing the write path must not launder the tampering."""
    p = tmp_path / "chain.jsonl"
    write(p, 2)
    tear(p)
    chain.append(p, [{"kind": "note", "i": 9}], "2026-10-22T00:00:09Z")

    result = chain.verify(p)
    assert not result.ok
    assert result.bad_seq == 3


def test_second_torn_tail_also_recovers(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 1)
    tear(p)
    chain.append(p, [{"kind": "note", "i": 1}], "2026-10-22T00:00:01Z")
    tear(p, b'{"kind":"sou')  # a second tear, on the new tail
    chain.append(p, [{"kind": "note", "i": 2}], "2026-10-22T00:00:02Z")

    assert len([r for r in parseable(p) if r["kind"] == "repair"]) == 2


def test_status_says_the_chain_was_repaired(tmp_path, capsys):
    p = tmp_path / "chain.jsonl"
    write(p, 1)
    tear(p)
    chain.append(p, [{"kind": "note", "i": 1}], "2026-10-22T00:00:01Z")

    cmd_status(tmp_path)
    out = capsys.readouterr().out
    assert "repair" in out.lower(), f"status hid the repair:\n{out}"
    assert "WARNING" in out or "warning" in out


def test_clean_chain_writes_no_repair(tmp_path):
    """Control: the ordinary path must not grow repair entries."""
    p = tmp_path / "chain.jsonl"
    write(p, 3)
    assert not [r for r in parseable(p) if r["kind"] == "repair"]
    assert chain.verify(p).ok
