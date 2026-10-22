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


def test_user_turn_still_produces_no_edge():
    """0/200 in the eval: dictated text is not an origin, so it gets no edge even when it overlaps."""
    page = src("Handbook excerpt: " + SNIP + " ...", node="src:ext:page")
    user = src("Heads up, I pasted the handbook section: " + SNIP, cls="user", node="src:user:u1")

    found, _ = edges.compute(KEY, "- " + SNIP, "", [user, page], set())

    assert not [e for e in found if e.node.startswith("src:user:")], "a user turn became a source"


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
