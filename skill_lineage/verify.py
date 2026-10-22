"""Standalone verifier: ``python -m skill_lineage.verify <chain.jsonl> [--head HASH]``.

Standard library only; needs neither Hermes nor this plugin's data directory.
Exit codes: 0 intact, 1 broken or head not found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .chain import verify


def report(result, out=sys.stdout) -> int:
    if result.bad_seq is not None:
        print(f"BROKEN at seq {result.bad_seq}: {result.reason}", file=out)
        print(f"entries verified before the break: {result.entries}", file=out)
        return 1
    if not result.ok:
        print(f"BROKEN: {result.reason} ({result.entries} entries otherwise intact)", file=out)
        return 1
    if result.entries == 0:
        # An empty file is what `truncate -s 0`, a shell redirect, an editor save or
        # `git checkout` of an empty file leave behind — and it is also what a fresh
        # install creates. Nothing here can tell those apart, so this must not print
        # the word "intact", which is the one line a reader takes as "the record is fine".
        print("EMPTY: 0 entries, nothing to verify", file=out)
        print("note: an empty chain cannot be told apart from one truncated to zero bytes; "
              "this checks internal consistency only. Pass the head hash you recorded "
              "elsewhere with --head to detect a truncation.", file=out)
        return 0
    print(f"INTACT: {result.entries} entries, head seq {result.head_seq} hash {result.head_hash}", file=out)
    if result.after_given_head is not None:
        print(f"given head found; {result.after_given_head} entries follow it", file=out)
    if result.after_given_head is None:
        print("note: without a head hash recorded elsewhere this checks internal consistency only", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skill_lineage.verify", description=__doc__.splitlines()[0])
    parser.add_argument("chain", type=Path)
    parser.add_argument("--head", default=None, help="a head hash recorded earlier, outside this machine")
    args = parser.parse_args(argv)
    return report(verify(args.chain, args.head))


if __name__ == "__main__":
    sys.exit(main())
