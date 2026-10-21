"""Lineage graph built from the chain: who came from what."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from . import store

DEFAULT_KINDS = frozenset({"strong", "anchor", "prev", "read-strong", "read-anchor", "merge"})
WEAK_KINDS = frozenset({"context", "read-context"})


@dataclass
class Graph:
    parents: dict[str, list[tuple[str, dict]]] = field(default_factory=lambda: defaultdict(list))
    children: dict[str, list[tuple[str, dict]]] = field(default_factory=lambda: defaultdict(list))
    versions: dict[str, dict] = field(default_factory=dict)        # node -> version entry
    latest: dict[str, str] = field(default_factory=dict)           # skill name -> newest live node
    sources: dict[str, dict] = field(default_factory=dict)         # node -> source entry
    by_url: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))      # fetched the URL
    by_mention: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # only mention it


def version_node(skill: str, fingerprint: str) -> str:
    return f"skill:{skill}@{fingerprint}"


def load(chain_path: Path) -> Graph:
    graph = Graph()
    for entry in store.read_rows(chain_path):
        kind = entry.get("kind")
        if kind == "source":
            graph.sources[entry["node"]] = entry
            for url in entry.get("urls") or []:
                graph.by_url[url].add(entry["node"])
            for url in entry.get("mentions") or []:
                graph.by_mention[url].add(entry["node"])
        elif kind == "version":
            skill, after = entry.get("skill"), entry.get("after")
            if not after:
                graph.latest.pop(skill, None)
                continue
            node = version_node(skill, after)
            graph.versions[node] = entry
            graph.latest[skill] = node
            for edge in entry.get("edges") or []:
                graph.parents[node].append((edge["from"], edge))
                graph.children[edge["from"]].append((node, edge))
    return graph


def walk(graph: Graph, start: set[str], forward: bool, kinds: frozenset[str]) -> dict[str, tuple[str, dict]]:
    """Reachable nodes -> (the node they were reached from, the edge used)."""
    links = graph.children if forward else graph.parents
    reached: dict[str, tuple[str, dict]] = {}
    queue = deque(start)
    seen = set(start)
    while queue:
        node = queue.popleft()
        for other, edge in links.get(node, []):
            if edge.get("k") not in kinds or other in seen:
                continue
            seen.add(other)
            reached[other] = (node, edge)
            queue.append(other)
    return reached


def start_nodes(graph: Graph, target: str, url_hash: str | None, mentions: bool = False) -> set[str]:
    """A node id, every version of a skill name, or the sources that fetched a URL — plus, with
    ``mentions``, sources whose text merely names it (a user message listing several pages)."""
    if target in graph.sources or target in graph.versions:
        return {target}
    if url_hash is not None:
        found = set(graph.by_url.get(url_hash, ()))
        if mentions:
            found |= graph.by_mention.get(url_hash, set())
        if found:
            return found
    return {node for node, entry in graph.versions.items() if entry.get("skill") == target}
