# skill-lineage

A Hermes plugin that records **where each skill's content came from**, and lets
you verify the record afterwards.

To audit a skill that rewrites itself, you need to answer two questions
afterwards: *which* text went into it, and *whether* the record of that is
intact. This plugin answers both, per skill version.

## What it records

For every skill write — a foreground `skill_manage` call, a background review
edit, or a curator consolidation — the plugin stores:

- the skill's content fingerprint before and after the write;
- the sources that were in the same session before that write: the text the user
  typed, tool results (a fetched page, a file), and other skills that were read;
- how each source is linked to the added lines: `strong` (at least 3 shared
  8-word shingles), `anchor` (a shared operative token — URL or host, a shell
  command with its first argument, a package install, a file path, an environment
  variable, an IP or e-mail address — that is not common across sources), or
  `context` (seen in the session, nothing measurable shared; recorded, not followed
  by default);
- a `seq → prev_hash → hash` chain over all of the above.

Text is never stored. Hashes are keyed, so two installs cannot be compared
against each other, and the key lives in `plugin-data/skill-lineage`, not in the
repository.

## What it answers

```
hermes skill-lineage status        # is anything being recorded, and from when
hermes skill-lineage trace <skill> # where the newest version of a skill came from
hermes skill-lineage descendants <url|skill>   # everything a source produced
hermes skill-lineage report        # versions with operative lines of no traceable origin
hermes skill-lineage verify        # is the chain intact
hermes skill-lineage head          # newest seq + hash, to record somewhere else
```

`descendants` runs the other way: give it a page or a skill, get back every
skill whose content it ended up inside.

`verify` re-walks the chain; `head` prints a value you can write down outside
this machine, so a later `verify --head <value>` can tell truncation from an
intact chain. A key reset is recorded in the chain and shown in `status` instead
of happening silently.

## Install

```
hermes plugins install skill-lineage   # from the catalog, once listed
```

Requires Hermes >= 0.21.5. No dependencies outside the standard library. No
network calls.

## Tests

```
python -m pytest -q
hermes plugins validate .
```

Hermes itself runs on Python 3.14 only, so the end-to-end suite (a real Hermes agent
against a local fake model server: foreground writes, the background review fork,
curator consolidation and the Tool Search bridge) runs on 3.14 and skips with a
printed reason elsewhere. The plugin code and unit tests are standard-library only.

Measured at v0.1.4 (2026-10-22): **84 passed, 1 skipped** on Python **3.14.7** and on
Python **3.11.16** — the end-to-end module skips in both, printing its reason (no Hermes
install on the machine that produced these numbers). Earlier: 60 passed, 1 skipped at
`8df4bcb`; 59 passed at `3166d61` with Hermes on 3.14; 46 passed, 1 skipped at `33631f8`
with Hermes `e06df9c2ea` on Windows. `hermes plugins validate .` reports no failures and
no warnings at v0.1.4.

Manual end-to-end smoke run on Hermes `e06df9c2ea` (2026-10-21, isolated
`HERMES_HOME`, plugin enabled, one real session that created a skill through
`skill_manage`): passed — `status`, `trace`, `descendants`, `report`, `verify`
and `head` all returned as documented. Raw output in
`tests/smoke-2026-10-21.txt`.

## What this does not do

- It does not stop a write, and it does not judge whether a skill is good. It
  records and it verifies.
- It does not prove a source *caused* an edit. The link is computed from shared
  content plus session order; `report` exists because some lines have no
  traceable origin and that should be visible rather than smoothed over.
- It covers skills only. Changes to `MEMORY.md` or to any external memory
  backend are not recorded.
- A skill archived by the curator, and a skill file edited between sessions
  without `skill_manage`, do not reach the graph yet. Hermes' skill ledger and
  the curator's `run.json` are not documented APIs; a weekly CI job runs against
  Hermes `main`, so a format change fails a build instead of going silent.
- Without an anchor, `verify` is an internal-consistency check and nothing more: it shows
  the chain is self-consistent, not that it was not truncated. An empty chain therefore
  prints `EMPTY`, never `INTACT`. Recording `hermes skill-lineage head --json` somewhere
  off this machine (another repository, or an OpenTimestamps stamp of the printed hash)
  and passing it back with `verify --head HASH` is the recommended setup, not an optional
  extra — it is the only check that can tell a truncated chain from a fresh one.
- A skill write the plugin cannot locate on disk leaves no chain entry at all: locating is
  a directory scan, so a name that resolves somewhere outside the scanned roots produces
  no version line, and a failed write is indistinguishable from a no-op.
- If the pre-call snapshot is missing (a reload between the two hooks, or a post that
  arrives alone), the whole existing body counts as new text, so a one-line patch can pick
  up a strong link to an unrelated page seen in that session.
