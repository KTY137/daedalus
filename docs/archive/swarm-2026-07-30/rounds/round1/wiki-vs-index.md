# Claims about `wiki-vs-index.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] If resolution logic is duplicated, a bug fix in one place may be missed in the other, leading to incorrect links in diagnostic outputs (local graph vs. document_links).
2. [risk] The index's wiki gate (DAEDALUS_INDEX_WIKI) suggests a separate code path that may not fully replicate links.py's deterministic sort, bounds, and edge types.
3. [risk] Link resolution rules (e.g., _candidates_for in links.py) may diverge between wiki and index, causing inconsistent edge sets for the same content.
4. [todo] Decide which component owns resolutio: preferably wiki layer exports a reusable LinkIndex builder, and index.py calls it when documents+wiki flags are on.
5. [todo] Verify that type: and vault: link handling is consistent across both; currently links.py just counts them, but index may attempt resolution.
6. [todo] Check that ambiguous/unresolved reporting is uniform; links.py reports, but index's document_links may silently drop.
7. [todo] Locate markdown.knowledge_links or equivalent in structcore/markdown.py and compare with wiki/links.py build_index.