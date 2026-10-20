import os
import time

from skill_lineage import sessions, skills
from skill_lineage.sessions import Seen


def test_record_and_load_roundtrip(tmp_path):
    s = Seen(kind="src", node="src:ext:aa", cls="ext", shingles={b"12345678", b"abcdefgh"}, anchors={"x"}, urls={"u"})
    sessions.record(tmp_path, "sess-1", s)
    sessions.record(tmp_path, "sess-1", s)  # same node twice -> one entry
    got = sessions.load(tmp_path, "sess-1")
    assert len(got) == 1 and got[0].shingles == s.shingles and got[0].anchors == {"x"}
    assert sessions.load(tmp_path, "other") == []


def test_prune_by_age_and_cap(tmp_path):
    for i in range(4):
        sessions.record(tmp_path, f"s{i}", Seen(kind="src", node=f"n{i}", cls="ext", shingles={os.urandom(8) for _ in range(500)}))
    files = sorted((tmp_path / "sessions").glob("*.jsonl"))
    old = time.time() - 10 * 86400
    os.utime(files[0], (old, old))
    assert sessions.prune(tmp_path, retention_days=7, cap_bytes=10**9) == 1
    size = sum(f.stat().st_size for f in (tmp_path / "sessions").glob("*.jsonl"))
    assert sessions.prune(tmp_path, retention_days=7, cap_bytes=size // 2) >= 1


def test_fingerprint_nested_and_missing(tmp_path):
    d = tmp_path / "sk"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text("a\n")
    fp1 = skills.fingerprint(d)
    (d / "references" / "x.md").write_text("b\n")
    fp2 = skills.fingerprint(d)
    assert fp1 != fp2 and len(fp2) == 64
    (d / ".DS_Store").write_text("junk")
    assert skills.fingerprint(d) == fp2
    assert skills.fingerprint(tmp_path / "nope") is None


def test_crlf_changes_fingerprint(tmp_path):
    d = tmp_path / "sk"
    d.mkdir()
    (d / "SKILL.md").write_bytes(b"a\nb\n")
    fp = skills.fingerprint(d)
    (d / "SKILL.md").write_bytes(b"a\r\nb\r\n")
    assert skills.fingerprint(d) != fp


def test_added_text_is_new_lines_only():
    before = {"SKILL.md": "# x\n- one\n- two\n"}
    after = {"SKILL.md": "# x\n- one\n- three\n- two\n", "references/r.md": "new file\n"}
    added = skills.added_text(before, after).splitlines()
    assert sorted(added) == ["- three", "new file"]
