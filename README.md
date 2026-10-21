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

Measured on 2026-10-21 against Hermes `3166d61`: Python 3.14 **59 passed**;
Python 3.11 **51 passed, 1 skipped** (the end-to-end module). Earlier, on `33631f8`
with Hermes `e06df9c2ea` on Windows: 46 passed, 1 skipped. `hermes plugins validate`
passes with no warnings.

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

## Evaluation (synthetic, so far)

`python eval/run_eval.py --seed 2 --per-label 100` feeds 600 generated scenarios through
the plugin's hooks and checks every (page, skill) pair against a label fixed when the
scenario was built. Seed 1 was used while developing; seed 2 is the held-out set below.
Full output: `eval/results-seed2.json`.

| tracing mode | verbatim | paraphrase, operative token kept | paraphrase, no token | 2 hops via curator | unrelated page | shared boilerplate | user-dictated rule | precision |
|---|---|---|---|---|---|---|---|---|
| strong only | 200/200 | 0/100 | 0/100 | 0/100 | 6/400 | 0/200 | 0/200 | 0.980 |
| strong + anchor (default) | 200/200 | 100/100 | 0/100 | 100/100 | 6/400 | 0/200 | 0/200 | 0.988 |
| everything seen in the session | 200/200 | 100/100 | 100/100 | 100/100 | 400/400 | 200/200 | 200/200 | 0.385 |

Read this with its limits: the pages and paraphrases are generated from templates, and
the "operative token kept" paraphrases keep their token by construction — whether a real
model's rewrite keeps it is a separate measurement, not yet run. A paraphrase with no
operative token is not traced by default (0/100); following `context` links finds it,
at the cost shown in the last row. The 6 unrelated-page links are pairs of generated pages
that really share sentences (7 pairs in this set share 3 or more 8-word runs).

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
