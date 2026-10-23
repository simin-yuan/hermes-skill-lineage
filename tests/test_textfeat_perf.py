"""Hostile-input timing guards for the patterns in ``textfeat``.

``anchor_strings`` runs on every tool result inside ``post_tool_call``, and results are capped at
2 MB rather than sanitised, so a prompt-injected page is a regular expression's input. CPython's
``re`` holds the GIL for the whole call: a slow pattern cannot be interrupted by Hermes' hook
timeout, it stalls the turn.

Each case therefore runs in its own process with a hard timeout — a regression fails the run
instead of hanging it — and every pattern gets one pathological input of its own, so a future edit
that reintroduces a nested quantifier is caught by the pattern it lands in, not only by the
end-to-end path.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from skill_lineage import textfeat

ROOT = Path(__file__).resolve().parents[1]
HARD_TIMEOUT = 10.0  # seconds; a healthy case finishes in milliseconds


def elapsed(body: str, *, timeout: float = HARD_TIMEOUT) -> float:
    """Run ``body`` in a fresh interpreter (it must print one float) and return that float.

    ``body`` gets ``textfeat`` imported. A case that exceeds ``timeout`` fails the test with the
    case name rather than wedging the suite.
    """
    script = "import sys, time\nsys.path.insert(0, %r)\nfrom skill_lineage import textfeat\n%s\n" % (str(ROOT), textwrap.dedent(body))
    try:
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                              timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        pytest.fail(f"case did not finish within {timeout:g}s — the pattern has regressed to "
                    f"super-linear time on hostile input:\n{textwrap.dedent(body)}")
    assert proc.returncode == 0, proc.stderr.strip()[-2000:]
    return float(proc.stdout.strip().splitlines()[-1])


def time_pattern(pattern: str, text_expr: str) -> float:
    return elapsed(
        f"text = {text_expr}\n"
        f"start = time.perf_counter()\n"
        f"n = sum(1 for _ in textfeat.{pattern}.finditer(text))\n"
        f"print(round(time.perf_counter() - start, 6))\n"
    )


def test_two_megabytes_of_dots_through_anchor_strings():
    """The review's reproducer: 2 MB of ``a.`` used to take over an hour via the e-mail pattern.

    The bounded pattern alone runs the 2 MB in ~0.05 s. The whole ``anchor_strings`` pipeline is
    ~0.6–1.2 s on the machine these numbers come from, because seven other patterns scan the same
    text; a CI runner is slower again, so the bar is 5 s. That is still three orders of magnitude
    below the old behaviour (200 KB took 143 s, so 2 MB is measured in hours), so any return to
    quadratic time fails loudly, and the subprocess timeout catches a case that never returns.
    """
    measured = elapsed(
        "text = 'a.' * 1_000_000\n"
        "start = time.perf_counter()\n"
        "textfeat.anchor_strings(text)\n"
        "print(round(time.perf_counter() - start, 6))\n"
    )
    assert measured < 5.0, f"anchor_strings on 2 MB of 'a.' took {measured:.3f}s"


def test_email_pattern_alone_on_two_megabytes():
    """The fixed pattern itself, without the rest of the pipeline: ~0.03 s, bar 0.2 s."""
    measured = time_pattern("_EMAIL", "'a.' * 1_000_000")
    assert measured < 0.2, f"_EMAIL on 2 MB of 'a.' took {measured:.3f}s"


PATHOLOGICAL = {
    # label: (pattern attribute, expression building the hostile one-liner)
    "word": ("_WORD", "'a' * 200_000"),
    "url": ("_URL", "'http://' + 'a' * 200_000"),
    "email": ("_EMAIL", "'a.' * 100_000"),
    "ip": ("_IP", "'1.' * 100_000"),
    "ip_long_octet": ("_IP", "'1' * 200_000"),
    "env": ("_ENV", "'$' + 'A' * 200_000"),
    "env_assignment": ("_ENV", "'A' * 200_000 + '='"),
    "path_posix": ("_PATH", "'/' + 'a/' * 100_000"),
    "path_windows": ("_PATH", r"'C:\\' + 'a\\\\' * 100_000"),
    "path_windows_tail": ("_PATH", r"'C:\\' + 'a' * 200_000"),
    "command": ("_COMMAND", "'curl' + ' a' * 100_000"),
    "install": ("_INSTALL", "'pip install ' + 'a' * 200_000"),
    "install_spaced": ("_INSTALL", "'pip install ' + 'a ' * 100_000"),
}


@pytest.mark.parametrize("label", sorted(PATHOLOGICAL))
def test_every_pattern_is_linear_on_hostile_input(label):
    """One hostile one-liner per pattern; all of them measured under 50 ms on 200–600 KB."""
    pattern, expr = PATHOLOGICAL[label]
    measured = time_pattern(pattern, expr)
    assert measured < 1.0, f"{pattern} on a pathological {label} input took {measured:.3f}s"


def test_bounded_email_still_matches_real_addresses():
    assert "email:bob.smith+x@example.co.uk" in textfeat.anchor_strings("write to Bob.Smith+x@example.co.uk.")
    assert "email:ops@canary.example" in textfeat.anchor_strings("mail ops@canary.example")
    assert "email:a@b.c" in textfeat.anchor_strings("a@b.c")


@pytest.mark.parametrize("local", [65 * "y", "prefix." + 63 * "y"])
def test_local_part_longer_than_rfc_limit_is_not_an_anchor(local):
    """Documented narrowing: RFC 5321 caps the local part at 64 octets.

    The old ``\\b[\\w.+-]+@`` matched a 70-character local part; the bounded form does not. Such a
    string is not a deliverable address, and matching it is what cost quadratic time.

    This is one of the two differences the twelve-sample comparison turned up. The other is that an
    ASCII ``-``, ``+`` or ``.`` immediately before an address is now kept as the first character of
    the local part, because ``\\b`` used to start the match after the separator while the lookbehind
    does not; see ``test_a_separator_before_an_address_is_kept_in_the_anchor``.
    """
    assert textfeat.anchor_strings(f"contact {local}@example.com") == set()
    allowed = 64 * "y" + "@example.com"
    assert textfeat.anchor_strings(f"contact {allowed}") == {"email:" + allowed}


@pytest.mark.parametrize("lead", ["-", "+", "."])
def test_a_separator_before_an_address_is_kept_in_the_anchor(lead):
    """The second difference between the old and the new pattern, recorded so it stays visible.

    ``\\b`` started the match after ``-``, ``+`` or ``.``; the lookbehind has no such anchor, so the
    separator becomes the first character of the local part, which RFC 5321 atext allows. It is the
    same token to a reader, and it is the whole of the difference on that input.
    """
    assert textfeat.anchor_strings(f"write to {lead}bob@example.com") == {f"email:{lead}bob@example.com"}
