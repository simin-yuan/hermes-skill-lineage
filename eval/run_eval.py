"""Run the labelled scenarios through the plugin's hooks and report precision / recall per mode.

python eval/run_eval.py --seed 2 [--per-label 40] [--json out.json]
Seed 1 is the development set; seed 2 is the reported test set (not used while tuning).
Standard library only; Hermes is not needed (skills are written to a temporary folder).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent / "__fixtures__"))

from skill_lineage import chain, graph, store, textfeat  # noqa: E402
from skill_lineage.hooks import Tracker  # noqa: E402
from scenarios import build  # noqa: E402

MODES = {
    "strong-only": frozenset({"strong", "read-strong", "prev", "merge"}),
    "default (strong+anchor)": graph.DEFAULT_KINDS,
    "record-everything": graph.DEFAULT_KINDS | graph.WEAK_KINDS,
}


def run(seed: int, per_label: int) -> dict:
    work = Path(tempfile.mkdtemp(prefix="sl-eval-"))
    data, skills_dir = work / "data", work / "skills"
    data.mkdir()
    skills_dir.mkdir()

    def locate(name):
        d = skills_dir / name
        return d if (d / "SKILL.md").exists() else None

    t = Tracker(directory=lambda: data, locator=locate)
    scenarios = build(seed, per_label)
    page_node: dict[tuple[str, str], str] = {}
    call = 0
    for sc in scenarios:
        for sname, sess in sc.sessions.items():
            sess_id = f"{sc.sid}:{sname}"
            if sess["user"]:
                t.pre_llm_call(session_id=sess_id, user_message=sess["user"], platform="cli")
            for pname, text in sess["pages"]:
                call += 1
                url = f"https://pages.example/{sc.sid}/{pname}"
                t.post_tool_call(tool_name="web_extract", args={"urls": [url]}, result=text,
                                 session_id=sess_id, tool_call_id=f"t{call}")
                key = store.read_key(data)[0]
                page_node[(sc.sid, pname)] = f"src:ext:{textfeat.keyed_hex(key, text, 16)}"
        for w in sc.writes:
            sess_id = f"{sc.sid}:{w.session}"
            for r in w.reads:
                call += 1
                t.post_tool_call(tool_name="skill_view", args={"name": r}, result="{}",
                                 session_id=sess_id, tool_call_id=f"r{call}")
            call += 1
            args = {"operations": [{"action": "create", "name": w.skill, "content": w.text}]}
            t.pre_tool_call(tool_name="skill_manage", args=args, session_id=sess_id, tool_call_id=f"w{call}")
            (skills_dir / w.skill).mkdir(exist_ok=True)
            (skills_dir / w.skill / "SKILL.md").write_text(w.text, encoding="utf-8")
            t.post_tool_call(tool_name="skill_manage", args=args, result="{}", session_id=sess_id,
                             tool_call_id=f"w{call}")

    g = graph.load(data / chain.CHAIN_FILE)
    verified = chain.verify(data / chain.CHAIN_FILE).ok
    by_mode: dict = {}
    for mode, kinds in MODES.items():
        per_label_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [predicted linked, total]
        tp = fp = fn = 0
        for sc in scenarios:
            for pname, skill, label, derived in sc.truth:
                start = page_node[(sc.sid, pname)]
                target = g.latest.get(skill)
                linked = target is not None and target in graph.walk(g, {start}, True, kinds)
                per_label_counts[label][0] += int(linked)
                per_label_counts[label][1] += 1
                if derived and label != "D3":
                    tp += linked
                    fn += not linked
                elif not derived:
                    fp += linked
        rates = {lab: {"linked": a, "n": n, "rate": round(a / n, 3)} for lab, (a, n) in sorted(per_label_counts.items())}
        precision = tp / (tp + fp) if tp + fp else 0.0
        by_mode[mode] = {"labels": rates, "tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3)}
    return {"seed": seed, "per_label": per_label, "scenarios": len(scenarios), "chain_intact": verified,
            "modes": by_mode}


FLOORS = {"D1": 0.95, "D4": 0.95, "D2": 0.80}


def table(res: dict) -> str:
    labels = ["D1", "D2", "D3", "D4", "D4-other", "N1", "N2", "N3"]
    lines = [f"seed {res['seed']}, {res['scenarios']} scenarios, chain intact: {res['chain_intact']}",
             "| mode | " + " | ".join(labels) + " | precision (D vs N, D3 excluded) |",
             "|---" * (len(labels) + 2) + "|"]
    for mode, r in res["modes"].items():
        cells = []
        for lab in labels:
            x = r["labels"].get(lab)
            cells.append(f"{x['linked']}/{x['n']}" if x else "-")
        lines.append(f"| {mode} | " + " | ".join(cells) + f" | {r['precision']} ({r['tp']} TP, {r['fp']} FP) |")
    d = res["modes"]["default (strong+anchor)"]
    checks = []
    for lab, floor in FLOORS.items():
        rate = d["labels"][lab]["rate"]
        checks.append(f"{lab} recall {rate} {'>=' if rate >= floor else '<'} {floor}")
    rec = res["modes"]["record-everything"]["precision"]
    checks.append(f"default precision {d['precision']} {'>=' if d['precision'] >= 0.90 else '<'} 0.90 and "
                  f"{'>' if d['precision'] > rec else '<='} record-everything {rec}")
    return "\n".join(lines + ["", "pre-registered floors (design §8): " + "; ".join(checks)])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--per-label", type=int, default=40)
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    res = run(a.seed, a.per_label)
    print(table(res))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