- Tool arguments are never treated as a source, and user turns in non-user platforms are
  skipped: text dictated through a `delegate_task` goal, a cron prompt or a curator run
  reaches the graph with no recorded origin.
- `report` calls a version untraceable only when the session saw external content *and* the
  body carries an anchor (a URL, host, path or command). Prose with no anchor is never
  flagged, even when nothing in the session could have produced it.
- A tool result is kept up to 2,000,000 characters from its start. Text copied from the tail
  of a longer result can only reach a `context` edge, and its anchors are then reported as
  untraceable — the one direction in which the report raises a false alarm.
- The source de-duplication index (`nodes.idx`) is not rebuilt from the chain. After a chain
  is emptied or rolled back, a source seen again is not written back, so its edges point at
  an id the chain no longer defines.

## Related work

Lineage for agent memory already exists; this plugin applies it to skills on a
shipping agent. Neighbouring work, and how this differs:

- **MemLineage** (Ouyang & Hou, [arXiv:2605.14421](https://arxiv.org/abs/2605.14421))
  introduced signed, Merkle-logged agent memory with a weighted derivation graph and
  an action gate. Independent implementations exist
  ([amurlaniakea/memlineage](https://github.com/amurlaniakea/memlineage),
  [dan0nchik/memlineage-provenance-loss](https://github.com/dan0nchik/memlineage-provenance-loss)).
  The latter shows, on a research harness, that lineage is lost when an agent
  refines or merges skills, and that recording everything the model saw over-taints
  clean skills. No code from these projects is used here.
- **Attacks on self-written skills** motivate this: SkillJack
  ([arXiv:2608.03509](https://arxiv.org/abs/2608.03509)), trajectory poisoning of
  self-evolving skills ([arXiv:2608.05563](https://arxiv.org/abs/2608.05563)),
  self-poisoning skill libraries ([arXiv:2608.25776](https://arxiv.org/abs/2608.25776)).
- **Other layers on Hermes**: `memory-rewind` keeps version history,
  `skill-integrity` detects changed skill files, `memory-shield` gates memory writes,
  `provenance-gate` checks claimed user decisions. [runxhq/runx](https://github.com/runxhq/runx)
  signs receipts of what ran and who allowed it. Hermes #139096 asks for the
  *install* source of a skill; #141990 / #142018 export *session* lineage
  (compression chain and subagent trees). This plugin records *content* lineage:
  which session evidence the lines of a skill came from.

What is specific here: it runs on Hermes' real skill lifecycle — foreground writes,
the background review fork and curator consolidation — and its `anchor` links target
paraphrased payloads that keep their operative tokens.

## Evaluation

Two separate measurements. The first feeds generated scenarios through the plugin's hooks and
checks every (page, skill) pair against a label fixed when the scenario was built. The second runs a
real model in a real Hermes install and asks whether the same links hold. They answer different
questions and neither substitutes for the other.

### Generated scenarios

`python eval/run_eval.py --seed N --per-label 100` builds 600 scenarios per seed. Seed 1 was used
while developing. Seeds 2 and 4 are held-out; seed 4 was run against the v0.1.3 edge rules and no
tuning followed it. Full output: `eval/results-seed2.json`, `eval/results-seed4-v013.json`.

| tracing mode | verbatim | paraphrase, operative token kept | paraphrase, no token | 2 hops via curator | unrelated page | shared boilerplate | user-dictated rule | precision |
|---|---|---|---|---|---|---|---|---|
| strong only (v0.1.2, seed 2) | 200/200 | 0/100 | 0/100 | 0/100 | 6/400 | 0/200 | 0/200 | 0.980 |
| **strong only (v0.1.3, seed 4)** | 200/200 | 0/100 | 0/100 | 0/100 | **0/400** | 0/200 | 0/200 | **1.000** |
| strong + anchor (v0.1.2, seed 2) | 200/200 | 100/100 | 0/100 | 100/100 | 6/400 | 0/200 | 0/200 | 0.988 |
| **strong + anchor (v0.1.3, seed 4)** | 200/200 | 100/100 | 0/100 | 100/100 | **0/400** | 0/200 | 0/200 | **1.000** |
| everything seen in the session (either version) | 200/200 | 100/100 | 100/100 | 100/100 | 400/400 | 200/200 | 200/200 | 0.385 |

Re-run at v0.1.4 on 2026-10-22 against the same seeds: every cell above is unchanged, so the
numbers carry over. v0.1.4 changed one edge rule — overlap is now only discounted between
sources of the same class, so a user message quoting a page no longer cancels the page's link.
That case is not among the generated labels; `tests/test_shared_text.py` covers it instead,
including the controls (a lone page, and two pages sharing a template sentence).

Seed 4 rows are the default configuration; the 0/400 on unrelated pages comes from the rule that
only text unique to one source counts toward a strong edge. Under v0.1.2, pairs of generated pages
that share template sentences were linked through that shared wording.

Read these rows with their limits. The pages and paraphrases are generated from templates, and the
"operative token kept" paraphrases keep their token by construction. A paraphrase with no operative
token is not traced by default (0/100); following `context` links finds it at the cost shown in the
last row. Whether a real model's rewrite keeps the token is not something this table can tell you —
that is the measurement below.

### Real model, two batches

60 runs per batch: 20 per scenario, one fresh Hermes install per run, one page pair and one task per
run, `deepseek-v4-flash` at default temperature, seed 3. Protocol, prompts and scenario wording are
identical between the batches; the only change is the plugin build. Raw records and per-run evidence:
`eval/real/2026-10-21/` (v0.1.2, `37132da`) and `eval/real/2026-10-21-v013/` (v0.1.3, `e147b7e`).

The per-run transcripts (`*.result.json`, 1.8 MB) are not in this repository. They are model
output rather than source, and the plugin validator scans every text file in the tree, so their
shell-shaped payloads read as plugin code. They are archived as a separate dataset together with
`eval/real/MANIFEST.json`, which lists every file with its sha256 and the plugin commit it was
produced from; the dataset DOI is recorded in the release notes for v0.1.4. The protocol, the
scenario wording, `runs.json` and each run's `REPORT.md` stay here — those are what a re-run needs.

| | v0.1.2 | v0.1.3 | Fisher exact, two-sided |
|---|---|---|---|
| false link (pre-registered) | 53/60 | **6/60** | 4.1 × 10⁻¹⁹ |
| false link (clean, final text) | 10/60 | **2/60** | 0.029 |
| false link (clean, per version) | 6/60 | **0/60** | 0.027 |
| traced when kept | 53/53 | 55/56 | — |

Two things to keep in mind before quoting these numbers.

**The batches are independent samples, not a paired comparison.** Each batch draws its own 60 model
runs. The same run id in the two batches is the same scenario, not the same output — the model
writes something different each time, and it often does. The r2-14 case is the clearest example and
is described below.

**"Per version" is exact for v0.1.3 and a sufficient-condition check for v0.1.2.** The plugin
records an edge against the version of the skill that earned it, while the "clean" columns ask
whether the skill's text contains anything from page B. A skill can be created with B's wording and
later rewritten without it; the edge stays true of the version, and the final text stops matching.
For v0.1.3 the edge weights themselves count only source-unique overlap, so the column is exact. For
v0.1.2 the weights include wording shared with the other page, so a link counts as version-correct
only when its overlap exceeds the number of 8-word runs the two pages share — a sufficient
condition, not an exact recount, because v0.1.2 did not preserve skill version text.

**r2-14, the one kept-but-untraced run in v0.1.3.** The model wrote a review checklist rather than a
procedure, quoting page A's package canary only as an example of a minted-looking name, and
reproducing none of A's steps. Its final text shares no 8-word run with page A, and the package name
appears without `pip install`, so the anchor extractor does not recognise it. The v0.1.2 batch traced
the same run id because that batch's model copied A's procedure outright. Recognising bare
identifiers is planned, not done.

**The 2 remaining clean false links in v0.1.3.** Both are cases where the model created the skill with
page B's material and then rewrote it without. `r2-01`'s first version has a `strong` edge from B
(109 B-only runs); after three rewrites the final text shares 1 run with B. `r2-03` opens with an
anchor match and ends with none. They are correct links to the version that earned them, which is
what the per-version row counts.

**4 of the 6 pre-registered false links are correct links.** In `r2-06`, `r2-13`, `r2-18` and `r3-06`
the written skill contains page B's canary or URL. The pre-registered question is whether B's node
reaches any written skill, and reaching a skill that quotes B is the right answer. The two split
columns exist to separate these from genuine misfires.

**`--weak` reaches 3 extra skills in R3, all false positives.** They link to `release-branch-date-prefix`,
the unrelated skill the curator scenario asks for. `--weak` means "written in a session that read this
source", which is a weaker claim than "contains its content" and should be read that way.

## Disclosure

Reads tool results, user messages and skill files to compute keyed hashes. Keeps
those hashes (no text) for 7 days per session, and the lineage chain (hashes and
skill names) under `plugin-data/skill-lineage`. No network. Never blocks or
changes a tool call.

## Record

- Discovered: 2026-10-20
- First public: 2026-10-21
- Patch commit: `33631f8adb10964fbd0af1f260e7dd81f178399a`

## License

Apache-2.0 — see `LICENSE` and `NOTICE`.
