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

**1. Page A and page B get different hosts** (`https://a-<run>.example/a` vs `https://b-<run>.example/b`).
The fixture returns `{"url": ..., "content": ...}` as the tool result, so every page's origin becomes
an operative anchor. With both pages under one origin, `host:<origin>` appears in *every* source, and
a skill that writes `Source: <page url>` links to page B for free. That is a fixture artefact, not a
lineage failure. Both stay under `*.example`, as required.

**2. False link is reported twice.** `graph.start_nodes` returns `src:user:*` for any URL the user
message mentions, and the R1/R2/R3 wording names both URLs. A literal `descendants <page B url>` can
therefore reach the skill through the user node's anchor edge without any of B's content being used.
Two columns are reported instead of one number:
- `false link` — starts from the page-B node only: did B's content get claimed as a source?
- `via user url` — includes the user node: the literal CLI answer. A limitation worth surfacing,
  not evidence of leakage.

**3. R2 uses the same user wording as R1.** The protocol says "same conversation", so the prompt is
identical; R2 differs only in that a background review fork is then run. Whether the foreground wrote
a skill is recorded, not prevented.

**4. Thinking stays on (the provider default).** `deepseek-v4-flash` returns `reasoning_tokens` unless
`thinking.type=disabled` is sent. The protocol pins temperature only, so nothing else is overridden;
reasoning tokens are recorded separately in the totals.

## Report format

One table, per scenario: n, no-write, token kept, traced (default / --weak), false link, via user url.
Plus totals: runs, errors, requests, prompt/completion tokens, reasoning tokens, cost in USD.
Raw per-run records (written skills included) go to `eval/real/<date>/work/`; aggregate to `runs.json`.

No claim beyond those numbers.
