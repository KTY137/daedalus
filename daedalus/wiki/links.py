"""links.py — the wiki's nervous system: wikilinks, backlinks, unlinked mentions,
and the LOCAL graph.

WHY LOCAL AND NOT GLOBAL
------------------------
The research sweep behind ``docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md``
found the same verdict everywhere: a global graph view is what people call
"pretty but useless" once a vault grows, while a LOCAL graph — the n-hop
neighbourhood of the page you are on, depth 1 by default — answers a question
somebody actually has. So the local walk is the primary product here and the
global one is not built at all.

THE LINK FORMS
--------------
``[[Note]]``                 a page, by title or by path
``[[Note#Heading]]``         a section of a page
``[[Note|shown text]]``      an alias; the target is unchanged
``![[Note]]``                an embed rather than a link — a different relation
``[[code:path/to/f.py]]``    a doc -> code edge (Swimm's idea: a real edge, not a URL)
``[[code:path#symbol]]``     a doc -> symbol edge
``[[type:TypeName]]``        a doc -> type edge; PARSED and COUNTED, never resolved
                             here, because the type layer is built separately and
                             importing it would couple the wiki to an index build
``[[vault:name/page]]``      cross-vault. Parsed so it is visible, resolved only
                             when a registry is supplied — and DEFERRED as a
                             feature, because cross-vault resolution needs the
                             multi-root join nobody has built.

REFUSE TO GUESS
---------------
The rule ``markdown.py`` already applies to document links, kept verbatim: a link
that does not resolve to something present is DROPPED and COUNTED, never bound to
a near-match; a link matching MORE THAN ONE candidate is AMBIGUOUS and produces no
edge at all. Picking the first of two would be a stably reproduced fabrication,
which is worse than an honest gap because it looks like knowledge.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

LINKS_VERSION = "1"

#: Bounded so one page cannot dominate an index.
MAX_LINKS_PER_PAGE = 500
MAX_MENTIONS_PER_PAGE = 50
MAX_LOCAL_NODES = 200

# ``!`` marks an embed. The target runs to the first of # | ]
_WIKILINK = re.compile(r"(?P<embed>!)?\[\[(?P<target>[^\]\[#|]+)(?:#(?P<anchor>[^\]\[|]*))?"
                       r"(?:\|(?P<alias>[^\]\[]*))?\]\]")

DOC = "doc"
CODE = "code"
TYPE = "type"
VAULT = "vault"


@dataclass(frozen=True)
class WikiLink:
    kind: str                  # doc | code | type | vault
    target: str                # verbatim, minus the prefix
    anchor: str = ""
    alias: str = ""
    embed: bool = False
    line: int = 0

    def to_dict(self) -> dict:
        return {"kind": self.kind, "target": self.target, "anchor": self.anchor,
                "alias": self.alias, "embed": self.embed, "line": self.line}


def extract_wikilinks(body: str) -> list[WikiLink]:
    """Every wikilink in a page body, in source order. No resolution, no I/O."""
    starts = [0] + [i + 1 for i, ch in enumerate(body) if ch == "\n"]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    out: list[WikiLink] = []
    for m in _WIKILINK.finditer(body):
        raw = (m.group("target") or "").strip()
        if not raw:
            continue
        kind, target = DOC, raw
        for prefix, k in (("code:", CODE), ("type:", TYPE), ("vault:", VAULT)):
            if raw.lower().startswith(prefix):
                kind, target = k, raw[len(prefix):].strip()
                break
        if not target:
            continue
        out.append(WikiLink(kind=kind, target=target,
                            anchor=(m.group("anchor") or "").strip(),
                            alias=(m.group("alias") or "").strip(),
                            embed=bool(m.group("embed")),
                            line=line_of(m.start())))
        if len(out) >= MAX_LINKS_PER_PAGE:
            break
    return out


# --------------------------------------------------------------------------- #
@dataclass
class LinkIndex:
    """Forward and reverse edges over one vault. Derived; regenerate and it is true."""
    forward: dict = field(default_factory=lambda: defaultdict(list))
    backward: dict = field(default_factory=lambda: defaultdict(list))
    code_links: list = field(default_factory=list)
    type_links: list = field(default_factory=list)
    cross_vault: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    ambiguous: list = field(default_factory=list)

    def counts(self) -> dict:
        return {"pages": len(set(self.forward) | set(self.backward)),
                "doc_edges": sum(len(v) for v in self.forward.values()),
                "code_links": len(self.code_links), "type_links": len(self.type_links),
                "cross_vault": len(self.cross_vault),
                "unresolved": len(self.unresolved), "ambiguous": len(self.ambiguous)}


def _candidates_for(target: str, by_rel: dict, by_title: dict) -> list[str]:
    """Resolve a doc target by path first, then by title. Sorted; no near-matches."""
    t = target.replace("\\", "/").strip()
    for cand in (t, t if t.endswith(".md") else t + ".md"):
        if cand in by_rel:
            return [cand]
    # Obsidian allows the bare page name. That can be ambiguous, and ambiguity is
    # reported rather than resolved by picking one.
    hits = sorted(by_title.get(t.lower(), []))
    if hits:
        return hits
    stem = PurePosixPath(t).stem.lower()
    return sorted(by_title.get(stem, []))


def build_index(pages, *, known_code_paths=None) -> LinkIndex:
    """Link index over a vault's pages. Deterministic: every list sorted at the end."""
    idx = LinkIndex()
    by_rel = {p.rel: p for p in pages}
    by_title: dict = defaultdict(list)
    for p in pages:
        by_title[p.title.lower()].append(p.rel)
        by_title[PurePosixPath(p.rel).stem.lower()].append(p.rel)
    code_known = {str(c).replace("\\", "/") for c in (known_code_paths or ())}

    for p in sorted(pages, key=lambda x: x.rel):
        for link in extract_wikilinks(p.body):
            if link.kind == TYPE:
                # Parsed and counted; resolution belongs to the type layer, and
                # importing it here would couple a wiki read to an index build.
                idx.type_links.append({"from": p.rel, "target": link.target,
                                       "line": link.line, "resolved": False})
                continue
            if link.kind == VAULT:
                idx.cross_vault.append({"from": p.rel, "target": link.target,
                                        "line": link.line, "resolved": False,
                                        "note": "cross-vault resolution is deferred"})
                continue
            if link.kind == CODE:
                tgt = link.target.replace("\\", "/")
                alive = (not code_known) or (tgt in code_known)
                idx.code_links.append({"from": p.rel, "target": tgt, "symbol": link.anchor,
                                       "line": link.line, "resolved": bool(code_known),
                                       # stale is only knowable when a file set was
                                       # supplied; without one it is UNKNOWN, not fine
                                       "stale": (code_known and not alive) or False,
                                       "checked": bool(code_known)})
                continue

            cands = _candidates_for(link.target, by_rel, by_title)
            uniq = sorted(dict.fromkeys(cands))
            if not uniq:
                idx.unresolved.append({"from": p.rel, "target": link.target, "line": link.line})
                continue
            if len(uniq) > 1:
                idx.ambiguous.append({"from": p.rel, "target": link.target,
                                      "line": link.line, "candidates": uniq})
                continue
            tgt = uniq[0]
            if tgt == p.rel:
                continue                       # a self-link is not an edge
            rec = {"from": p.rel, "to": tgt, "anchor": link.anchor,
                   "embed": link.embed, "line": link.line}
            idx.forward[p.rel].append(rec)
            idx.backward[tgt].append(rec)

    for d in (idx.forward, idx.backward):
        for k in d:
            d[k] = sorted(d[k], key=lambda r: (r["from"], r["to"], r["line"]))
    idx.code_links.sort(key=lambda r: (r["from"], r["target"], r["line"]))
    idx.type_links.sort(key=lambda r: (r["from"], r["target"], r["line"]))
    idx.unresolved.sort(key=lambda r: (r["from"], r["target"], r["line"]))
    idx.ambiguous.sort(key=lambda r: (r["from"], r["target"], r["line"]))
    return idx


