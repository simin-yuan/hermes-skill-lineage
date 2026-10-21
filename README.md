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
- the features used to link a source to the added lines (`shingle` overlap,
  anchors such as URLs, identifiers and quoted strings, path/context proximity);
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

Measured on `33631f8` on 2026-10-21 (Hermes `e06df9c2ea`, Python 3.11.16 and
3.14.7): **46 passed, 1 skipped**. The skipped one is the end-to-end suite; it
skips with a printed reason when Hermes cannot be imported by the running
interpreter. `hermes plugins validate .` passes with no warnings.

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
