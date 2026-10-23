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


# Three shapes per pattern, each built from that pattern's own structure rather than from "a.", so a
# rewrite that trades one weakness for another is caught instead of passing on a single input. The
# 4x size step is what separates linear from quadratic: linear time grows ~4x, a nested quantifier
# grows ~16x, and the assertion below fails well before that.
HOSTILE = {
    "word_run": ("_WORD", "a", 1),
    "word_dashes": ("_WORD", "-", 1),
    "word_dots": ("_WORD", "a.", 2),
    "url_schemes": ("_URL", "http://", 7),
    "url_hosts": ("_URL", "http://example.com/", 19),
    "url_query": ("_URL", "http://example.com/?", 1),
    "ip_quads": ("_IP", "1.1.1.1.", 8),
    "ip_digits": ("_IP", "1", 1),
    "ip_octets": ("_IP", "255.", 4),
    "env_vars": ("_ENV", "$A", 2),
    "env_subshell": ("_ENV", "$( ", 3),
    "path_slashes": ("_PATH", "/", 1),
    "path_dot_slash": ("_PATH", "./", 2),
    "path_segments": ("_PATH", "a" * 40 + "/", 41),
    "command_backticks": ("_COMMAND", "`", 1),
    "command_subshell": ("_COMMAND", "$( ", 3),
    "install_repeats": ("_INSTALL", "pip install ", 12),
    "install_spaced": ("_INSTALL", "$( ", 3),
    "email_dots": ("_EMAIL", "a.", 2),
    "email_at": ("_EMAIL", "a@", 2),
    "email_at_dots": ("_EMAIL", "@.", 2),
}


def _repeat_expr(unit: str, width: int, size: float) -> str:
    return repr(unit) + " * %d" % int(size // width)


@pytest.mark.parametrize("label", sorted(HOSTILE))
def test_each_shape_grows_linearly_across_three_sizes(label):
    """0.25 MB -> 0.5 MB -> 1 MB of one hostile shape; time must grow with the data, not its square."""
    pattern, unit, width = HOSTILE[label]
    small = time_pattern(pattern, _repeat_expr(unit, width, 250_000))
    mid = time_pattern(pattern, _repeat_expr(unit, width, 500_000))
    large = time_pattern(pattern, _repeat_expr(unit, width, 1_000_000))

    assert large < 2.0, f"{pattern} on 1 MB of {label!r} took {large:.3f}s"
    if small > 0.02:  # below ~20 ms the measurement is dominated by start-up noise
        assert large / small < 8.0, (
            f"{pattern} on {label!r} grew x{large / small:.1f} for x4 data "
            f"({small:.3f}s -> {mid:.3f}s -> {large:.3f}s): no longer linear")


def test_the_slowest_measured_shape_has_headroom():
    """``_COMMAND`` on repeated ``"$( "`` is the slowest linear case: 0.42 s per MB locally.

    It is linear, so 2 MB — the cap on a tool result — stays around 0.85 s, and the whole
    ``anchor_strings`` pipeline stays inside the 5 s bar. Recorded as its own case so the trend,
    not only the absolute number, is visible if this ever changes.
    """
    measured = time_pattern("_COMMAND", _repeat_expr("$( ", 3, 1_000_000))
    assert measured < 2.0, f"_COMMAND on 1 MB of '$( ' took {measured:.3f}s"


def test_bounded_email_still_matches_real_addresses():
    assert "email:bob.smith+x@example.co.uk" in textfeat.anchor_strings("write to Bob.Smith+x@example.co.uk.")
    assert "email:ops@canary.example" in textfeat.anchor_strings("mail ops@canary.example")
    assert "email:a@b.c" in textfeat.anchor_strings("a@b.c")


@pytest.mark.parametrize("local", [65 * "y", "prefix." + 63 * "y"])
def test_local_part_longer_than_rfc_limit_is_not_an_anchor(local):
    """Documented narrowing: RFC 5321 caps the local part at 64 octets.

    The old ``\\b[\\w.+-]+@`` matched a 70-character local part; the bounded form does not. Such a
    string is not a deliverable address, and matching it is what cost quadratic time. This is the
    only behavioural difference the twelve-sample comparison turns up at v0.1.7.
    """
    assert textfeat.anchor_strings(f"contact {local}@example.com") == set()
    allowed = 64 * "y" + "@example.com"
    assert textfeat.anchor_strings(f"contact {allowed}") == {"email:" + allowed}


@pytest.mark.parametrize("lead", ["-", "+", "."])
def test_a_separator_before_an_address_is_not_part_of_it(lead):
    """A leading ``-``, ``+`` or ``.`` is dropped, so the address keeps the form the old pattern gave.

    The bounded pattern's lookbehind cannot tell a separator from the first character of a local
    part, so ``anchor_strings`` strips it. Without that, ``-name@example.com`` recorded at v0.1.6
    would hash differently from the same address in a chain written by v0.1.4, and one address would
    count as two.
    """
    assert textfeat.anchor_strings(f"write to {lead}bob@example.com") == {"email:bob@example.com"}
    assert textfeat.anchor_strings(f"write to {lead * 3}bob@example.com") == {"email:bob@example.com"}
