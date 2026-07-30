# tests/test_wiki_links.py

"""
Tests for finding unmatched wiki/code links.

The function under test is `get_unmatched_links(doc_links, code_links)`.
It returns a tuple (unimplemented_pages, orphaned_code) where:
- unimplemented_pages: set of wiki pages that have document edges but are never referenced by any code entity.
- orphaned_code: set of code identifiers that reference at least one wiki page that does not exist in the document edges.

Expected false-positive modes:
- Documented but unimplemented: some wiki pages document concepts that have no direct code counterpart (e.g., architectural overviews). These will be flagged as unimplemented intentions, but may be intentional.
- Code with no page: code may reference wiki pages for future documentation or external resources; these missing pages may be planned but not yet created.
- Index incompleteness: the wiki_code_links index may fail to capture all references due to indirection, dynamic linking, or naming variations (e.g., aliases). This can cause real links to be missed, leading to false positives.
- Naming mismatches: code references may use abbreviated or alternative names that do not exactly match wiki page titles, causing false orphaned code.
"""

import pytest


@pytest.fixture
def empty_links():
    """Both link directions empty."""
    return (dict(), dict())


@pytest.fixture
def perfect_links():
    """Every page is referenced, every reference points to an existing page."""
    doc_links = {
        "Page1": {"func_a", "func_b"},
        "Page2": {"func_c"},
    }
    code_links = {
        "func_a": {"Page1"},
        "func_b": {"Page1"},
        "func_c": {"Page2"},
    }
    return (doc_links, code_links)


@pytest.fixture
def mixed_links():
    """Contains unimplemented pages and orphaned code references."""
    doc_links = {
        "PageA": {"func_x"},          # referenced by func_x, ok
        "PageB": {"func_y"},          # not referenced at all -> unimplemented
        "PageC": {"func_z"},          # referenced by func_z, ok
    }
    code_links = {
        "func_x": {"PageA"},          # ok
        "func_y": set(),              # references nothing (or no doc? still might be unimplemented if PageB isn't referenced? No, func_y doesn't ref anything)
        "func_z": {"PageC"},          # ok
        "func_w": {"PageMissing"},    # references non-existing page -> orphaned
    }
    return (doc_links, code_links)


@pytest.mark.parametrize("fixture_name, expected_unimplemented, expected_orphaned", [
    ("empty_links", set(), set()),
    ("perfect_links", set(), set()),
    ("mixed_links", {"PageB"}, {"func_w"}),
])
def test_get_unmatched_links(request, fixture_name, expected_unimplemented, expected_orphaned):
    from daedalus.wiki.links import get_unmatched_links
    doc_links, code_links = request.getfixturevalue(fixture_name)
    unimplemented, orphaned = get_unmatched_links(doc_links, code_links)
    assert unimplemented == expected_unimplemented
    assert orphaned == expected_orphaned


def test_page_with_no_doc_edges_but_referenced_is_not_unimplemented():
    """A page that is only referenced (value in code_links) but has no doc_links entry
    is missing, but the code should be flagged as orphaned, not the page as unimplemented."""
    from daedalus.wiki.links import get_unmatched_links
    doc_links = {"ExistingPage": {"func_a"}}
    code_links = {"func_a": {"ExistingPage"}, "func_b": {"MissingPage"}}
    unimplemented, orphaned = get_unmatched_links(doc_links, code_links)
    assert unimplemented == set()
    assert orphaned == {"func_b"}


def test_code_referencing_existing_and_missing_pages_is_orphaned():
    """A code identifier that points to at least one missing page should be considered orphaned."""
    from daedalus.wiki.links import get_unmatched_links
    doc_links = {"Page1": {"func_a"}}
    code_links = {"func_a": {"Page1", "MissingPage"}}
    unimplemented, orphaned = get_unmatched_links(doc_links, code_links)
    assert unimplemented == set()
    assert orphaned == {"func_a"}


def test_page_documented_but_no_code_edges_alone_is_unimplemented():
    """If a page is present in doc_links but never appears as a value in code_links,
    it is unimplemented."""
    from daedalus.wiki.links import get_unmatched_links
    doc_links = {"PageOnly": {"func_a"}}
    code_links = {}
    unimplemented, orphaned = get_unmatched_links(doc_links, code_links)
    assert unimplemented == {"PageOnly"}
    assert orphaned == set()


# ----------------------------------------------------------------------
# Tests for wiki link index properties
# ----------------------------------------------------------------------

def test_backlink_symmetry_with_forward_links():
    """
    The index must maintain backlink symmetry: if A lists B as a forward link,
    then B must list A as a backlink.  This ensures the graph is consistent.
    """
    from daedalus.wiki.links import build_wiki_link_index

    doc_links = {
        "PageA": {"func_x"},
        "PageB": {"func_y"},
    }
    code_links = {
        "func_x": {"PageA"},
        "func_y": {"PageB"},
    }
    index = build_wiki_link_index(doc_links, code_links)

    for node in index.all_nodes():
        for target in index.forward_links(node):
            assert node in index.backlinks(target), (
                f"Backlink symmetry broken: {node} -> {target}"
            )


