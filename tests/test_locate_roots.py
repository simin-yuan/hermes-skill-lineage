"""Skill lookup without importing Hermes.

The catalog validator warns on any import from the private part of the Hermes
package (rule 9), so ``locate`` has to find every skill by scanning. These tests
pin the layouts it must cover and the ones it must not: a category prefix in the
name, a skill only present under ``profiles/*/skills``, a project-local
``.hermes/skills``, and ``skills.external_dirs`` from config.yaml.
"""

import os
import sys
import types
from pathlib import Path

import pytest

from skill_lineage import skills


def make_skill(root: Path, rel: str, name: str | None = None) -> Path:
    """Create ``<root>/<rel>/SKILL.md`` and return the directory."""
    directory = root / rel
    directory.mkdir(parents=True, exist_ok=True)
    declared = name if name is not None else Path(rel).name
    directory.joinpath("SKILL.md").write_text(
        f"---\nname: {declared}\ndescription: test skill\n---\n\nbody\n", encoding="utf-8"
    )
    return directory


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # keep a project dir from the real cwd out of the scan
    return tmp_path


def test_flat_layout(home):
    want = make_skill(home / "skills", "deploy")
    assert skills.locate("deploy") == want


def test_category_prefix_in_name(home):
    """Hermes names skills ``category/name`` in tool calls."""
    want = make_skill(home / "skills" / "devops", "deploy")
    assert skills.locate("devops/deploy") == want


def test_nested_categories(home):
    want = make_skill(home / "skills" / "a" / "b", "deploy")
    assert skills.locate("a/b/deploy") == want


def test_found_by_declared_name_when_dir_differs(home):
    """The directory may be renamed while the skill keeps its name."""
    want = make_skill(home / "skills" / "cat", "_old_dir", name="deploy")
    assert skills.locate("deploy") == want


def test_archive_is_skipped(home):
    make_skill(home / "skills" / ".archive", "deploy")
    assert skills.locate("deploy") is None


def test_hub_is_skipped(home):
    make_skill(home / "skills" / ".hub" / "pack", "deploy")
    assert skills.locate("deploy") is None


def test_profile_skills_dir(home):
    want = make_skill(home / "profiles" / "researcher" / "skills", "deep")
    assert skills.locate("deep") == want


def test_project_skills_dir(home, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    want = make_skill(project / ".hermes" / "skills", "localrule")
    os.chdir(project)
    try:
        assert skills.locate("localrule") == want
    finally:
        os.chdir(home)


def test_external_dirs_block_form(home):
    external = home / "outside"
    want = make_skill(external, "borrowed")
    home.joinpath("config.yaml").write_text(
        "skills:\n  external_dirs:\n    - outside\n", encoding="utf-8"
    )
    assert skills.locate("borrowed") == want


def test_external_dirs_inline_form(home):
    external = home / "outside"
    want = make_skill(external, "borrowed")
    home.joinpath("config.yaml").write_text(
        'skills:\n  external_dirs: ["outside"]\n', encoding="utf-8"
    )
    assert skills.locate("borrowed") == want


def test_missing_skill_returns_none(home):
    make_skill(home / "skills", "present")
    assert skills.locate("absent") is None
    assert skills.locate("") is None


def test_no_private_hermes_imports():
    """Rule 9: the module must not import from the Hermes package."""
    source = Path(skills.__file__).read_text(encoding="utf-8")
    assert "from tools." not in source
    assert "import tools" not in source
    assert "from agent." not in source
    assert "from hermes_cli" not in source


def _fake_constants(home):
    """A stand-in for ``hermes_constants``; the plugin imports only ``get_hermes_home`` from it."""
    module = types.ModuleType("hermes_constants")
    setattr(module, "get_hermes_home", lambda: home)
    return module


def test_hermes_home_comes_from_get_hermes_home_not_the_env(tmp_path, monkeypatch):
    """One process, several profiles: the env names the launch profile, the helper names this one."""
    launch = tmp_path / "launch"
    session = tmp_path / "session-profile"
    launch.mkdir()
    want = make_skill(session, "skills/profiled")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setitem(sys.modules, "hermes_constants", _fake_constants(session))
    monkeypatch.chdir(tmp_path)  # no project-local .hermes/skills may answer for it
    assert skills.locate("profiled") == want


def test_hermes_home_is_read_per_call_not_cached_at_import(tmp_path, monkeypatch):
    """A value cached at import would still pin the first profile; the helper is asked every call."""
    first, second = tmp_path / "one", tmp_path / "two"
    one = make_skill(first, "skills/alpha")
    two = make_skill(second, "skills/beta")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "hermes_constants", _fake_constants(first))
    assert skills.locate("alpha") == one
    assert skills.locate("beta") is None
    monkeypatch.setitem(sys.modules, "hermes_constants", _fake_constants(second))
    assert skills.locate("beta") == two
    assert skills.locate("alpha") is None


def test_missing_helper_falls_back_to_the_environment(tmp_path, monkeypatch):
    """Older Hermes: no ``get_hermes_home``; the launch profile is still searched."""
    home = tmp_path / "legacy"
    want = make_skill(home, "skills/legacy")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setitem(sys.modules, "hermes_constants", types.ModuleType("hermes_constants"))
    monkeypatch.chdir(tmp_path)
    assert skills.locate("legacy") == want
