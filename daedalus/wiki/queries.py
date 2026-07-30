"""
Queries over wiki pages and their document / code edges.

Each query returns a list of (entity, provenance) pairs.  Provenance is a
human-readable string that states *which edge sets* produced the result, so
a reviewer or automated tool can trace back why something was flagged.

False-positive modes expected:

- ``find_documented_but_unimplemented``:  A page may have document edges
  but its implementation lives in a different repository, or in code
  generated outside the build process that produced the code edges.  The
  wiki can also contain historical intention pages whose implementation
  was removed without pruning the document edges.
- ``find_undocumented_code``:  The ``all_symbols`` set may include
  test helpers, deprecated functions, or plumbing that is intentionally
  undocumented.  Without filtering, the query treats every code symbol as
  needing a wiki page, which is rarely true; an external filter is
  necessary for low-noise results.
- ``find_orphan_pages``:  A page with zero edges is not necessarily dead
  content; it could be reachable from navigation (which is not modelled as
  document edges), or it could be a stand-alone page such as a style guide
  that is valid on its own.

Each query remains deterministic: two runs on identical inputs produce
byte-for-byte identical output.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple


def find_documented_but_unimplemented(
    pages: Set[str],
    doc_edges: Dict[str, Set[str]],   # page -> set of doc references
    code_edges: Dict[str, Set[str]],  # page -> set of code references
) -> List[Dict[str, Any]]:
    """
    Return pages that have at least one document edge and no code edges.

    These are *documented intentions* that have never been linked to code;
    they are good candidates for implementation work that does not require
    poring over repository history.

    Provenance states the number of document edges on the page.
    """
    results: List[Dict[str, Any]] = []
    for page in sorted(pages):
        has_doc = page in doc_edges and len(doc_edges[page]) > 0
        has_code = page in code_edges and len(code_edges[page]) > 0
        if has_doc and not has_code:
            results.append({
                "entity": page,
                "provenance": f"page {page} has document edges but no code edges "
                              f"({len(doc_edges[page])} document edge(s))",
            })
    return results


def find_undocumented_code(
    all_symbols: Set[str],
    code_edges: Dict[str, Set[str]],
    pages: Set[str],
) -> List[Dict[str, Any]]:
    """
    Return code symbols that are not referenced by any code edge
    (i.e. they have no wiki page that claims them).

    *all_symbols* is the set of known code symbols (e.g. function FQNs);
    it must be provided by an external analyser because the wiki graph
    alone cannot know which symbols exist in the first place.

    Provenance states that the symbol appears in zero pages' code edges.
    """
    documented: Set[str] = set()
    for page in pages:
        if page in code_edges:
            documented.update(code_edges[page])
    undocumented = all_symbols - documented
    return [
        {
            "entity": sym,
            "provenance": f"symbol {sym} is not referenced by any code edge",
        }
        for sym in sorted(undocumented)
    ]


def find_orphan_pages(
    pages: Set[str],
    doc_edges: Dict[str, Set[str]],
    code_edges: Dict[str, Set[str]],
) -> List[Dict[str, Any]]:
    """
    Return pages that have zero document edges AND zero code edges.

    A page with no connections of either kind is an orphan; it is unlikely
    to be reached through the documented surface of the project.

    Provenance states that the page has no edges of either type.
    """
    results: List[Dict[str, Any]] = []
    for page in sorted(pages):
        has_doc = page in doc_edges and len(doc_edges[page]) > 0
        has_code = page in code_edges and len(code_edges[page]) > 0
        if not has_doc and not has_code:
            results.append({
                "entity": page,
                "provenance": f"page {page} has no document edges and no code edges",
            })
    return results


def test_find_documented_but_unimplemented_false_positives():
    """
    REFUTATION: The core claim that a page with document edges and no code edges
    identifies a documented-but-unimplemented feature is too broad.
    Concrete counterexamples:
    - A design note (page "Design Notes") with doc edges to other notes but no code edges.
    - An ADR ("ADR-001: Use PostgreSQL") referencing other decision pages.
    - A glossary ("Glossary") linking to term pages.
    - A meeting record ("Meeting-2025-01-01") with links to attendees' pages.
    All these are valid wiki content but not "unimplemented features".
    The signal as currently implemented will flag them as such, leading to false positives.
    To be honest, the query needs a qualifier (e.g., filtering by page category or requiring
    certain content patterns) or the caller must accept that it conflates these page types.
    """
    pages = {"FeatureX", "Design Notes", "ADR-001", "Glossary", "Meeting-2025-01-01"}
    doc_edges = {
        "FeatureX": {"req-1"},
        "Design Notes": {"Note1"},
        "ADR-001": {"Decision"},
        "Glossary": {"TermA"},
        "Meeting-2025-01-01": {"Attendee"},
    }
    code_edges = {
        "FeatureX": {"some_code"},
    }
    result = find_documented_but_unimplemented(pages, doc_edges, code_edges)
    flagged = {entry["entity"] for entry in result}
    # The defect: these non-feature pages are returned
    # The test will fail, showing the implementation is over-broad.
    assert "Design Notes" not in flagged, "Design notes are not unimplemented features"
    assert "ADR-001" not in flagged, "ADRs are not unimplemented features"
    assert "Glossary" not in flagged, "Glossaries are not unimplemented features"
    assert "Meeting-2025-01-01" not in flagged, "Meeting records are not unimplemented features"
    # FeatureX is actually implemented, so it should not be flagged either (it isn't, so this passes)
    assert "FeatureX" not in flagged, "FeatureX has code edges; it's implemented"
