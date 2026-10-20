import json
import subprocess
import sys
import threading
from pathlib import Path

from skill_lineage import chain


def write(path: Path, n: int) -> None:
    for i in range(n):
        chain.append(path, [{"kind": "note", "i": i}], "2026-10-21T00:00:00Z")


def lines(path):
    return path.read_bytes().split(b"\n")[:-1]


def test_intact_and_head(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 5)
    r = chain.verify(p)
    assert r.ok and r.entries == 5 and r.bad_seq is None
    seq, digest = chain.head(p)
    assert seq == 5 and len(digest) == 64 and digest == r.head_hash


def test_genesis_and_full_hashes(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 2)
    first, second = (json.loads(l) for l in lines(p))
    assert first["prev"] == "0" * 64 and second["prev"] == first["hash"]
    assert all(len(e["hash"]) == 64 for e in (first, second))


def _mutate(p, index, fn):
    rows = lines(p)
    rows[index] = fn(rows[index])
    p.write_bytes(b"\n".join(rows) + b"\n")


def test_edited_field_fails_at_that_seq(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 5)
    _mutate(p, 2, lambda l: l.replace(b'"i":2', b'"i":9'))
    r = chain.verify(p)
    assert not r.ok and r.bad_seq == 3 and "hash" in r.reason


def test_deleted_middle_line(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 5)
    rows = lines(p)
    del rows[1]
    p.write_bytes(b"\n".join(rows) + b"\n")
    r = chain.verify(p)
    assert r.bad_seq == 2 and "seq" in r.reason


def test_reordered_lines(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 4)
    rows = lines(p)
    rows[1], rows[2] = rows[2], rows[1]
    p.write_bytes(b"\n".join(rows) + b"\n")
    assert chain.verify(p).bad_seq == 2


def test_bad_json(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 3)
    _mutate(p, 1, lambda l: l[:-3])
    r = chain.verify(p)
    assert r.bad_seq == 2 and "JSON" in r.reason


def test_truncated_tail_needs_a_head(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 5)
    _, recorded = chain.head(p)
    p.write_bytes(b"\n".join(lines(p)[:3]) + b"\n")
    assert chain.verify(p).ok  # internally consistent ...
    r = chain.verify(p, recorded)  # ... but the head recorded elsewhere is gone
    assert not r.ok and "truncated" in r.reason


def test_head_found_counts_followers(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 3)
    _, h = chain.head(p)
    write(p, 2)
    r = chain.verify(p, h)
    assert r.ok and r.after_given_head == 2


def test_rewritten_whole_chain_passes_without_anchor(tmp_path):
    """Documented limit: a full rewrite is only caught against an external head."""
    p = tmp_path / "chain.jsonl"
    write(p, 3)
    _, h = chain.head(p)
    p.unlink()
    for i in range(3):
        chain.append(p, [{"kind": "note", "i": i + 100}], "2026-10-21T00:00:00Z")
    assert chain.verify(p).ok
    assert not chain.verify(p, h).ok


def test_parallel_appends_stay_valid(tmp_path):
    from skill_lineage import store
    p = tmp_path / "chain.jsonl"

    def worker(k):
        for i in range(20):
            with store.locked(p):
                chain.append(p, [{"kind": "note", "w": k, "i": i}], "2026-10-21T00:00:00Z")

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    r = chain.verify(p)
    assert r.ok and r.entries == 120


def test_standalone_verify_needs_no_hermes(tmp_path):
    p = tmp_path / "chain.jsonl"
    write(p, 3)
    repo = Path(__file__).resolve().parents[1]
    # Only the package folder is copied, Hermes imports are poisoned: the verifier must need neither.
    import shutil
    pkg = tmp_path / "alone"
    shutil.copytree(repo / "skill_lineage", pkg / "skill_lineage", ignore=shutil.ignore_patterns("__pycache__"))
    code = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
            "[sys.modules.__setitem__(m, None) for m in ('hermes_constants', 'plugins', 'tools', 'run_agent')]; "
            "from skill_lineage.verify import main; sys.exit(main(sys.argv[1:]))")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(pkg), str(p)], cwd=tmp_path,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "INTACT: 3 entries" in out.stdout
    _mutate(p, 0, lambda l: l.replace(b'"i":0', b'"i":7'))
    out = subprocess.run([sys.executable, "-I", "-c", code, str(pkg), str(p)], cwd=tmp_path,
                         capture_output=True, text=True)
    assert out.returncode == 1 and "BROKEN at seq 1" in out.stdout
