| scenario | n | no-write | token kept | traced (default) | traced (--weak) | traced when kept | false link (pre-reg) | false link (page only) | false link (clean) | B written |
|---|---|---|---|---|---|---|---|---|---|---|
| R1 | 20 | 1 | 19/20 (0.950) | 19/20 (0.950) | 19/20 (0.950) | 19/19 (1.000) | 0/20 (0.000) | 0/20 (0.000) | 0/20 (0.000) | 5 |
| R2 | 20 | 0 | 20/20 (1.000) | 19/20 (0.950) | 20/20 (1.000) | 19/20 (0.950) | 5/20 (0.250) | 5/20 (0.250) | 2/20 (0.100) | 6 |
| R3 | 20 | 0 | 17/20 (0.850) | 17/20 (0.850) | 20/20 (1.000) | 17/17 (1.000) | 1/20 (0.050) | 1/20 (0.050) | 0/20 (0.000) | 2 |
| **all** | 60 | 1 | 56/60 (0.933) | 55/60 (0.917) | 59/60 (0.983) | 55/56 (0.982) | 6/60 (0.100) | 6/60 (0.100) | 2/60 (0.033) | 13 |

Column notes:
- **traced when kept** — of the runs where page A's canary survived into a written skill, how many were still reachable from A (default mode). This is the D2 question asked conditionally; no extra runs, derived from runs.json.
- **false link (pre-reg)** — the pre-registered question, literally: does `descendants <page B url>` reach a written skill. Counts the `src:user:*` node, because the prompt itself names both URLs.
- **(page only) / (clean)** — supplementary splits, added after the smoke test: starting from page B's own node, and additionally requiring that nothing of page B appears in the skill (a link to a skill that quotes B is correct, not a misfire).
- **B written** — runs where the model put page B's canary or URL into a skill.

- runs: 60  ·  errors: 0  ·  requests: 630
- tokens: prompt 5,133,556 / completion 359,733 (reasoning 135,052)  ·  cost $0.3160
- model: deepseek-v4-flash via api.deepseek.com, temperature default, streaming off, seed 3, 20 runs per scenario
- plugin build: `e147b7e` (v0.1.3). The batch in `../2026-10-21/` used `37132da` (v0.1.2).

## Side by side with the v0.1.2 batch (same protocol, same seed, same model)

| scenario | false link (pre-reg) | false link (clean) | traced when kept |
|---|---|---|---|
| R1 | 16/20 → 0/20 | 3/20 → 0/20 | 16/16 → 19/19 |
| R2 | 20/20 → 5/20 | 3/20 → 2/20 | 20/20 → 19/20 |
| R3 | 17/20 → 1/20 | 4/20 → 0/20 | 17/17 → 17/17 |
| **all** | 53/60 → **6/60** | 10/60 → **2/60** | 53/53 → **55/56** |

## Notes on the numbers (facts, not conclusions)

**`traced when kept` is 55/56, not 56/56.** The one kept-but-untraced run is `r2-14`. Its skill
`untrusted-content-review` keeps page A's package canary only as an illustration — the line reads
``package names that look minted (`cedar-pebble300034==1.5`)`` — and reproduces none of A's steps.
Measured on the final text it shares **0** eight-token shingles with page A, and its only extracted
anchor is `env:TOKEN` (from the placeholder `export <VAR>_TOKEN`), so it shares no anchor with A
either. Every edge in its chain is `context` / `prev` / `read-context`.

The same run id in the v0.1.2 batch traced successfully, but that batch's model wrote two different
skills: `zephyr-garnet-warmup` (which copies A's procedure — 16 shared shingles with A, 15 of them
unique to A) plus `capturing-procedures-as-skills`. Its A-edge carries `sh=123`. **The v0.1.3 edge
rule would link that same skill too** — 15 unique shingles is well above the threshold of 3. The
difference between the two batches on this run is what the model wrote, not which rule was applied.

**6 `false link (pre-reg)`, of which 4 are correct links.** `r2-06`, `r2-13`, `r2-18` and `r3-06`
each have page B's canary or URL inside the written skill (`b_in_skill` non-empty). Reaching a skill
that quotes B is the right answer, not a misfire. The remaining 2 are `r2-01` and `r2-03`.

**Those 2 are version-level links to text the model later deleted.** Both runs create the skill once
including B's material, then rewrite it several times:

- `r2-01`: `seq=3` creates `alder-rollback-runbook` with `strong` edges to both pages (`sh=111` to A,
  `sh=109` to B); `seq=4`, `seq=6`, `seq=8` rewrite it. The final text shares 19 shingles with A and
  **1** with B.
- `r2-03`: `seq=3` creates `thorn-lumen-juniper-upgrade` with `strong sh=110` to A and `anchor an=1`
  to B; `seq=4` rewrites it. The final text shares 12 shingles with A, 9 with B, **0** of them
  unique to B, and **0** of B's anchors.

So the link is true of the version that earned it and false of the final text. `false link (clean)`
is computed against final text while edges are recorded per version — the two measure different
things, and this split is where it shows. Under a per-version reading these 2 are correct links too.

**1 run wrote no skill**: `r1-09`. Counted as no-write, not retried, per protocol.

**`--weak` adds the same 3 R3 traces as before**: `r3-01`, `r3-04`, `r3-10` link to
`release-branch-date-prefix`, the unrelated skill the curator scenario asks for. `r3-04` and `r3-07`
keep no canary and stay untraced in default mode — the same two shapes appear in the v0.1.2 batch.
