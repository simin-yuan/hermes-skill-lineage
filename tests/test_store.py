import argparse
import os

from skill_lineage import cli, sessions, store
from skill_lineage.hooks import Tracker


def test_key_is_stable_across_calls(tmp_path):
    first = store.install_key_ex(tmp_path)[0]
    assert all(store.install_key_ex(tmp_path)[0] == first for _ in range(50))
    raw = (tmp_path / store.KEY_FILE).read_bytes()
    assert raw == first.hex().encode("ascii") + b"\n"


def test_key_with_newline_bytes_survives(tmp_path, monkeypatch):
    """The Windows text-mode bug: raw 0x0A bytes became 0x0D 0x0A and the key silently changed."""
    monkeypatch.setattr(store.secrets, "token_bytes", lambda n: b"\n\r" * (n // 2))
    first = store.install_key_ex(tmp_path)[0]
    monkeypatch.undo()
    assert store.install_key_ex(tmp_path)[0] == first == b"\n\r" * 16


def test_crlf_written_key_file_still_reads(tmp_path):
    key = os.urandom(32)
    (tmp_path / store.KEY_FILE).write_bytes(key.hex().encode("ascii") + b"\r\n")
    assert store.install_key_ex(tmp_path) == (key, "")


def test_malformed_key_is_kept_and_reported(tmp_path):
    (tmp_path / store.KEY_FILE).write_bytes(os.urandom(33))  # what the old raw format became on Windows
    key, reason = store.install_key_ex(tmp_path)
    assert len(key) == 32 and reason.startswith("key file ")
    assert len(list(tmp_path.glob(store.KEY_FILE + ".bad-*"))) == 1
    assert store.install_key_ex(tmp_path) == (key, "")


def test_key_reset_is_recorded_in_chain_and_status(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    t = Tracker(directory=lambda: data, locator=lambda n: None)
    t.post_tool_call(tool_name="web_extract", result="x " * 50, session_id="S1", tool_call_id="1")
    assert list((data / sessions.SESSIONS_DIR).glob("*.jsonl"))
    (data / store.KEY_FILE).write_bytes(b"garbage")
    t.post_tool_call(tool_name="web_extract", result="y " * 50, session_id="S2", tool_call_id="2")
    rows = store.read_rows(data / "chain.jsonl")
    reset = [r for r in rows if r.get("kind") == "key_reset"]
    assert len(reset) == 1 and reset[0]["session_files_removed"] == 1
    cli.make_handler(lambda: data)(argparse.Namespace(skill_lineage_command="status"))
    assert "WARNING: hashing key was reset 1 time(s)" in capsys.readouterr().out


def test_cli_never_touches_the_key(tmp_path, capsys):
    """CLI commands only read: a malformed key is reported, not replaced (the reset belongs to the hooks,
    which record it in the chain)."""
    data = tmp_path / "data"
    data.mkdir()
    t = Tracker(directory=lambda: data, locator=lambda n: None)
    t.post_tool_call(tool_name="web_extract", result="x " * 50, args={"url": "https://a.example/p"},
                     session_id="S1", tool_call_id="1")
    bad = b"0" * 33
    (data / store.KEY_FILE).write_bytes(bad)
    handler = cli.make_handler(lambda: data)
    assert handler(argparse.Namespace(skill_lineage_command="descendants", target="https://a.example/p", weak=False)) == 1
    assert "hashing key malformed (33 bytes)" in capsys.readouterr().out
    assert handler(argparse.Namespace(skill_lineage_command="status")) == 0
    assert "WARNING: hashing key malformed" in capsys.readouterr().out
    for command in ("trace", "report", "verify", "head"):
        ns = argparse.Namespace(skill_lineage_command=command, skill="x", weak=False, head=None, json=False)
        handler(ns)
    capsys.readouterr()
    assert (data / store.KEY_FILE).read_bytes() == bad
    assert not list(data.glob(store.KEY_FILE + ".bad-*"))


def test_store_has_no_silent_key_api():
    assert not hasattr(store, "install_key")
