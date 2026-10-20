"""End-to-end through a real Hermes install (fake model server, real AIAgent, real forks).

Skipped when Hermes is not importable, unless SKILL_LINEAGE_REQUIRE_E2E=1 (CI sets it).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
sys.path.insert(0, str(REPO))

PROBE = r"""
import json, sys
from pathlib import Path
out = {"problem": ""}
try:
    import agent.background_review, agent.curator, run_agent  # what the worker imports
    from hermes_cli.plugins_manifest import running_hermes_version, version_satisfies
    spec = next((l.split(":", 1)[1].strip().strip('"') for l in
                 Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.startswith("requires_hermes:")), "")
    running = running_hermes_version()
    if spec and not version_satisfies(spec, running):
        out["problem"] = f"needs Hermes {spec}, running {running}: Hermes would skip the plugin"
except BaseException as exc:  # SystemExit too: importing run_agent may relaunch the process
    out["problem"] = f"Hermes cannot be imported here ({type(exc).__name__}: {exc})"
print("PROBE" + json.dumps(out))
"""


def _hermes_problem() -> str:
    """Why the end-to-end tests cannot run here, or "". Hermes runs on Python 3.14 only, and importing
    run_agent can relaunch the process (hermes_bootstrap), so nothing Hermes is imported in this process:
    a child process imports what the worker imports and reports back."""
    if sys.version_info < (3, 14):
        return f"Hermes runs on Python 3.14 only (pyproject.toml); this is {sys.version.split()[0]}"
    if importlib.util.find_spec("run_agent") is None:
        return "Hermes is not importable (run_agent not found)"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    try:
        proc = subprocess.run([sys.executable, "-c", PROBE, str(REPO / "plugin.yaml")], capture_output=True,
                              text=True, timeout=300, env=env, cwd=str(TESTS))
    except subprocess.TimeoutExpired:
        return "Hermes import probe timed out"
    line = next((l for l in proc.stdout.splitlines() if l.startswith("PROBE")), "")
    if not line:
        tail = (proc.stderr.strip().splitlines() or ["no output"])[-1]
        return f"Hermes import probe exited {proc.returncode}: {tail}"
    return json.loads(line[len("PROBE"):])["problem"]


if (_problem := _hermes_problem()):
    if os.environ.get("SKILL_LINEAGE_REQUIRE_E2E") == "1":
        raise RuntimeError(_problem)
    pytest.skip(_problem, allow_module_level=True)

from skill_lineage import chain, graph  # noqa: E402


pytestmark = pytest.mark.e2e
_cache: dict = {}


def run(scenario, stream, tmp_path_factory, bridge=False):
    key = (scenario, stream, bridge)
    if key not in _cache:
        work = tmp_path_factory.mktemp(f"{scenario}-{stream}")
        spec, out = work / "spec.json", work / "out.json"
        spec.write_text(json.dumps({"scenario": scenario, "stream": stream, "bridge": bridge}), encoding="utf-8")
        # The worker is a separate process: hand it exactly the import path this pytest run has, so a
        # Hermes checkout found through PYTHONPATH (not only an installed one) is found there too.
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
        proc = subprocess.run([sys.executable, str(TESTS / "e2e_worker.py"), str(spec), str(out)],
                              capture_output=True, text=True, timeout=600, env=env)
        assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["stream_flags"] == [stream]
        _cache[key] = result
    return _cache[key]


def lineage(result):
    g = graph.load(Path(result["data_dir"]) / chain.CHAIN_FILE)
    page = [n for n, s in g.sources.items() if s.get("tool") == "fetch_page"]
    return g, page


def reached_skills(g, start, weak=False):
    kinds = graph.DEFAULT_KINDS | (graph.WEAK_KINDS if weak else frozenset())
    return {g.versions[n]["skill"] for n in graph.walk(g, set(start), True, kinds) if n in g.versions}


@pytest.fixture(params=[False, True], ids=["plain", "stream"])
def stream(request):
    return request.param


def test_foreground_verbatim_unrelated_and_user_rule(stream, tmp_path_factory):
    r = run("foreground", stream, tmp_path_factory)
    assert set(r["skills"]) >= {"deploy-a", "status-check", "indent"}
    assert chain.verify(Path(r["data_dir"]) / chain.CHAIN_FILE).ok
    g, pages = lineage(r)
    assert len(pages) == 2  # both fetched pages became ext sources
    deploy_page = [n for n in pages if any(e.get("k") == "strong" for _, e in g.children.get(n, []))]
    assert len(deploy_page) == 1
    assert reached_skills(g, deploy_page) == {"deploy-a"}                            # D1 strong
    assert reached_skills(g, deploy_page, weak=True) == {"deploy-a", "status-check", "indent"}  # context only
    weather = [n for n in pages if n not in deploy_page]
    assert reached_skills(g, weather) == set()                                       # N1
    user = [n for n, s in g.sources.items() if s["cls"] == "user"]
    assert reached_skills(g, user) == {"indent"}                                     # N3 traced to the user
    assert r["leaks"] == []


def test_background_review_paraphrase_is_anchored(stream, tmp_path_factory):
    r = run("background_review", stream, tmp_path_factory)
    assert "predeploy" in r["skills"]
    g, pages = lineage(r)
    versions = [v for v in g.versions.values() if v["skill"] == "predeploy"]
    assert len(versions) == 1
    kinds = {e["k"] for e in versions[0]["edges"]}
    assert "anchor" in kinds                                                          # D5 via the fork
    assert any(reached_skills(g, [p]) == {"predeploy"} for p in pages)
    assert r["leaks"] == []


def test_curator_merge_two_hops(stream, tmp_path_factory):
    r = run("curator", stream, tmp_path_factory)
    assert "deploy" in r["skills"]
    g, pages = lineage(r)
    deploy_page = [n for n in pages if any(e.get("k") == "strong" for _, e in g.children.get(n, []))]
    assert reached_skills(g, deploy_page) == {"deploy-a", "deploy"}                  # D4: page -> a -> umbrella
    umbrella = [v for v in g.versions.values() if v["skill"] == "deploy"][0]
    assert {e["k"] for e in umbrella["edges"]} >= {"read-anchor", "read-strong"}
    assert umbrella["session"] != [v for v in g.versions.values() if v["skill"] == "deploy-a"][0]["session"]
    assert chain.verify(Path(r["data_dir"]) / chain.CHAIN_FILE).ok


def test_tool_search_bridge_keeps_the_real_tool_name(stream, tmp_path_factory):
    """Hermes' default Tool Search reaches plugin/MCP tools through tool_call; hooks see the real name."""
    r = run("bridge", stream, tmp_path_factory, bridge=True)
    g, pages = lineage(r)
    assert len(pages) == 1 and reached_skills(g, pages) == {"deploy-a"}
    assert not any(s.get("tool") in ("tool_call", "tool_search", "tool_describe") for s in g.sources.values())
