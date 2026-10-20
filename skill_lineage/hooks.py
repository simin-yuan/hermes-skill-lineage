"""Hermes hooks. Observe only: every hook returns None, never raises into Hermes.

pre_llm_call   — the user's message becomes a ``user`` source of this session
post_tool_call — a tool result becomes a source (ext / local / agent); ``skill_view`` becomes a read;
                 ``skill_manage`` writes become chain entries with their edges
pre_tool_call  — ``skill_manage`` only: snapshot the skills it names before they change
on_session_start — expire old session files
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from . import chain, edges, sessions, skills, store, textfeat

logger = logging.getLogger(__name__)

NON_USER_PLATFORMS = frozenset({"curator", "subagent", "cron"})
NOT_SOURCES = frozenset({
    "memory", "skill_manage", "skills_list", "todo", "todo_list", "clarify", "set_theme", "show_tip", "gui_tour",
    "focus_pane", "setup_beat", "react_to_message", "text_to_speech", "image_generate", "video_generate",
    "close_terminal", "annotate_preview", "desktop_preview", "drive_preview", "write_file", "patch",
    "tool_search", "tool_describe",  # the Tool Search bridge's own catalog text, not content
})
LOCAL_TOOLS = frozenset({"terminal", "read_terminal", "execute_code", "process", "read_file", "search_files",
                         "session_search", "read_window_below"})
AGENT_TOOLS = frozenset({"delegate_task"})
READ_TOOL = "skill_view"
WRITE_TOOL = "skill_manage"
MAX_SOURCE_CHARS = 2_000_000  # a result longer than this is cut here (stated limit)


def classify(tool_name: str) -> Optional[str]:
    if tool_name in NOT_SOURCES or tool_name == READ_TOOL:
        return None
    if tool_name in LOCAL_TOOLS:
        return "local"
    if tool_name in AGENT_TOOLS:
        return "agent"
    return "ext"  # web, browser, MCP and every tool this list does not know


def short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else ""


def skill_names(args: Any) -> list[str]:
    """Skill names a skill_manage call touches (operations list, JSON string, or the flat legacy shape)."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return []
    if not isinstance(args, dict):
        return []
    ops = args.get("operations")
    if isinstance(ops, str):
        try:
            ops = json.loads(ops)
        except json.JSONDecodeError:
            ops = None
    if not isinstance(ops, list):
        ops = [args]
    names: list[str] = []
    for op in ops:
        if isinstance(op, dict):
            for field in ("name", "new_name"):
                value = op.get(field)
                if isinstance(value, str) and value and value not in names:
                    names.append(value)
    return names


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _result_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