def test_local_graph_on_cycle_terminates_and_truncates():
    """
    When a local graph contains a cycle, the traversal must terminate
    (avoid infinite loops) and signal that it truncated the results.
    """
    from daedalus.wiki.links import WikiLinkIndex

    # Build a small index with a cycle: A -> B -> C -> A
    index = WikiLinkIndex()
    index.add_edge("A", "B")
    index.add_edge("B", "C")
    index.add_edge("C", "A")

    subgraph, truncated = index.local_graph("A", max_depth=5)
    assert truncated, "Expected local_graph to report truncation on a cycle"
    # Ensure it didn't hang (the test itself terminates)


def test_unlinked_mentions_ignore_common_words():
    """
    The `unlinked_mentions` function must not flag common words
    (like 'the', 'and', 'for') as potential missing links; these are
    false positives that clutter the output.
    """
    from daedalus.wiki.links import unlinked_mentions

    text = "Check the index for and with a quick run."
    known_links = {"index", "run"}  # only real link-worthy terms
    mentions = unlinked_mentions(text, known_links, stopwords=True)
    common = {"the", "and", "for", "a"}
    false_positives = common & set(mentions)
    assert not false_positives, f"Common words incorrectly flagged: {false_positives}"


def test_ambiguous_bare_name_produces_no_edge():
    """
    When a bare name (without explicit disambiguation) matches multiple
    possible entities, the indexer must not create an edge, because that
    would introduce an unreliable link.
    """
    from daedalus.wiki.links import build_wiki_link_index

    doc_links = {}  # minimal
    code_links = {} # minimal
    # Simulate an ambiguous name scenario: a name that maps to two possible pages
    # The builder should either skip it or record it with no edge.
    index = build_wiki_link_index(doc_links, code_links, ambiguous_names={"Java": ["Java_(island)", "Java_(programming_language)"]})
    edges = index.edges_from("Java")
    assert edges == set(), "Ambiguous bare name 'Java' should produce no edge"


def test_determinism_across_two_builds():
    """
    Building the wiki link index twice with the same inputs must yield
    identical results.  Non-deterministic output would break reproducibility.
    """
    from daedalus.wiki.links import build_wiki_link_index

    doc_links = {"PageA": {"func_x"}, "PageB": {"func_y"}}
    code_links = {"func_x": {"PageA"}, "func_y": {"PageB"}}

    index1 = build_wiki_link_index(doc_links, code_links)
    index2 = build_wiki_link_index(doc_links, code_links)

    # Compare serialized forms to ensure deterministic output
    assert index1.as_dict() == index2.as_dict(), "Two builds of the same input differ"


# ----------------------------------------------------------------------
# Additional tests to catch stub/empty implementations that would
# otherwise let the above tests pass without actually exercising the
# feature.
# ----------------------------------------------------------------------

def test_built_index_contains_expected_nodes():
    """An index built from actual data must contain the nodes that were provided."""
    from daedalus.wiki.links import build_wiki_link_index

    doc_links = {
        "PageA": {"func_x"},
        "PageB": {"func_y"},
    }
    code_links = {
        "func_x": {"PageA"},
        "func_y": {"PageB"},
    }
    index = build_wiki_link_index(doc_links, code_links)
    nodes = index.all_nodes()
    assert "PageA" in nodes
    assert "func_x" in nodes
    assert "PageB" in nodes
    assert "func_y" in nodes


def test_cycle_local_graph_returns_start_node():
    """
    A local_graph traversal on a non-empty index must include the start
    node in the returned subgraph, even when the max_depth is reached
    and the result set is truncated.
    """
    from daedalus.wiki.links import WikiLinkIndex

    index = WikiLinkIndex()
    index.add_edge("A", "B")
    index.add_edge("B", "C")
    index.add_edge("C", "A")
    subgraph, truncated = index.local_graph("A", max_depth=5)
    assert "A" in subgraph, "local_graph must include the starting node"


def test_unlinked_mentions_detects_unknown_terms():
    """unlinked_mentions must return words that are not in known_links, not just filter stopwords."""
    from daedalus.wiki.links import unlinked_mentions

    text = "unique_term known_term"
    known_links = {"known_term"}
    mentions = unlinked_mentions(text, known_links, stopwords=False)
    assert "unique_term" in mentions, "unknown term should appear in mentions"
    assert "known_term" not in mentions, "known term should not appear"


def test_unambiguous_name_produces_edge():
    """A non-ambiguous name must create edges in the index, unlike the ambiguous case."""
    from daedalus.wiki.links import build_wiki_link_index

    doc_links = {"PageX": {"func_y"}}
    code_links = {"func_y": {"PageX"}}
    index = build_wiki_link_index(doc_links, code_links)
    edges = index.edges_from("PageX")
    assert len(edges) > 0, "unambiguous name should have outgoing edges"


def test_index_as_dict_is_not_empty():
    """When there are links, the serialised form must not be empty."""
    from daedalus.wiki.links import build_wiki_link_index

    doc_links = {"PageA": {"func_x"}}
    code_links = {"func_x": {"PageA"}}
    index = build_wiki_link_index(doc_links, code_links)
    d = index.as_dict()
    assert d, "as_dict() should not be empty when there are links"
