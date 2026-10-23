"""A page still counts as the origin when the user message quotes the same text.

Text that two recorded sources both contain cannot say which one a skill came
from, so overlap shared between sources is discounted. The discount used to be
applied between *all* sources at once, which meant a user turn quoting a page
erased the overlap on both sides: the page lost its strong edge and fell back to
``context`` (not followed by default, so ``trace`` printed "no recorded origin"),
and the user turn — which never gets an edge by design — kept nothing either.

The usable reading is the common one: "I pasted this page for you" is how a page
reaches a skill, so a quote must not cancel the page. Discounting still applies
within a class, which is what keeps two pages sharing a template sentence from
both claiming the copy.
"""

from skill_lineage import edges, textfeat
from skill_lineage.sessions import Seen

KEY = b"k" * 32
SNIP = ("run the release checklist from the internal deployment handbook before every production push "
        "and confirm the on call engineer has acknowledged the change window in writing")


def src(text, cls="ext", node=None):
    return Seen(kind="src", node=node or f"src:{cls}:{hash(text)}", cls=cls,
                shingles=textfeat.shingles(KEY, text), anchors=textfeat.anchors(KEY, text))


def kinds(found):
    return [e.kind for e in found]


def test_page_alone_is_strong():
    """Control: the plain case the README advertises."""
    found, _ = edges.compute(KEY, "- " + SNIP, "",
                             [src("Handbook excerpt: " + SNIP + " ...", node="src:ext:page")], set())
    assert kinds(found) == ["strong"]


def test_page_stays_strong_when_user_message_quotes_it():
    page = src("Handbook excerpt: " + SNIP + " ...", node="src:ext:page")
    user = src("Heads up, I pasted the handbook section: " + SNIP, cls="user", node="src:user:u1")

    found, _ = edges.compute(KEY, "- " + SNIP, "", [user, page], set())

    page_edges = [e for e in found if e.node == "src:ext:page"]
    assert page_edges, "the page produced no edge at all"
    assert page_edges[0].kind == "strong", (
        f"the page was demoted to {page_edges[0].kind!r} because the user message quoted it")


def test_a_user_turn_is_the_origin_of_what_the_user_typed():
    """The eval's N3 case: a rule the user dictates comes from that turn, so the turn is an origin.

    Guard for 0.1.7: user turns were dropped from the edge pass outright, which left every dictated
    skill with no origin at all and broke the end-to-end scenario that traces a dictated rule back
    to the turn that dictated it. The recorded smoke run in ``tests/smoke-2026-10-21.txt`` shows the
    shipped behaviour was a strong edge from ``src:user:…`` ("5 shingles; into skill smoke-probe").
    """
    user = src("Also: always use tabs for indentation in every python file of this project.",
               cls="user", node="src:user:u1")

    found, _ = edges.compute(
        KEY, "- always use tabs for indentation in every python file of this project", "", [user], set())

    user_edges = [e for e in found if e.node == "src:user:u1"]
    assert user_edges and user_edges[0].kind == "strong", [e.kind for e in user_edges]


def test_a_page_is_not_credited_for_user_dictated_text():
    """What the eval's 0/200 floor checks: the page read in the session gets no attributable edge."""
    page = src("Weather for the site: sunny, force five, high tide at noon on the eastern shore.",
               node="src:ext:weather")
    user = src("Also: always use tabs for indentation in every python file of this project.",
               cls="user", node="src:user:u1")

    found, _ = edges.compute(
        KEY, "- always use tabs for indentation in every python file of this project", "",
        [user, page], set())

    assert not [e for e in found if e.node == "src:ext:weather" and e.kind in ("strong", "anchor")], (
        "a page was credited for text the user dictated")


def test_two_pages_sharing_boilerplate_still_discriminate():
    """Template sentences must not make both pages claim the copy."""
    template = "All rights reserved. This guide was reviewed by the platform team on a quarterly basis."
    quoted = template + " " + SNIP
    other = template + " Restart the warden service whenever the ledger looks stale overnight."

    found, _ = edges.compute(KEY, "- " + SNIP, "",
                             [src(quoted, node="src:ext:quoted"), src(other, node="src:ext:other")], set())

    by_node = {e.node: e.kind for e in found}
    assert by_node.get("src:ext:quoted") == "strong", by_node
    assert by_node.get("src:ext:other") != "strong", by_node


def test_overlap_between_two_tool_results_still_discounted():
    """Same class, so the discount must still apply: two pages cannot both own the words."""
    shared = SNIP
    found, _ = edges.compute(KEY, "- " + shared, "",
                             [src(shared, node="src:ext:a"), src(shared, node="src:ext:b")], set())

    strong = [e for e in found if e.kind == "strong"]
    assert len(strong) <= 1, f"both pages were credited: {[e.node for e in strong]}"
