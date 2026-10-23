# Changelog

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
