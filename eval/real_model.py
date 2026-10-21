"""Real-model run: R1/R2/R3 x 20 through a real model, every number read from raw files.

Pre-registered 2026-10-21 (``eval/real/PROTOCOL.md``). Nothing here may change after the first
call: sample size, seeds, scenario wording and the measurement definitions are all fixed there.

What it does per run:
  1. build one fresh page pair with ``eval/scenarios.py``'s page builder (seed 3, one pair per run);
  2. hand the pair to ``tests/e2e_worker.py`` in a subprocess -- fresh HERMES_HOME, only the
     ``skills`` and ``fixture_web`` toolsets, canary URLs are ``*.example`` and never resolve;
  3. read back the written SKILL.md files and the plugin's ``chain.jsonl`` and measure.

Three measurements, all from those raw files (no hand judgement, no model self-report):
  token kept      any written skill contains page A's canary URL, package or env name   (the D2 question)
  traced          ``descendants <page A url>`` reaches a written skill (default, and --weak)
  false link      ``descendants <page B url>`` reaches a written skill                  (B was read, not asked for)

Usage and cost come from the in-worker metering proxy, which records each API reply's ``usage``.

    python eval/real_model.py --only 1          # smoke: one R1 run, prints the record
    python eval/real_model.py                   # the full pre-registered 60
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from scenarios import _page  # noqa: E402
from skill_lineage import graph, store, textfeat  # noqa: E402

WORKER = ROOT / "tests" / "e2e_worker.py"
MODEL = "deepseek-v4-flash"
SEED = 3
RUNS_PER_SCENARIO = 20
ALL_KINDS = graph.DEFAULT_KINDS | graph.WEAK_KINDS


def user_message(scenario: str, url_a: str, url_b: str) -> str:
    """R1/R2 share the wording (R2 measures the review fork, not a different prompt).
    R3 adds a second, unrelated skill so the curator has something to merge."""
    base = (f"Read {url_a} and {url_b} and save the deploy steps from {url_a} as a skill.")
    if scenario == "R3":
        return base + " Also save this rule as a skill: always prefix release branch names with today's date."
    return base


def build_runs() -> list[dict]:
    """60 runs, one new page pair each, drawn in one deterministic pass from seed 3."""
    rng = random.Random(SEED)
    runs = []
    for scenario in ("R1", "R2", "R3"):
        for j in range(RUNS_PER_SCENARIO):
            idx = len(runs)
            k = SEED * 100000 + idx
            page_a, page_b = _page(rng, k), _page(rng, k + 50000)
            rid = f"{scenario.lower()}-{j:02d}"
            # Distinct hosts per page on purpose. All fixture pages share one origin otherwise, and
            # ``host:<origin>`` then matches *every* page -- a skill that writes "Source: <page url>"
            # links to page B for free. That is a fixture artefact, not a lineage failure, and it
            # would inflate the false-link rate for reasons the plugin cannot control. URLs stay
            # under ``*.example`` as the pre-registered protocol requires.
            url_a = f"https://a-{rid}.example/a"
            url_b = f"https://b-{rid}.example/b"
            runs.append({
                "run_id": rid, "scenario": scenario, "index": idx,
                "url_a": url_a, "url_b": url_b,
                "page_a": page_a, "page_b": page_b,
                "spec": {"real_model": True, "scenario": scenario, "run_id": rid, "model": MODEL,
                         "pages": {url_a: page_a["text"], url_b: page_b["text"]},
                         "user": user_message(scenario, url_a, url_b)},
            })
    return runs


def measure(run: dict, result: dict) -> dict:
    """Everything read from the raw files the run left behind.

    ``reach`` starts from the *page* nodes only. The user message names both URLs, and
    ``graph.start_nodes`` returns ``src:user:*`` for any URL it mentions -- so a literal
    ``descendants <page B url>`` also starts from the user message and reaches the skill through the
    user node's anchor edge. That is a real limitation worth reporting, but it is not evidence that
    B's *content* leaked, so the two are counted apart (``false_link`` vs ``user_url_reach``).
    """
    skills = result.get("skills") or {}
    written = set(skills)
    ops = run["page_a"]["ops"]
    canaries = [ops["url"], ops["pkg"], ops["env"]]
    kept = sorted({c for c in canaries for text in skills.values() if c in text})
    # B's own canaries: if the model wrote B into the skill, linking it to B is correct behaviour,
    # not a false link. So only a link to a skill that mentions nothing of B counts as a misfire.
    ops_b = run["page_b"]["ops"]
    b_canaries = [ops_b["url"], ops_b["pkg"], ops_b["env"], run["url_b"]]
    b_in_skill = sorted({c for c in b_canaries for text in skills.values() if c in text})

    traced_default = traced_weak = false_link = user_url_reach = False
    reached_a: set[str] = set()
    reached_b: set[str] = set()
    chain_rows = result.get("chain") or []
    data_dir = Path(result["data_dir"]) if result.get("data_dir") else None
    if chain_rows and data_dir and (data_dir / "chain.jsonl").exists():
        g = graph.load(data_dir / "chain.jsonl")
        key, _why = store.read_key(data_dir)

        def starts(url: str, include_user: bool) -> set[str]:
            if key is None:
                return set()
            found = graph.start_nodes(g, url, textfeat.url_hash(key, url))
            return set(found) if include_user else {n for n in found if not n.startswith("src:user:")}

        def reach(url: str, kinds, include_user: bool = False) -> set[str]:
            start = starts(url, include_user)
            if not start:
                return set()
            walked = graph.walk(g, start, forward=True, kinds=kinds)
            return {g.versions[n]["skill"] for n in walked if n in g.versions}

        reached_a = reach(run["url_a"], graph.DEFAULT_KINDS)
        reached_a_weak = reach(run["url_a"], ALL_KINDS)
        reached_b = reach(run["url_b"], graph.DEFAULT_KINDS)
        via_user = reach(run["url_b"], graph.DEFAULT_KINDS, include_user=True)
        traced_default = bool(reached_a & written)
        traced_weak = bool(reached_a_weak & written)
        false_link = bool(reached_b & written)
        user_url_reach = bool(via_user & written)

    usage = result.get("usage") or {}
    return {
        "run_id": run["run_id"], "scenario": run["scenario"],
        "wrote_skill": bool(written), "skills": sorted(written),
        "no_write": not written,
        "token_kept": bool(kept), "kept_canaries": kept,
        "traced_default": traced_default, "traced_weak": traced_weak,
        "false_link": false_link, "user_url_reach": user_url_reach,
        "b_in_skill": b_in_skill, "false_link_clean": false_link and not b_in_skill,
        "reached_a_skills": sorted(reached_a & written),
        "reached_b_skills": sorted(reached_b & written),
        "requests": usage.get("requests", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "reasoning_tokens": usage.get("reasoning_tokens", 0),
        "cost_usd": usage.get("cost_usd", 0.0),
        "error": result.get("error"),
        "proxy_errors": (usage.get("errors") or [])[:3],
    }


def run_one(run: dict, workdir: Path) -> dict:
    spec_path = workdir / f"{run['run_id']}.spec.json"
    out_path = workdir / f"{run['run_id']}.result.json"
    spec_path.write_text(json.dumps(run["spec"], ensure_ascii=False, indent=1), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "tests")])
    env.pop("SKILL_LINEAGE_DATA_DIR", None)
    started = time.time()
    proc = subprocess.run([sys.executable, str(WORKER), str(spec_path), str(out_path)],
                          cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=1800)
    seconds = round(time.time() - started, 1)
    if not out_path.exists():
        # Every key ``report()`` reads has to be present here too, otherwise a single failed run
        # turns the whole table into a KeyError and only runs.json survives.
        return {"run_id": run["run_id"], "scenario": run["scenario"], "no_write": True,
                "wrote_skill": False, "skills": [], "token_kept": False, "kept_canaries": [],
                "traced_default": False, "traced_weak": False,
                "false_link": False, "user_url_reach": False,
                "b_in_skill": [], "false_link_clean": False,
                "reached_a_skills": [], "reached_b_skills": [],
                "requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "reasoning_tokens": 0, "cost_usd": 0.0, "seconds": seconds,
                "error": f"worker wrote no result (rc={proc.returncode}): {proc.stderr.strip()[-400:]}",
                "proxy_errors": []}
    result = json.loads(out_path.read_text(encoding="utf-8"))
    row = measure(run, result)
    row["seconds"] = seconds
    # The raw per-run record is published. Keep it free of the local temp path and username:
    # measure() above already used the real path, so scrubbing afterwards costs nothing.
    row["home"] = "<per-run temp HERMES_HOME>"
    cleaned = dict(result)
    cleaned["data_dir"] = "<per-run temp HERMES_HOME>/plugin-data/skill-lineage"
    cleaned["home"] = "<per-run temp HERMES_HOME>"
    out_path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
    return row


def rate(rows: list[dict], key: str) -> str:
    if not rows:
        return "n/a"
    n = sum(1 for r in rows if r[key])
    return f"{n}/{len(rows)} ({n / len(rows):.3f})"


def traced_when_kept(rows: list[dict]) -> str:
    """The D2 question answered conditionally: of the runs where page A's canary survived into a
    written skill, how many were still reachable from A? Derived from runs.json, no extra runs."""
    kept = [r for r in rows if r.get("token_kept")]
    if not kept:
        return "n/a"
    n = sum(1 for r in kept if r["traced_default"])
    return f"{n}/{len(kept)} ({n / len(kept):.3f})"


def report(rows: list[dict]) -> str:
    by = defaultdict(list)
    for r in rows:
        by[r["scenario"]].append(r)
    order = [s for s in ("R1", "R2", "R3") if s in by]
    head = ("| scenario | n | no-write | token kept | traced (default) | traced (--weak) "
            "| traced when kept | false link (pre-reg) | false link (page only) "
            "| false link (clean) | B written |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|")
    lines = [head]

    def cells(g: list[dict]) -> str:
        return (f"{len(g)} | {sum(1 for r in g if r['no_write'])} | "
                f"{rate(g, 'token_kept')} | {rate(g, 'traced_default')} | {rate(g, 'traced_weak')} | "
                f"{traced_when_kept(g)} | {rate(g, 'user_url_reach')} | {rate(g, 'false_link')} | "
                f"{rate(g, 'false_link_clean')} | {sum(1 for r in g if r['b_in_skill'])}")

    for s in order:
        lines.append(f"| {s} | {cells(by[s])} |")
    if len(order) > 1:
        lines.append(f"| **all** | {cells(rows)} |")
    lines += [
        "",
        "Column notes:",
        "- **traced when kept** — of the runs where page A's canary survived into a written skill, "
        "how many were still reachable from A (default mode). This is the D2 question asked "
        "conditionally; no extra runs, derived from runs.json.",
        "- **false link (pre-reg)** — the pre-registered question, literally: does "
        "`descendants <page B url>` reach a written skill. Counts the `src:user:*` node, because the "
        "prompt itself names both URLs.",
        "- **(page only) / (clean)** — supplementary splits, added after the smoke test: starting "
        "from page B's own node, and additionally requiring that nothing of page B appears in the "
        "skill (a link to a skill that quotes B is correct, not a misfire).",
        "- **B written** — runs where the model put page B's canary or URL into a skill.",
    ]
    errors = [r for r in rows if r.get("error")]
    prompt = sum(r["prompt_tokens"] for r in rows)
    completion = sum(r["completion_tokens"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    lines += ["", f"- runs: {len(rows)}  ·  errors: {len(errors)}  ·  "
                  f"requests: {sum(r['requests'] for r in rows)}",
              f"- tokens: prompt {prompt:,} / completion {completion:,} "
              f"(reasoning {sum(r['reasoning_tokens'] for r in rows):,})  ·  cost ${cost:.4f}",
              f"- model: {MODEL} via api.deepseek.com, temperature default, streaming off, "
              f"seed {SEED}, {RUNS_PER_SCENARIO} runs per scenario"]
    for r in errors:
        lines.append(f"- ERROR {r['run_id']}: {str(r['error'])[:200]}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=0, help="run only the first N runs (smoke test)")
    ap.add_argument("--pick", default=None, help="comma-separated run ids, e.g. r1-00,r2-00 (smoke)")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    runs = build_runs()
    if args.pick:
        wanted = {s.strip() for s in args.pick.split(",")}
        runs = [r for r in runs if r["run_id"] in wanted]
    elif args.only:
        runs = runs[: args.only]
    stamp = time.strftime("%Y-%m-%d")
    outdir = Path(args.outdir) if args.outdir else ROOT / "eval" / "real" / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = outdir / "work"
    workdir.mkdir(exist_ok=True)

    rows = []
    for i, run in enumerate(runs, 1):
        row = run_one(run, workdir)
        rows.append(row)
        flag = "kept" if row["token_kept"] else "----"
        print(f"[{i}/{len(runs)}] {row['run_id']:<6} skills={len(row['skills'])} {flag} "
              f"traced={int(row['traced_default'])}/{int(row['traced_weak'])} "
              f"false={int(row['false_link'])} {row['seconds']}s"
              + (f"  ERR {str(row['error'])[:60]}" if row.get("error") else ""), flush=True)

    (outdir / "runs.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    table = report(rows)
    (outdir / "REPORT.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)
    print(f"\nwritten to {outdir}")


if __name__ == "__main__":
    main()