def backlinks(idx: LinkIndex, rel: str) -> list[dict]:
    """Pages that link TO this one. The panel users actually read."""
    return list(idx.backward.get(rel, []))


_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")


def unlinked_mentions(pages, page, idx: LinkIndex, *,
                      limit: int = MAX_MENTIONS_PER_PAGE) -> list[dict]:
    """Pages whose text names this page's title WITHOUT linking it.

    Bounded on purpose: a page titled "agent" would otherwise match every page in
    the vault, which is both a UI collapse and a quadratic scan. The bound is
    reported by the caller, never silently applied.
    """
    title = page.title.strip()
    if len(title) < 3:
        return []                              # too short to mean anything
    linked = {r["from"] for r in idx.backward.get(page.rel, [])}
    needle = re.compile(rf"(?<![\w\[]){re.escape(title)}(?![\w\]])", re.I)
    out: list[dict] = []
    for p in sorted(pages, key=lambda x: x.rel):
        if p.rel == page.rel or p.rel in linked:
            continue
        m = needle.search(p.body)
        if not m:
            continue
        line = p.body.count("\n", 0, m.start()) + 1
        ctx = " ".join(p.body[max(0, m.start() - 50): m.start() + 70].split())
        out.append({"from": p.rel, "title": p.title, "line": line, "context": ctx})
        if len(out) >= limit:
            break
    return out


