"""Where a skill lives, its fingerprint, and its text.

Skills are found by scanning the directories Hermes keeps them in — the active
profile's ``skills`` dir, every ``profiles/*/skills``, a project's
``.hermes/skills`` and ``skills.external_dirs`` — and reading the ``name:``
field of each ``SKILL.md``. The one Hermes import is
``hermes_constants.get_hermes_home()``, which is on the public surface plugin
authors are told to use (rule 9); it is imported inside the function, at call
time, and an older Hermes without it falls back to ``HERMES_HOME``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Optional

JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}
MAX_TEXT_BYTES = 2 * 1024 * 1024  # per file read for comparison; larger files are fingerprinted only

# Directories that hold SKILL.md files we must never treat as the live one:
# archived skills, skill-hub downloads, vendored repos, and tooling noise.
SKIP_PARTS = {".archive", ".hub", "_nested_repos", "node_modules", ".git"}


def _hermes_base() -> Path:
    """The active profile's Hermes home, resolved on every call.

    ``HERMES_HOME`` names the *launch* profile. When one Hermes process serves several profiles, a
    write in another profile's session would be looked up in the wrong tree, so prefer
    ``hermes_constants.get_hermes_home()``, which honours the per-session profile override.
    ``hermes_constants`` is a documented public surface for plugins (catalog rule 9); the import is
    inside the function so both the value and the module are resolved at call time, and an older
    Hermes without it falls back to the environment.
    """
    try:
        from hermes_constants import get_hermes_home  # public surface (catalog rule 9)
    except ImportError:  # Hermes predating the helper: the launch profile is all we can see
        home = os.environ.get("HERMES_HOME")
        return Path(home) if home else Path.home() / ".hermes"
    return Path(get_hermes_home())


def _external_dirs(base: Path) -> list[Path]:
    """``skills.external_dirs`` read from config.yaml with a line scanner.

    PyYAML is not a declared dependency, and the block is a flat list of paths,
    so a scanner beats taking a dependency for it. Anything it cannot parse is
    skipped — a missed external dir costs a lookup, a bad parse must not crash.
    """
    config = base / "config.yaml"
    if not config.is_file():
        return []
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[str] = []
    in_block = False
    block_indent = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if not in_block:
            if stripped.startswith("external_dirs:"):
                rest = stripped.split(":", 1)[1].strip()
                if rest.startswith("["):
                    found += [v.strip().strip("'\"") for v in rest.strip("[]").split(",") if v.strip()]
                    break
                if not rest:  # block form, list follows on indented lines
                    in_block = True
                    block_indent = indent
            continue
        if stripped.startswith("- "):
            value = stripped[2:].strip().strip("'\"")
            if value:
                found.append(value)
        elif indent <= block_indent:
            break
    out: list[Path] = []
    for raw in found:
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            path = base / path
        out.append(path)
    return out


def _roots() -> list[Path]:
    """Every directory that may contain SKILL.md, most specific first."""
    base = _hermes_base()
    candidates: list[Path] = [base / "skills", Path.cwd() / ".hermes" / "skills"]
    profiles = base / "profiles"
    if profiles.is_dir():
        try:
            candidates += [p / "skills" for p in sorted(profiles.iterdir()) if p.is_dir()]
        except OSError:
            pass
    candidates += _external_dirs(base)
    seen: list[Path] = []
    for path in candidates:
        try:
            if path.is_dir() and path not in seen:
                seen.append(path)
        except OSError:
            continue
    return seen


def _declared_name(skill_md: Path) -> str:
    """The ``name:`` field from the frontmatter, or '' when absent/unreadable."""
    try:
        head = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
    lines = head.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:60]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.lower().startswith("name:"):
            return stripped.split(":", 1)[1].strip().strip("'\"")
    return ""


def locate(name: str) -> Optional[Path]:
    """Live directory of skill ``name`` or None (missing, archived, ambiguous).

    ``name`` may carry a category prefix (``category/name``); the leaf is what
    identifies the skill, which is how Hermes names them in tool calls.
    """
    if not name:
        return None
    leaf = name.replace("\\", "/").rstrip("/").split("/")[-1]
    if not leaf:
        return None
    for root in _roots():
        try:
            candidates = sorted(root.rglob("SKILL.md"))
        except OSError:
            continue
        for skill_md in candidates:
            if any(part in SKIP_PARTS for part in skill_md.parts):
                continue
            if skill_md.parent.name == leaf or _declared_name(skill_md) == leaf:
                return skill_md.parent
    return None


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
