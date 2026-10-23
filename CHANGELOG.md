# Changelog

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