class Tracker:
    def __init__(self, directory: Callable[[], Path] = store.data_dir, locator: skills.Locator = skills.locate):
        self._directory = directory
        self._locate = locator
        self._pending: dict[tuple[str, str], dict[str, tuple[Optional[str], dict[str, str]]]] = {}
        self._pending_guard = threading.Lock()

    # --- hooks -----------------------------------------------------------------------------

    def on_session_start(self, **_: Any) -> None:
        try:
            directory = self._directory()
            removed = sessions.prune(directory)
            if removed:
                self._append(directory, [{"kind": "prune", "session_files": removed}])
        except Exception:
            logger.warning("skill-lineage: prune failed (ignored)", exc_info=True)
        return None

    def pre_llm_call(self, session_id: str = "", user_message: Any = None, platform: str = "", **_: Any) -> None:
        try:
            if (platform or "") in NON_USER_PLATFORMS or not session_id:
                return None
            text = "\n".join(_strings(user_message)).strip()
            if text:
                self._record_source(str(session_id), "user", "", text, set())
        except Exception:
            logger.warning("skill-lineage: user turn not recorded (ignored)", exc_info=True)
        return None

    def pre_tool_call(self, tool_name: str = "", args: Any = None, session_id: str = "",
                      tool_call_id: str = "", **_: Any) -> None:
        if tool_name != WRITE_TOOL:
            return None
        try:
            snap = {name: skills.snapshot(name, self._locate) for name in skill_names(args)}
            with self._pending_guard:
                self._pending[(str(session_id), str(tool_call_id))] = snap
        except Exception:
            logger.warning("skill-lineage: pre-write snapshot failed (ignored)", exc_info=True)
        return None

    def post_tool_call(self, tool_name: str = "", args: Any = None, result: Any = None, session_id: str = "",
                       tool_call_id: str = "", **_: Any) -> None:
        session_id, call = str(session_id or ""), str(tool_call_id or "")
        try:
            if tool_name == WRITE_TOOL:
                with self._pending_guard:
                    before = self._pending.pop((session_id, call), {})
                self._record_writes(session_id, call, args, before)
            elif tool_name == READ_TOOL:
                self._record_read(session_id, args)
            elif session_id and (cls := classify(tool_name)) is not None and result is not None:
                urls = {s.strip() for s in _strings(args) if s.strip().lower().startswith(("http://", "https://"))}
                self._record_source(session_id, cls, tool_name, _result_text(result)[:MAX_SOURCE_CHARS], urls)
        except Exception:
            logger.warning("skill-lineage: %s not recorded (ignored)", tool_name, exc_info=True)
        return None

    # --- recording -------------------------------------------------------------------------

    def _record_source(self, session_id: str, cls: str, tool: str, text: str, urls: set[str]) -> None:
        directory = self._directory()
        key = store.install_key(directory)
        node = f"src:{cls}:{textfeat.keyed_hex(key, text, 16)}"
        strings = textfeat.anchor_strings(text)
        anchors = {textfeat.keyed_hex(key, s) for s in strings}
        url_hashes = {textfeat.keyed_hex(key, s) for s in strings if s.startswith("url:")}
        url_hashes |= {textfeat.url_hash(key, u) for u in urls}
        sessions.record(directory, session_id, sessions.Seen(
            kind="src", node=node, cls=cls, tool=tool, shingles=textfeat.shingles(key, text),
            anchors=anchors, urls=url_hashes))
        if cls in edges.CONTEXT_CLASSES:
            edges.AnchorCounts(directory).add_source(node, anchors)

    def _record_read(self, session_id: str, args: Any) -> None:
        if isinstance(args, str):
            args = json.loads(args)
        name = args.get("name") if isinstance(args, dict) else None
        if not session_id or not isinstance(name, str) or not name:
            return
        fp, texts = skills.snapshot(name, self._locate)
        if fp is None:
            return
        directory = self._directory()
        key = store.install_key(directory)
        body = "\n".join(texts[rel] for rel in sorted(texts))
        sessions.record(directory, session_id, sessions.Seen(
            kind="read", node=f"skill:{name}@{fp}", cls="skill", skill=name,
            shingles=textfeat.shingles(key, body), anchors=textfeat.anchors(key, body)))

    def _record_writes(self, session_id: str, call: str, args: Any,
                       before: dict[str, tuple[Optional[str], dict[str, str]]]) -> None:
        names = skill_names(args) or list(before)
        if not names:
            return
        directory = self._directory()
        key = store.install_key(directory)
        seen = sessions.load(directory, session_id) if session_id else []
        common = edges.AnchorCounts(directory).common()
        bodies: list[dict] = []
        for name in names:
            before_fp, before_texts = before.get(name, (None, {}))
            after_fp, after_texts = skills.snapshot(name, self._locate)
            if after_fp == before_fp:
                continue  # failed or no-op call: nothing changed on disk
            added = skills.added_text(before_texts, after_texts)
            before_all = "\n".join(before_texts[rel] for rel in sorted(before_texts))
            found, orphans = edges.compute(key, added, before_all,
                                           [s for s in seen if s.node != f"skill:{name}@{before_fp}"], common)
            edge_rows, dropped = edges.rows(found)
            if before_fp:
                edge_rows.insert(0, {"k": "prev", "from": f"skill:{name}@{before_fp}"})
            for item in seen:
                if item.kind == "src" and any(r["from"] == item.node for r in edge_rows):
                    bodies.append({"kind": "source", "node": item.node, "cls": item.cls, "tool": item.tool,
                                   "session": sessions.session_tag(session_id), "urls": sorted(item.urls)})
            version = {"kind": "version", "skill": name, "before": before_fp, "after": after_fp,
                       "session": sessions.session_tag(session_id), "call": short(call), "tool": WRITE_TOOL,
                       "edges": edge_rows, "orphans": orphans}
            if dropped:
                version["context_not_listed"] = dropped
            bodies.append(version)
        self._append(directory, bodies, dedupe_sources=True)

    def _append(self, directory: Path, bodies: list[dict], dedupe_sources: bool = False) -> None:
        if not bodies:
            return
        path = directory / chain.CHAIN_FILE
        index_path = directory / "nodes.idx"
        with store.locked(path):
            if dedupe_sources:
                known = set(index_path.read_text(encoding="utf-8").split()) if index_path.exists() else set()
                kept, new_nodes = [], []
                for body in bodies:
                    if body.get("kind") == "source":
                        if body["node"] in known or body["node"] in new_nodes:
                            continue
                        new_nodes.append(body["node"])
                    kept.append(body)
                bodies = kept
                if new_nodes:
                    with open(index_path, "a", encoding="utf-8") as handle:
                        handle.write("".join(n + "\n" for n in new_nodes))
            chain.append(path, bodies, store.iso())