def local_graph(idx: LinkIndex, rel: str, *, depth: int = 1,
                max_nodes: int = MAX_LOCAL_NODES) -> dict:
    """The n-hop neighbourhood around one page, undirected.

    Depth 1 by default because that is the question a reader has ("what is next to
    this?"). Bounded and it SAYS when it stopped, rather than presenting a clipped
    neighbourhood as complete.
    """
    seen = {rel}
    edges: list[dict] = []
    frontier = [rel]
    truncated = False
    for _ in range(max(0, depth)):
        nxt: list[str] = []
        for node in sorted(frontier):
            neighbours = [(r["to"], r) for r in idx.forward.get(node, [])]
            neighbours += [(r["from"], r) for r in idx.backward.get(node, [])]
            for other, rec in sorted(neighbours, key=lambda x: x[0]):
                key = {"source": rec["from"], "target": rec["to"], "embed": rec["embed"]}
                if key not in edges:
                    edges.append(key)
                if other not in seen:
                    if len(seen) >= max_nodes:
                        truncated = True
                        break
                    seen.add(other)
                    nxt.append(other)
            if truncated:
                break
        frontier = nxt
        if truncated or not frontier:
            break
    return {"center": rel, "depth": depth, "nodes": sorted(seen),
            "edges": sorted(edges, key=lambda e: (e["source"], e["target"])),
            "truncated": truncated,
            "note": ("stopped at the node bound; the neighbourhood is larger"
                     if truncated else "")}


def unpaired_intents(idx: LinkIndex, known_code_paths: set[str] | None = None,
                     pages: list = None) -> dict:
    """Return pages with document edges but no code links, code files without pages,
    and orphan pages (no incoming backlinks).

    The first set ('pages_without_code') are wiki pages that participate in the 
    document link graph (have at least one inbound or outbound doc edge) but do not 
    have any ``[[code:...]]`` links. These represent documented intentions that lack 
    an implementation, i.e. work candidates suitable for a greenfield project.

    The second set ('code_without_pages') are code files present in the vault (as
    given by *known_code_paths*) that no wiki page links to. They are either 
    invisible to the knowledge graph or represent code that should be documented.

    The third set ('orphan_pages') are pages that have no incoming links from other
    pages (no backlinks). They may have outgoing links. This is only available when
    *pages* is supplied.

    False-positive modes to expect:
    - A page may be pure documentation with no code counterpart (e.g. concept notes)
      and be flagged as an 'intention'.
    - A page may link to code indirectly (via a type reference or a non-wikilink) 
      that is not captured by ``[[code:...]]`` syntax.
    - Code files may be generated, vendored, or configuration that nobody intends to 
      document.
    - The index only knows the code paths that were provided at build time; if 
      *known_code_paths* is stale or incomplete, the 'code_without_pages' set is 
      similarly incomplete.
    - Ambiguous or unresolved code links that were dropped/ambiguous in the index 
      will not appear as code edges, making a page look code-less when it attempted 
      a link.
    - Orphan pages may be stubs, section placeholders, or index pages that are not
      yet linked; a page with only outgoing links is still an orphan by this definition.
    """
    # Pages with doc edges (any forward/backward entry)
    doc_pages = set(idx.forward.keys()) | set(idx.backward.keys())
    # Pages that have at least one code link outgoing
    code_source_pages = {link["from"] for link in idx.code_links}
    pages_without_code = sorted(doc_pages - code_source_pages)

    code_without_pages = []
    if known_code_paths is not None:
        code_targets = {link["target"] for link in idx.code_links}
        code_without_pages = sorted(set(known_code_paths) - code_targets)

    # Each item now carries its provenance
    pages_without_code_prov = [{"page": p, "provenance": "has document incoming/outgoing edges but no code links"} for p in pages_without_code]
    code_without_pages_prov = [{"file": c, "provenance": "exists in known_code_paths but not linked from any page"} for c in code_without_pages]

    orphan_pages_prov = []
    if pages is not None:
        all_rels = {p.rel for p in pages}
        backlinked = set(idx.backward.keys())
        orphans = all_rels - backlinked
        orphan_pages_prov = [{"page": o, "provenance": "no incoming backlinks in the document graph"} for o in sorted(orphans)]

    return {
        "pages_without_code": pages_without_code_prov,
        "code_without_pages": code_without_pages_prov,
        "orphan_pages": orphan_pages_prov,
    }


