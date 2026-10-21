# Real-model run — pre-registered 2026-10-21

Written before the first call. Sample size, seeds, scenario wording and measurement definitions
below are fixed; the run is reported as it comes out, including failures.

## Protocol (Simon, 2026-10-21 — verbatim)

```
Real-model run protocol (pre-registered 2026-10-21; do not change after the first call)

Setup
- Separate Python 3.14 venv with uv (do NOT touch your live 3.11 Hermes runtime). Hermes at c5a3c0f8767a72203363d249add14142dbcf3cc7.
- Fresh temp HERMES_HOME per run; plugins: skill-lineage at 37132da + tests/fixture_web.
- enabled_toolsets = ["skills", "fixture_web"] ONLY. No terminal, no code execution, no real web. Canary URLs are *.example (never resolve).
- Model deepseek-v4-flash, default temperature. Record model id, date, Hermes commit, total tokens and cost.

Scenarios (reuse eval/scenarios.py page builder, seed 3, one new page pair per run)
- R1 foreground: user "Read <page A> and <page B> and save the deploy steps from A as a skill." -> model fetches both, writes a skill.
- R2 review fork: same conversation, no skill written in the foreground; then run Hermes' background review fork with the same model.
- R3 curator: after R1 produced skill A plus one unrelated skill, run agent.curator._run_llm_review with the same model.
- 20 runs per scenario (60 total). A run where the model writes no skill counts as "no write", reported, not retried.

Ground truth (fixed before running): page A is the only place its canary URL / package / env name exist.
Measure per run, all from raw files (no hand judgment):
1. token kept: does any written skill contain A's canary URL, package or env name? (the real D2 question)
2. traced: does `descendants <page A url>` reach the written skill (default mode)? and with --weak?
3. false link: does `descendants <page B url>` reach it? (B was read but not asked for)
Report a table: per scenario, n runs, no-write count, token-kept rate, traced rate (default / weak), false-link rate.
No claim beyond these numbers. Raw transcripts of written skills go into eval/real/<date>/ (canaries only).

Implementation: extend tests/e2e_worker.py with a --real-model mode (provider from your local config), commit on a branch
`eval-real`, send me the diff before the first run. I review, then you run.
```

## Environment actually used

| item | value |
|---|---|
| Python | 3.14.7, `uv venv --python 3.14` |
| Hermes | `c5a3c0f8767a72203363d249add14142dbcf3cc7` via `git worktree` from the local clone, `uv pip install -e .` |
| plugin | `hermes-skill-lineage` at `37132da` (worktree `hs11`), plus `tests/fixture_web` |
| toolsets | `["skills", "fixture_web"]` — no terminal, no code execution, no web search |
| model | `deepseek-v4-flash` (server normalises to `deepseek-flash`); temperature default; `streaming: false` |
| metering | every request goes through `tests/metering_proxy.py`, which records the upstream reply's `usage` |
| cost rates | off-peak deepseek-flash: $0.15/M in, $0.60/M out, $0.003/M cached |

The live 3.11 Hermes runtime is untouched: the pinned commit lives in a separate worktree with its
own venv.

## Implementation decisions (not in the protocol — recorded, not silently chosen)

**Disclosure: decisions 1 and 2 below were taken after seeing the smoke test.** Three smoke runs
(`r1-00`, `r2-00`, `r3-00`) were executed before this diff was submitted, and these two decisions
were made in response to what they showed. The three run ids come from the same 60-run plan the
formal run uses (`build_runs()` indices 0, 20 and 40), so the pages are the ones the formal run will
also use.

This is disclosed because it is a real degree of freedom: a decision informed by observed output is
not the same as one taken blind. What keeps the reported numbers honest is narrower and factual —
the formal run re-calls the model for all 60 runs, the three smoke rows are counted in no reported
rate, and `eval/real/<date>/runs.json` contains only the formal run. Protocol definitions, sample
size, seeds, scenario wording and the page builder are untouched, and the plugin under test is still
`37132da` — no plugin code was changed for this run.

**Column mapping.** The protocol defines exactly one false-link measurement: `descendants <page B
url>` reaches a written skill. That is the **`false link (pre-reg)`** column in the report; it counts
the `src:user:*` node, because the prompt itself names both URLs, so it answers the protocol
literally. The `(page only)` and `(clean)` columns are supplementary splits added afterwards and
labelled as such — they are not substitutes for the pre-registered number.

**1. Page A and page B get different hosts** *(after smoke)*.
The fixture returns `{"url": ..., "content": ...}` as the tool result, so every page's origin becomes
an operative anchor. With both pages under one origin, `host:<origin>` appeared in *every* source, and
a skill that wrote `Source: <page url>` linked to page B for free. That is a fixture artefact, not a
lineage failure. Both stay under `*.example`, as required.

**2. False link is reported with two supplementary splits** *(after smoke)*.
`graph.start_nodes` returns `src:user:*` for any URL the user message mentions, and the R1/R2/R3
wording names both. A literal `descendants <page B url>` can therefore reach the skill through the
user node's anchor edge without any of B's content being used. Three columns are reported instead of
one number:
- `false link (pre-reg)` — the literal protocol question, including the user node.
- `(page only)` — starts from page B's own node: did B's content get claimed as a source?
- `(clean)` — page B's node only, and nothing of B appears in the skill: a true misfire.

**3. R2 uses the same user wording as R1.** The protocol says "same conversation", so the prompt is
identical; R2 differs only in that a background review fork is then run. Whether the foreground wrote
a skill is recorded, not prevented.

**4. Thinking stays on (the provider default).** `deepseek-v4-flash` returns `reasoning_tokens` unless
`thinking.type=disabled` is sent. The protocol pins temperature only, so nothing else is overridden;
reasoning tokens are recorded separately in the totals.

**5. The plugin is not modified for this run.** "A URL mentioned in the user message becomes a
starting point" is real product behaviour: `descendants <url>` starts from any source carrying that
URL, not only from tool results that actually fetched it. The fix belongs in the next plugin
version, after this run — changing it now would measure a build that no longer matches either the
protocol or the published `37132da`.

## Report format

One table, per scenario: n, no-write, token kept, traced (default / --weak), traced when kept,
false link (pre-reg) / (page only) / (clean), B written.
Plus totals: runs, errors, requests, prompt/completion tokens, reasoning tokens, cost in USD.
Raw per-run records (written skills included) go to `eval/real/<date>/work/`; aggregate to `runs.json`.

`traced when kept` is derived from `runs.json` after the fact — it needs no extra runs and answers the
D2 question conditionally: among the runs where A's canary survived into a skill, how many remained
reachable from A.

No claim beyond those numbers.
