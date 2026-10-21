"""``hermes skill-lineage trace | descendants | report | verify | head``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from . import chain, graph, store, textfeat
from .verify import report as verify_report

HELP = "Trace where a skill's content came from, or which skills a source produced; verify the chain"
DESCRIPTION = (
    "skill-lineage keeps a hash chain of skill versions and the sources each one drew on under "
    "<HERMES_HOME>/plugin-data/skill-lineage/. These commands only read it."
)


def setup(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="skill_lineage_command", metavar="{status,trace,descendants,report,verify,head}")
    sub.add_parser("status", help="Is anything being recorded? Version, data folder, newest entries")
    trace = sub.add_parser("trace", help="Where the newest version of a skill came from")
    trace.add_argument("skill")
    trace.add_argument("--weak", action="store_true", help="Also follow context edges (things the session only saw)")
    desc = sub.add_parser("descendants", help="Every skill version that came from a source, URL or skill")
    desc.add_argument("target", help="a source node id, a URL the agent read, or a skill name")
    desc.add_argument("--weak", action="store_true", help="Also follow context edges")
    desc.add_argument("--mentions", action="store_true",
                      help="For a URL, also start from sources that only mention it (e.g. a user message)")
    sub.add_parser("report", help="Skill versions with operative tokens of no traceable origin")
    verify = sub.add_parser("verify", help="Check the chain; --head checks it against a hash recorded elsewhere")
    verify.add_argument("--head", default=None)
    head = sub.add_parser("head", help="Print the newest entry's seq and hash (record it outside this machine)")
    head.add_argument("--json", action="store_true")


def make_handler(directory: Callable[[], Path] = store.data_dir) -> Callable[[argparse.Namespace], int]:
    def handle(args: argparse.Namespace) -> int:
        command = getattr(args, "skill_lineage_command", None)
        folder = directory()
        if command == "status":
            return cmd_status(folder)
        if command == "trace":
            return cmd_trace(folder, args.skill, args.weak)
        if command == "descendants":
            return cmd_descendants(folder, args.target, args.weak, getattr(args, "mentions", False))
        if command == "report":
            return cmd_report(folder)
        if command == "verify":
            return verify_report(chain.verify(folder / chain.CHAIN_FILE, args.head))
        if command == "head":
            return cmd_head(folder, args.json)
        print("usage: hermes skill-lineage {status,trace,descendants,report,verify,head} ...")
        return 2
    return handle


def _kinds(weak: bool) -> frozenset[str]:
    return graph.DEFAULT_KINDS | (graph.WEAK_KINDS if weak else frozenset())


def _label(g: graph.Graph, node: str) -> str:
    if node in g.sources:
        src = g.sources[node]
        return f"{node[:28]}…  [{src.get('cls')}{' via ' + src['tool'] if src.get('tool') else ''}]"
    if node in g.versions:
        v = g.versions[node]
        extra = f"  orphans={v['orphans']}" if v.get("orphans") else ""
        return f"skill {v['skill']} @{v['after'][:10]}  (seq {v.get('seq')}, {v.get('ts')}){extra}"
    return node[:40]


def _edge(edge: dict) -> str:
    parts = [edge.get("k", "?")]
    if edge.get("sh"):
        parts.append(f"{edge['sh']} shingles")
    if edge.get("an"):
        parts.append(f"{edge['an']} anchors")
    return ", ".join(parts)


def cmd_trace(folder: Path, skill: str, weak: bool) -> int:
    g = graph.load(folder / chain.CHAIN_FILE)
    node = g.latest.get(skill)
    if node is None:
        print(f"no recorded live version of skill {skill!r}")
        return 1
    print(_label(g, node))
    reached = graph.walk(g, {node}, forward=False, kinds=_kinds(weak))
    for other, (via, edge) in reached.items():
        print(f"  <- {_label(g, other)}   [{_edge(edge)}; into {_label(g, via)[:40]}]")
    if not reached:
        print("  (no recorded origin)")
    return 0


def cmd_descendants(folder: Path, target: str, weak: bool, mentions: bool = False) -> int:
    g = graph.load(folder / chain.CHAIN_FILE)
    url = None
    if target.lower().startswith(("http://", "https://")):
        key, why = store.read_key(folder)
        if key is None:
            print(f"cannot look up a URL: {why}. A URL is matched by its keyed hash; see "
                  "`hermes skill-lineage status`. Source node ids and skill names still work.")
            return 1
        url = textfeat.url_hash(key, target)
    start = graph.start_nodes(g, target, url, mentions)
    if not start:
        print(f"nothing recorded for {target!r}")
        return 1
    reached = graph.walk(g, start, forward=True, kinds=_kinds(weak))
    live = set(g.latest.values())
    for other, (via, edge) in reached.items():
        if other in g.versions:
            mark = "LIVE " if other in live else "     "
            print(f"{mark}{_label(g, other)}   [{_edge(edge)}]")
    if not any(o in g.versions for o in reached):
        print("no skill versions reached" + ("" if weak else " (try --weak)"))
    return 0


def cmd_report(folder: Path) -> int:
    g = graph.load(folder / chain.CHAIN_FILE)
    flagged = [v for v in g.versions.values() if v.get("orphans")]
    if not flagged:
        print("no skill versions with untraceable operative tokens")
        return 0
    for v in flagged:
        print(f"{v['skill']} @{v['after'][:10]}  seq {v.get('seq')}  {v['orphans']} operative token(s) with no "
              f"traceable origin (session saw external content) — try: hermes skill-lineage trace {v['skill']} --weak")
    return 0


def cmd_head(folder: Path, as_json: bool) -> int:
    seq, digest = chain.head(folder / chain.CHAIN_FILE)
    if as_json:
        print(json.dumps({"seq": seq, "hash": digest, "ts": store.iso()}))
    else:
        print(f"seq {seq} hash {digest}")
    return 0


def _manifest_field(name: str) -> str:
    manifest = Path(__file__).resolve().parents[1] / "plugin.yaml"
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + ":"):
                return line.split(":", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "?"


def cmd_status(folder: Path) -> int:
    """Answers "am I being recorded?". This command exists only when Hermes loaded the plugin, so reaching it
    means the requires_hermes gate passed; a missing command means the plugin was skipped (see plugins doctor)."""
    import time

    from . import sessions as sessions_mod

    print(f"skill-lineage {_manifest_field('version')} loaded (requires_hermes {_manifest_field('requires_hermes')} "
          "satisfied, or Hermes would not have loaded it)")
    print(f"data folder: {folder}")
    path = folder / chain.CHAIN_FILE
    rows = store.read_rows(path)
    if not rows:
        print("chain: empty — nothing recorded yet (a skill write through skill_manage creates the first entry)")
    else:
        last = rows[-1]
        versions = [r for r in rows if r.get("kind") == "version"]
        print(f"chain: {len(rows)} entries, head seq {last.get('seq')} at {last.get('ts')}; "
              f"{len(versions)} skill versions; last skill write {versions[-1]['ts'] if versions else 'none'}")
        resets = [r for r in rows if r.get("kind") == "key_reset"]
        if resets:
            print(f"WARNING: hashing key was reset {len(resets)} time(s), last at seq {resets[-1].get('seq')} "
                  f"({resets[-1].get('reason')}): sources seen before a reset cannot link to writes after it")
    key, why = store.read_key(folder)
    if key is None and (rows or (folder / store.KEY_FILE).exists()):
        print(f"WARNING: {why}. The next recorded event will make a new key and write a key_reset entry; "
              "lineage before it cannot connect to sources recorded after it")
    folder_s = folder / sessions_mod.SESSIONS_DIR
    files = sorted(folder_s.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if folder_s.exists() else []
    if files:
        age = time.time() - files[-1].stat().st_mtime
        print(f"sessions: {len(files)} files, newest source or read recorded {int(age // 60)} min ago")
    else:
        print("sessions: none — no user message or tool result recorded yet in this profile")
    return 0
