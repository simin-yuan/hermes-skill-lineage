"""Edges from what a session saw to a new skill version, and the orphan signal.

strong  — >= STRONG_MIN shared 8-token shingles between the added text and the source (exact count)
anchor  — no strong overlap, but >= 1 shared operative token that is not common
context — the session saw it, nothing measurable links it (recorded, not followed by default)
Skill reads use the same tests and are labelled read-strong / read-anchor / read-context.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from . import store, textfeat
from .sessions import Seen

STRONG_MIN = 3
COMMON_MIN_SOURCES = 5        # an anchor seen in fewer distinct sources is never "common"
COMMON_FRACTION = 0.05        # ... and above 100 sources, the fraction takes over
CONTEXT_CLASSES = {"ext", "local", "agent"}
MAX_CONTEXT_EDGES = 50
ANCHOR_STATE = "anchor_counts.json"
MAX_TRACKED_SOURCES = 20000


def common_threshold(sources: int) -> int:
    return max(COMMON_MIN_SOURCES, math.ceil(COMMON_FRACTION * sources))


class AnchorCounts:
    """How many distinct recorded sources carried each anchor hash."""

    def __init__(self, directory: Path):
        self.path = directory / ANCHOR_STATE

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"sources": [], "counts": {}}

    def add_source(self, node: str, anchors: set[str]) -> None:
        with store.locked(self.path):
            data = self._load()
            sources = data.setdefault("sources", [])
            if node in sources:
                return
            sources.append(node)
            if len(sources) > MAX_TRACKED_SOURCES:
                del sources[: len(sources) - MAX_TRACKED_SOURCES]
            counts = data.setdefault("counts", {})
            for anchor in anchors:
                counts[anchor] = int(counts.get(anchor, 0)) + 1
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.path)

    def common(self) -> set[str]:
        data = self._load()
        threshold = common_threshold(len(data.get("sources", [])))
        return {a for a, n in data.get("counts", {}).items() if int(n) >= threshold}


@dataclass
class Edge:
    kind: str
    node: str
    shingles: int = 0
    anchors: int = 0

    def as_row(self) -> dict:
        row = {"k": self.kind, "from": self.node}
        if self.shingles:
            row["sh"] = self.shingles
        if self.anchors:
            row["an"] = self.anchors
        return row


def compute(key: bytes, added: str, before_all: str, seen: list[Seen], common: set[str]) -> tuple[list[Edge], int]:
    """Edges into the new version, and how many of its operative tokens have no traceable origin."""
    added_sh = textfeat.shingles(key, added)
    added_an = textfeat.anchors(key, added) - common
    edges: list[Edge] = []
    explained: set[str] = set(textfeat.anchors(key, before_all))
    saw_external = False
    for item in seen:
        prefix = "read-" if item.kind == "read" else ""
        if item.cls == "ext":
            saw_external = True
        if item.cls == "user":
            explained |= item.anchors
        sh = len(added_sh & item.shingles)
        an = len(added_an & item.anchors)
        if sh >= STRONG_MIN:
            edges.append(Edge(prefix + "strong", item.node, sh, an))
            explained |= item.anchors
        elif an >= 1:
            edges.append(Edge(prefix + "anchor", item.node, sh, an))
            explained |= item.anchors
        elif item.kind == "read" or item.cls in CONTEXT_CLASSES:
            edges.append(Edge(prefix + "context", item.node))
    orphans = len(added_an - explained) if saw_external else 0
    return edges, orphans


def rows(edges: list[Edge]) -> tuple[list[dict], int]:
    """Edge rows for the chain; context edges past MAX_CONTEXT_EDGES are counted, not listed."""
    out, dropped, context = [], 0, 0
    for edge in edges:
        if edge.kind.endswith("context"):
            context += 1
            if context > MAX_CONTEXT_EDGES:
                dropped += 1
                continue
        out.append(edge.as_row())
    return out, dropped
