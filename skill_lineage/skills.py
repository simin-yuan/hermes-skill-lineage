"""Where a skill lives, its fingerprint, and its text.

Skills are found by scanning ``$HERMES_HOME/skills``; nothing private from the Hermes
package is imported, so a release bump cannot break the lookup (catalog rule 9).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Optional

JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}
MAX_TEXT_BYTES = 2 * 1024 * 1024  # per file read for comparison; larger files are fingerprinted only


def _plain_locate(name: str) -> Optional[Path]:
    home = os.environ.get("HERMES_HOME")
    if not home:
        return None
    root = Path(home) / "skills"
    if not root.exists():
        return None
    for skill_md in root.rglob("SKILL.md"):
        if ".archive" in skill_md.parts or ".hub" in skill_md.parts:
            continue
        if skill_md.parent.name == name:
            return skill_md.parent
    return None


def locate(name: str) -> Optional[Path]:
    """Live directory of skill ``name`` or None (missing, archived, ambiguous)."""
    if not name:
        return None
    return _plain_locate(name)


Locator = Callable[[str], Optional[Path]]


def _files(skill_dir: Path) -> list[Path]:
    out = []
    for path in skill_dir.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.name not in JUNK \
                and not any(part.startswith(".") for part in path.relative_to(skill_dir).parts[:-1]):
            out.append(path)
    return sorted(out, key=lambda p: p.relative_to(skill_dir).as_posix())


def fingerprint(skill_dir: Optional[Path]) -> Optional[str]:
    """sha256 of canonical [[relative path, sha256(bytes)], ...]; None when the skill is missing."""
    if skill_dir is None or not skill_dir.exists():
        return None
    listing = [[p.relative_to(skill_dir).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()]
               for p in _files(skill_dir)]
    return hashlib.sha256(json.dumps(listing, separators=(",", ":")).encode("utf-8")).hexdigest()


def texts(skill_dir: Optional[Path]) -> dict[str, str]:
    """relative path -> decoded text for every UTF-8 file up to MAX_TEXT_BYTES."""
    if skill_dir is None or not skill_dir.exists():
        return {}
    out = {}
    for path in _files(skill_dir):
        try:
            if path.stat().st_size > MAX_TEXT_BYTES:
                continue
            out[path.relative_to(skill_dir).as_posix()] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return out


def snapshot(name: str, locator: Locator = locate) -> tuple[Optional[str], dict[str, str]]:
    skill_dir = locator(name)
    return fingerprint(skill_dir), texts(skill_dir)


def added_text(before: dict[str, str], after: dict[str, str]) -> str:
    """Lines present after the write and not before (per file, with multiplicity), in file order."""
    from collections import Counter

    chunks = []
    for rel, text in sorted(after.items()):
        old = Counter(before.get(rel, "").splitlines())
        for line in text.splitlines():
            if old[line] > 0:
                old[line] -= 1
            else:
                chunks.append(line)
    return "\n".join(chunks)
