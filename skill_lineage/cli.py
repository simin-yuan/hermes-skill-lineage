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
    sub = parser.add_subparsers(dest="skill_lineage_command", metavar="{trace,descendants,report,verify,head}")
    trace = sub.add_parser("trace", help="Where the newest version of a skill came from")
    trace.add_argument("skill")
    trace.add_argument("--weak", action="store_true", help="Also follow context edges (things the session only saw)")
    desc = sub.add_parser("descendants", help="Every skill version that came from a source, URL or skill")
    desc.add_argument("target", help="a source node id, a URL the agent read, or a skill name")
    desc.add_argument("--weak", action="store_true", help="Also follow context edges")
    sub.add_parser("report", help="Skill versions with operative tokens of no traceable origin")
    verify = sub.add_parser("verify", help="Check the chain; --head checks it against a hash recorded elsewhere")
    verify.add_argument("--head", default=None)
    head = sub.add_parser("head", help="Print the newest entry's seq and hash (record it outside this machine)")
    head.add_argument("--json", action="store_true")


def make_handler(directory: Callable[[], Path] = store.data_dir) -> Callable[[argparse.Namespace], int]:
    def handle(args: argparse.Namespace) -> int:
        command = getattr(args, "skill_lineage_command", None)
        folder = directory()
        if command == "trace":
            return cmd_trace(folder, args.skill, args.weak)
        if command == "descendants":
            return cmd_descendants(folder, args.target, args.weak)
        if command == "report":
            return cmd_report(folder)
        if command == "verify":
            return verify_report(chain.verify(folder / chain.CHAIN_FILE, args.head))
        if command == "head":
            return cmd_head(folder, args.json)
        print("usage: hermes skill-lineage {trace,descendants,report,verify,head} ...")
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


def cmd_descendants(folder: Path, target: str, weak: bool) -> int:
    g = graph.load(folder / chain.CHAIN_FILE)
    url = None
    if target.lower().startswith(("http://", "https://")):
        url = textfeat.url_hash(store.install_key(folder), target)
    start = graph.start_nodes(g, target, url)
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