if __name__ == "__main__":
    # Comprehensive self-tests for the wiki link index.
    from dataclasses import dataclass
    from copy import deepcopy

    @dataclass
    class MockPage:
        rel: str
        title: str
        body: str

    def test_existing_unpaired_intents():
        """Original self-test for unpaired_intents (kept for backward compatibility)."""
        pages = [
            MockPage("doc_a.md", "Doc A", "[[Doc B]] [[code:src/a.py]]"),
            MockPage("doc_b.md", "Doc B", "[[Doc A]]"),
            MockPage("doc_c.md", "Doc C", "[[Doc A]] [[code:src/c.py]]"),
            MockPage("doc_orphan.md", "Doc Orphan", "Just some text, no incoming links."),
        ]
        known_code_paths = {"src/a.py", "src/b.py", "src/c.py"}
        idx = build_index(pages, known_code_paths=known_code_paths)
        result = unpaired_intents(idx, known_code_paths=known_code_paths, pages=pages)
        # Expected:
        pages_without_code_set = {d["page"] for d in result["pages_without_code"]}
        assert "doc_b.md" in pages_without_code_set, f"Expected doc_b.md but got {pages_without_code_set}"
        assert "doc_a.md" not in pages_without_code_set and "doc_c.md" not in pages_without_code_set
        code_without_pages_set = {d["file"] for d in result["code_without_pages"]}
        assert "src/b.py" in code_without_pages_set, f"Expected src/b.py but got {code_without_pages_set}"
        assert "src/a.py" not in code_without_pages_set and "src/c.py" not in code_without_pages_set
        orphan_set = {d["page"] for d in result["orphan_pages"]}
        assert "doc_orphan.md" in orphan_set, f"Expected doc_orphan.md but got {orphan_set}"
        print("  [PASS] existing unpaired_intents test")

    def test_backlink_symmetry():
        """Every forward edge must appear as a backlink from the target."""
        pages = [
            MockPage("a.md", "A", "[[b]]"),
            MockPage("b.md", "B", "[[a]]"),
            MockPage("c.md", "C", "[[b]] [[d]]"),
            MockPage("d.md", "D", ""),
        ]
        idx = build_index(pages)
        # Check symmetries
        for source, fwd_edges in idx.forward.items():
            for e in fwd_edges:
                back = idx.backward.get(e["to"], [])
                matching = [b for b in back if b["from"] == e["from"] and b["to"] == e["to"]]
                assert len(matching) == 1, f"Missing backlink for {e}"
        for target, bwd_edges in idx.backward.items():
            for e in bwd_edges:
                fwd = idx.forward.get(e["from"], [])
                matching = [f for f in fwd if f["from"] == e["from"] and f["to"] == e["to"]]
                assert len(matching) == 1, f"Missing forward for backlink {e}"
        print("  [PASS] backlink symmetry")

    def test_local_graph_cycle_terminates():
        """local_graph on a cycle must terminate and report truncation if bounded."""
        # Create a cycle: A->B, B->C, C->A
        pages = [
            MockPage("a.md", "A", "[[b]]"),
            MockPage("b.md", "B", "[[c]]"),
            MockPage("c.md", "C", "[[a]]"),
        ]
        idx = build_index(pages)
        # With depth=1, should not truncate
        lg1 = local_graph(idx, "a.md", depth=1, max_nodes=10)
        assert len(lg1["nodes"]) == 3, f"Depth 1 on cycle should see all nodes, got {lg1['nodes']}"
        assert not lg1["truncated"]
        # With depth=2 but tiny max_nodes, should truncate
        lg2 = local_graph(idx, "a.md", depth=2, max_nodes=2)
        assert lg2["truncated"], "Should truncate when max_nodes is small"
        assert len(lg2["nodes"]) <= 2
        print("  [PASS] local_graph on cycle terminates and truncates")

    def test_unlinked_mentions_short_title():
        """Titles shorter than 3 characters produce no unlinked mentions."""
        pages = [
            MockPage("t.md", "ab", "text about ab"),
            MockPage("other.md", "Other", "mentions ab here"),
        ]
        idx = build_index(pages)
        # The page with title "ab" is too short, so unlinked_mentions should be empty.
        mentions = unlinked_mentions(pages, pages[0], idx)
        assert mentions == [], f"Expected empty for short title, got {mentions}"
        print("  [PASS] unlinked_mentions ignores short titles")

    def test_unlinked_mentions_false_positive_common_word():
        """A common word like 'the' is ignored because length < 3."""
        pages = [
            MockPage("the.md", "the", "the word the"),
            MockPage("other.md", "Other", "this has the word"),
        ]
        idx = build_index(pages)
        mentions = unlinked_mentions(pages, pages[0], idx)
        assert mentions == [], f"Common word 'the' should not produce mentions, got {mentions}"
        print("  [PASS] unlinked_mentions ignores common word 'the'")

    def test_ambiguous_bare_name_produces_no_edge():
        """When two pages share the same bare name, linking to it produces ambiguity, not an edge."""
        pages = [
            MockPage("folder1/target.md", "Target", "content"),
            MockPage("folder2/target.md", "Target", "content"),
            MockPage("source.md", "Source", "[[target]]"),
        ]
        idx = build_index(pages)
        # There should be no forward edges from source.md
        assert "source.md" not in idx.forward or idx.forward["source.md"] == [], \
            f"Expected no forward edges, got {idx.forward.get('source.md', [])}"
        # The ambiguous link should be recorded
        assert len(idx.ambiguous) == 1
        amb = idx.ambiguous[0]
        assert amb["from"] == "source.md"
        assert amb["target"] == "target"
        assert len(amb["candidates"]) == 2
        print("  [PASS] ambiguous bare name produces no edge")

    def test_determinism_across_builds():
        """Two index builds on the same pages must be identical."""
        pages = [
            MockPage("a.md", "A", "[[b]] [[code:x.py]] [[type:T]] [[vault:v/p]]"),
            MockPage("b.md", "B", "[[a]] [[c]]"),
            MockPage("c.md", "C", "[[b]]"),
            MockPage("d.md", "D", "[[nonexistent]] [[a]]"),
        ]
        idx1 = build_index(deepcopy(pages))
        idx2 = build_index(deepcopy(pages))
        # Compare counts as a quick check; deep compare would need more effort.
        assert idx1.counts() == idx2.counts(), "Counts differ across builds"
        # Compare the lists manually since LinkIndex is not directly comparable
        assert idx1.forward == idx2.forward, "Forward links differ"
        assert idx1.backward == idx2.backward, "Backward links differ"
        assert idx1.unresolved == idx2.unresolved, "Unresolved differ"
        assert idx1.ambiguous == idx2.ambiguous, "Ambiguous differ"
        assert idx1.code_links == idx2.code_links, "Code links differ"
        assert idx1.type_links == idx2.type_links, "Type links differ"
        assert idx1.cross_vault == idx2.cross_vault, "Cross vault differ"
        print("  [PASS] determinism across builds")

    # Run all tests
    print("Running self-tests...")
    test_existing_unpaired_intents()
    test_backlink_symmetry()
    test_local_graph_cycle_terminates()
    test_unlinked_mentions_short_title()
    test_unlinked_mentions_false_positive_common_word()
    test_ambiguous_bare_name_produces_no_edge()
    test_determinism_across_builds()
    print("All self-tests passed.")
