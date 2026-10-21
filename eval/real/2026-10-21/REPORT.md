| scenario | n | no-write | token kept | traced (default) | traced (--weak) | traced when kept | false link (pre-reg) | false link (page only) | false link (clean) | B written |
|---|---|---|---|---|---|---|---|---|---|---|
| R1 | 20 | 3 | 16/20 (0.800) | 17/20 (0.850) | 17/20 (0.850) | 16/16 (1.000) | 16/20 (0.800) | 10/20 (0.500) | 3/20 (0.150) | 7 |
| R2 | 20 | 0 | 20/20 (1.000) | 20/20 (1.000) | 20/20 (1.000) | 20/20 (1.000) | 20/20 (1.000) | 11/20 (0.550) | 3/20 (0.150) | 8 |
| R3 | 20 | 0 | 17/20 (0.850) | 17/20 (0.850) | 20/20 (1.000) | 17/17 (1.000) | 17/20 (0.850) | 6/20 (0.300) | 4/20 (0.200) | 2 |
| **all** | 60 | 3 | 53/60 (0.883) | 54/60 (0.900) | 57/60 (0.950) | 53/53 (1.000) | 53/60 (0.883) | 27/60 (0.450) | 10/60 (0.167) | 17 |

Column notes:
- **traced when kept** — of the runs where page A's canary survived into a written skill, how many were still reachable from A (default mode). This is the D2 question asked conditionally; no extra runs, derived from runs.json.
- **false link (pre-reg)** — the pre-registered question, literally: does `descendants <page B url>` reach a written skill. Counts the `src:user:*` node, because the prompt itself names both URLs.
- **(page only) / (clean)** — supplementary splits, added after the smoke test: starting from page B's own node, and additionally requiring that nothing of page B appears in the skill (a link to a skill that quotes B is correct, not a misfire).
- **B written** — runs where the model put page B's canary or URL into a skill.

- runs: 60  ·  errors: 0  ·  requests: 593
- tokens: prompt 4,495,035 / completion 335,355 (reasoning 127,099)  ·  cost $0.2954
- model: deepseek-v4-flash via api.deepseek.com, temperature default, streaming off, seed 3, 20 runs per scenario

## Notes on the numbers (facts, not conclusions)

**`traced when kept` is 53/53.** Every run whose skill kept page A's canary was reachable from A in
default mode. There is no kept-but-untraced run in this batch.

**3 runs wrote no skill at all** — r1-10, r1-13, r1-17, all in R1. Counted as no-write, not retried,
as the protocol requires.

**1 run kept no canary yet was still traced**: r1-05. Its skill cites `Source:
https://a-r1-05.example/a` and nowhere reproduces A's canary URL, package or env name, so it links
through the page-URL anchor. Its traceability comes from the model writing the citation, not from the
canary surviving.

**`--weak` adds exactly 3 traces in R3, and all 3 are the unrelated skill.** r3-01, r3-04 and r3-10
trace to `release-branch-date-prefix` — the second skill the curator scenario asks for, unrelated to
page A. Default mode correctly does not link them; `--weak` links them through the context edge.

**The 10 `false link (clean)` runs split into 8 strong edges and 2 anchor edges.** For the strong
ones, pages A and B share 14–17 identical 8-token shingles in this fixture: the page template has
fixed sentences, so a skill that copies those sentences from A links to B as well (r2-03's edge
carries `sh=17`, equal to the A∩B overlap measured for that same pair). This is a property of the
fixture rather than of the plugin — two unrelated pages do not normally share 14–17 sentences. The
16.7% figure is therefore an upper bound produced under template homogeneity, and is not a
measurement of the real-world misfire rate.

**`false link (pre-reg)` is 53/60 because the prompt itself names page B's URL.** That is the
`src:user:*` behaviour described in PROTOCOL.md. The fix is scheduled for the next plugin version,
after this run, so that this run measures `37132da`.
