# Changelog

## 0.2.0 — 2026-10-30

**`HERMES_GUARD_MODE` has no effect here, and the README now says so instead of leaving it to be
discovered.** This plugin records lineage; it never refuses anything, so there is no posture for a
family mode to set. Reading the key and doing nothing is the correct behaviour, not an omission —
what would be wrong is staying silent about it while its two siblings honour the key.

Documentation only: no runtime change in this release. Verified against Hermes `b4170e7` and current
`main` on Python 3.11–3.14 — 139 tests pass with Hermes installed.

## 0.1.8 — 2026-10-23

- Behaviour: the bounded pattern is kept as written, and a leading `.`, `+` or `-` is now removed
  where the match is used, so `-name@example.com` records `name@example.com` exactly as 0.1.4 did.
  Without that, an address next to a separator hashed one way in an old chain and another way now,
  and one address counted as two. Re-compared against 0.1.4 on 13 samples: 2 differ, both a local
  part longer than 64 octets, which is the only intended difference (RFC 5321; matching it is what
  cost quadratic time). Post-processing costs nothing measurable — `anchor_strings` on 2 MB of
  `"a."` is 0.631 s with it, 0.664 s without.
- Coverage: every pattern in `textfeat` now has three hostile shapes of its own — 21 in total —
  each measured at 0.25, 0.5 and 1 MB in a fresh process with a hard timeout, and the 4x step must
  stay linear. Nothing is super-linear; the slowest is `_COMMAND` on repeated `"$( "` at 0.42 s per
  MB (1.0 MB 0.42 s, 2.1 MB 0.85 s, 4.2 MB 1.76 s — x4.2 for x4 data), so the e-mail pattern is no
  longer the expensive one. 43 tests in the file, 16 s.

## 0.1.7 — 2026-10-23

- Fixed: a user turn is an origin again for text the user dictated. 0.1.4 dropped user turns from
  the edge pass outright while keeping their text out of the same-class discount, so every dictated
  skill ended up with no origin at all and `test_foreground_verbatim_unrelated_and_user_rule`
  (both `[plain]` and `[stream]`) failed on the `hermes-tools` job from that release on. The
  recorded smoke run in `tests/smoke-2026-10-21.txt` shows what the plugin did before: a strong
  edge from `src:user:…` into the skill ("5 shingles; into skill smoke-probe"). The eval is
  unchanged at 240 scenarios — N3 0/80, precision 1.0, every pre-registered floor met — because
  what keeps a page from being credited for dictated text is the same-class discount, not the
  removal of the user turn.
- Tests: `test_a_user_turn_is_the_origin_of_what_the_user_typed` and
  `test_a_page_is_not_credited_for_user_dictated_text` replace one test that asserted a stronger
  rule than the design does (`user turns produce no edge at all`).

## 0.1.6 — 2026-10-23

- Guards: the 2 MB reproducer now asserts under 5 s rather than 2 s. The bounded pattern alone is
  0.05 s on the machine these numbers come from, but the whole `anchor_strings` pass is 0.6-1.2 s
  because seven other patterns scan the same text, so a slower runner could have reached the old
  bar. The old pattern needs 143 s at 200 KB, so the guard still separates the two by orders of
  magnitude.
- Recorded the second output difference between the old and the new e-mail pattern, which 0.1.5
  described as the only one: an ASCII `-`, `+` or `.` directly before an address is now the first
  character of the local part instead of being left out, because `` anchored after it and the
  lookbehind does not. RFC 5321 atext allows that character, and it is the same token to a reader.

## 0.1.5 — 2026-10-23

- Fixed quadratic-time e-mail regex in `anchor_strings` (reported by @teknium1 in review of
  NousResearch/hermes-agent#142381). The local part is bounded to 64 octets (RFC 5321) and
  anchored with a lookbehind instead of `\b`, so a run of word characters is no longer re-scanned
  from every offset. Timed on the pattern alone: 40 KB of `"a."` 4.1 s → 0.0005 s, 200 KB
  104 s → 0.0026 s, 2 MB (over an hour under the old pattern) → 0.027 s. `anchor_strings` end to
  end on `"a." * 1_000_000` (2 MB): 0.55 s.
- Added `tests/test_textfeat_perf.py`: one pathological input for every pattern, plus the review's
  2 MB reproducer through `anchor_strings`. Each case runs in its own process with a hard timeout,
  so a regression fails the run instead of hanging it.
- `HERMES_HOME` is now profile-aware via `hermes_constants.get_hermes_home()`, resolved on every
  call and with an environment fallback for Hermes releases that predate the helper. Skill lookup
  in `skills.py` follows the session's profile, not the launch profile.
- Behaviour difference, documented in the tests: an address whose local part exceeds 64 octets is
  no longer an anchor. All the other samples compared (12, including `bob.smith+x@example.co.uk`)
  match identically.

Earlier versions: see `git log`.
