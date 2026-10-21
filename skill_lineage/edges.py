"""Edges from what a session saw to a new skill version, and the orphan signal.

strong  — >= STRONG_MIN shared 8-token shingles between the added text and the source (exact count)
anchor  — no strong overlap, but >= 1 shared operative token that is not common
context — the session saw it, nothing measurable links it (recorded, not followed by default)
Skill reads use the same tests and are labelled read-strong / read-anchor / read-context.
"""

from __future__ import annotations

import json
import math
from array import array
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


SHINGLE_SKETCH = "shingle_counts.bin"
SKETCH_DEPTH, SKETCH_WIDTH = 4, 1 << 16  # 4 x 65,536 uint16 = 512 KiB, fixed size


class AnchorCounts:
    """How many distinct recorded sources carried each anchor hash (exact) and each shingle hash
    (count-min sketch: fixed size, can only over-count, so it can only make more shingles 'common' —
    a missed link, never an invented one)."""

    def __init__(self, directory: Path):
        self.path = directory / ANCHOR_STATE
        self.sketch_path = directory / SHINGLE_SKETCH

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"sources": [], "counts": {}}

    def _load_sketch(self) -> array:
        sketch = array("H")
        try:
            raw = self.sketch_path.read_bytes()
            if len(raw) == SKETCH_DEPTH * SKETCH_WIDTH * 2:
                sketch.frombytes(raw)
                return sketch
        except OSError:
            pass
        return array("H", bytes(SKETCH_DEPTH * SKETCH_WIDTH * 2))

    @staticmethod
    def _cells(shingle: bytes) -> list[int]:
        a = int.from_bytes(shingle[:4], "little")
        b = int.from_bytes(shingle[4:8], "little") | 1
        return [row * SKETCH_WIDTH + (a + row * b) % SKETCH_WIDTH for row in range(SKETCH_DEPTH)]

    def add_source(self, node: str, anchors: set[str], shingles: set[bytes] = frozenset()) -> None:
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
            if shingles:
                sketch = self._load_sketch()
                for shingle in shingles:
                    for cell in self._cells(shingle):
                        if sketch[cell] < 0xFFFF:
                            sketch[cell] += 1
                tmp = self.sketch_path.with_name(self.sketch_path.name + ".tmp")
                tmp.write_bytes(sketch.tobytes())
                tmp.replace(self.sketch_path)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.path)

    def common(self) -> set[str]:
        data = self._load()
        threshold = common_threshold(len(data.get("sources", [])))
        return {a for a, n in data.get("counts", {}).items() if int(n) >= threshold}

    def common_shingles(self, shingles: set[bytes]) -> set[bytes]:
        """Which of these shingles occurred in at least the common threshold of distinct sources."""
        if not shingles:
            return set()
        threshold = common_threshold(len(self._load().get("sources", [])))
        sketch = self._load_sketch()
        return {s for s in shingles if min(sketch[c] for c in self._cells(s)) >= threshold}


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


def compute(key: bytes, added: str, before_all: str, seen: list[Seen], common: set[str],
            common_shingles: set[bytes] = frozenset()) -> tuple[list[Edge], int]:
    """Edges into the new version, and how many of its operative tokens have no traceable origin.
    Shingles and anchors that are common across recorded sources (boilerplate) never make an edge."""
    added_sh = textfeat.shingles(key, added) - set(common_shingles)
    added_an = textfeat.anchors(key, added) - common
    edges: list[Edge] = []
    explained: set[str] = set(textfeat.anchors(key, before_all))
    saw_external = any(item.cls == "ext" for item in seen)
    # Discriminative overlap: text that two sources of the session both contain cannot tell which one
    # it came from, so between sources (pages, tool results, user messages) only overlap unique to one
    # source counts. Skill reads are not part of this: a skill read in the session may itself derive
    # from a page, and subtracting it would cut the page's own link.
    sources = [item for item in seen if item.kind != "read"]
    for item in seen:
        prefix = "read-" if item.kind == "read" else ""
        explained |= item.anchors  # a token found in anything the session saw has a traceable origin
        own_sh, own_an = item.shingles, item.anchors
        if item.kind != "read":
            others = [o for o in sources if o is not item]
            own_sh = own_sh - set().union(*(o.shingles for o in others)) if others else own_sh
            own_an = own_an - set().union(*(o.anchors for o in others)) if others else own_an
        sh = len(added_sh & own_sh)
        an = len(added_an & own_an)
        if sh >= STRONG_MIN:
            edges.append(Edge(prefix + "strong", item.node, sh, an))
        elif an >= 1:
            edges.append(Edge(prefix + "anchor", item.node, sh, an))
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
