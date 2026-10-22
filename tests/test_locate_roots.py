"""Skill lookup without importing Hermes.

The catalog validator warns on any import from the private part of the Hermes
package (rule 9), so ``locate`` has to find every skill by scanning. These tests
pin the layouts it must cover and the ones it must not: a category prefix in the
name, a skill only present under ``profiles/*/skills``, a project-local
``.hermes/skills``, and ``skills.external_dirs`` from config.yaml.
"""

import os
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
