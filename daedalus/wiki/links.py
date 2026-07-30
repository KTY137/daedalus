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
