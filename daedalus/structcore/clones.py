# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Clone detection — the dominant AI-decay signal, generalized to any language.

Two complementary strategies (both generalize ``codemap.py``):

  * ``unit_clusters`` — precise, function/method level. Normalizes each unit
    (strip comments/docstrings/whitespace) and SHA1-fingerprints it; identical
    fingerprints across >=2 sites are a clone cluster. Catches Type-1/2 exact
    and renamed-literal clones. Needs units from ``parse.extract_units`` (Python
    always; other languages when tree-sitter is installed).
  * ``window_clusters`` — universal, needs no parser. Slides an N-line window of
    normalized source across every file and finds identical runs shared by >=2
    files. Catches copy-paste across files in ANY language/text. This is
    ``codemap.analyze_qml`` generalized to every language.

Every cluster is safety-annotated: if any site lives in a SAFETY-CLASS path it is
flagged ``do_not_collapse`` (the HV-triplication lesson) and never recommended
for merge.
"""
from __future__ import annotations

import hashlib
import io
import keyword
import re
import tokenize
from collections import Counter, defaultdict

from .languages import LanguageSpec
from .parse import CodeUnit

_WS = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Normalization + fingerprint                                                  #
# --------------------------------------------------------------------------- #
def normalize_source(source: str, spec: LanguageSpec | None) -> str:
    """Strip comments/docstrings/whitespace so byte-copies with cosmetic
    differences hash the same. Python uses the exact ``tokenize`` path from
    codemap; other languages use a comment-aware lexical strip."""
    if spec is not None and spec.name == "python":
        return _normalize_python(source)
    return _normalize_generic(source, spec)


def _normalize_python(source: str) -> str:
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                            tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
                continue
            if tok.type == tokenize.STRING and tok.string[:3] in ('"""', "'''"):
                continue  # drop block docstrings; keep inline literals
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        return _WS.sub(" ", source).strip()
    return " ".join(out)


def _strip_comments_generic(source: str, spec: LanguageSpec | None) -> str:
    """Comment-stripped source, one significant line per line (no whitespace
    collapse) — the shared substrate for both the lexical normalizer and the
    abstract tokenizer, so they see identical, comment-free text.

    STRING-LITERAL AWARE, and that is load-bearing rather than a nicety. The
    previous implementation searched raw text for comment markers, so a marker
    appearing INSIDE a string literal silently deleted real code and made
    different functions hash identically — i.e. it FABRICATED exact clones,
    which is this engine's worst failure mode. Two confirmed cases:

        send("SOUR:VOLT // 500");   ->   send("SOUR:VOLT
        send("SOUR:VOLT // 50");    ->   send("SOUR:VOLT     (identical!)

    two different bias voltages reported as the same code; and a ``/*`` inside a
    string, where the old block regex ran with ``re.S`` and swallowed everything
    up to the next ``*/`` — deleting whole function bodies and merging unrelated
    functions into one cluster.

    Single left-to-right pass, because the three states are mutually exclusive:
    inside a string, comment markers are text; outside one, a quote opens a
    string. Which quotes open a string is per-language (``spec.string_delims``):
    Rust's ``'a`` is a lifetime, not a literal, and consuming to the next ``'``
    would eat the code the old version was already eating.

    Unterminated literals stop at end-of-line rather than running to EOF, so a
    stray quote degrades one line instead of the rest of the file.
    """
    blocks = tuple(spec.block_comment) if spec else ()
    markers = tuple(spec.line_comment) if spec else ("//", "#")
    quotes = tuple(spec.string_delims) if spec else ('"', "'")

    out: list[str] = []
    line: list[str] = []
    i, n = 0, len(source)

    while i < n:
        ch = source[i]

        if ch in quotes:
            # Copy the literal through verbatim: its contents are code, and the
            # abstract tokenizer maps it to STR later anyway.
            line.append(ch)
            i += 1
            while i < n:
                c = source[i]
                if c == "\\" and i + 1 < n:      # \" does not close the literal
                    line.append(c)
                    line.append(source[i + 1])
                    i += 2
                    continue
                if c == "\n":                    # unterminated: bail at EOL
                    break
                line.append(c)
                i += 1
                if c == ch:
                    break
            continue

        hit = False
        for open_, close_ in blocks:
            if source.startswith(open_, i):
                end = source.find(close_, i + len(open_))
                i = n if end == -1 else end + len(close_)
                line.append(" ")                 # keep tokens either side apart
                hit = True
                break
        if hit:
            continue

        for m in markers:
            if source.startswith(m, i):
                nl = source.find("\n", i)
                i = n if nl == -1 else nl
                hit = True
                break
        if hit:
            continue

        if ch == "\n":
            s = "".join(line).strip()
            if s:
                out.append(s)
            line = []
            i += 1
            continue

        line.append(ch)
        i += 1

    s = "".join(line).strip()
    if s:
        out.append(s)
    return "\n".join(out)


def _normalize_generic(source: str, spec: LanguageSpec | None) -> str:
    return _WS.sub(" ", _strip_comments_generic(source, spec).replace("\n", " ")).strip()


def fingerprint(source: str, spec: LanguageSpec | None) -> str:
    return hashlib.sha1(normalize_source(source, spec).encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Abstract normalization (Type-2 / renamed) + token bags (Type-3 / near-miss)  #
#                                                                              #
# Where ``normalize_source`` preserves identifiers/literals (so only cosmetic  #
# differences hash the same -> Type-1), ``abstract_normalize`` erases them:    #
# every identifier -> ``ID``, number -> ``NUM``, string -> ``STR``, keeping    #
# keywords/operators/structure. Two functions that differ ONLY by renamed      #
# variables/constants therefore produce the same abstract fingerprint -> the   #
# Type-2 signal. The same abstracted token stream, as a multiset, is the       #
# Type-3 (near-miss) signal via SourcererCC-style overlap.                     #
# --------------------------------------------------------------------------- #

# A small, cross-language keyword set kept verbatim in the GENERIC path so the
# abstraction retains control-flow structure (an ``if`` must not look like a
# ``while``). The Python path uses the exact ``keyword`` module instead. This is
# best-effort for non-Python languages (documented) — precision lives in Python.
_GENERIC_KEYWORDS = frozenset({
    "if", "else", "elif", "for", "while", "do", "switch", "case", "default",
    "break", "continue", "return", "goto", "try", "catch", "except", "finally",
    "throw", "throws", "raise", "match", "when", "def", "fn", "func", "function",
    "class", "struct", "enum", "interface", "trait", "impl", "namespace",
    "public", "private", "protected", "static", "final", "const", "let", "var",
    "new", "delete", "import", "from", "use", "package", "module", "export",
    "async", "await", "yield", "in", "of", "is", "as", "and", "or", "not",
    "true", "false", "null", "nil", "none", "void", "self", "this", "super",
})

# One master token pattern: string | number | identifier | single operator char.
_GEN_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'          # double-quoted string
    r"|'(?:\\.|[^'\\])*'"         # single-quoted string
    r"|`(?:\\.|[^`\\])*`"         # backtick / template string
    r"|\d[\w.]*"                  # number-ish (ints, floats, hex, 1_000)
    r"|[A-Za-z_]\w*"              # identifier / keyword
    r"|[^\sA-Za-z0-9_]"          # a single operator / punctuation char
)


def _python_abstract_tokens(source: str) -> list[str] | None:
    """Abstract token stream via the stdlib ``tokenize`` lexer (precise). NAME
    that isn't a keyword -> ID; NUMBER -> NUM; STRING -> STR (block docstrings
    dropped, matching ``normalize_source``); keywords + operators kept verbatim.
    Returns None on a tokenizer error so the caller can fall back to generic."""
    out: list[str] = []
    _str_types = {tokenize.STRING}
    for _name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):  # py3.12+
        _t = getattr(tokenize, _name, None)
        if _t is not None:
            _str_types.add(_t)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            t = tok.type
            if t in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                     tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
                     tokenize.ENDMARKER):
                continue
            if t == tokenize.STRING and tok.string[:3] in ('"""', "'''"):
                continue  # drop block docstrings, as normalize_source does
            if t in _str_types:
                out.append("STR")
            elif t == tokenize.NUMBER:
                out.append("NUM")
            elif t == tokenize.NAME:
                out.append(tok.string if keyword.iskeyword(tok.string) else "ID")
            elif t == tokenize.OP:
                out.append(tok.string)
            # any remaining token kinds are structurally irrelevant -> skip
    except (tokenize.TokenError, IndentationError):
        return None
    return out


def _generic_abstract_tokens(source: str, spec: LanguageSpec | None) -> list[str]:
    """Best-effort abstraction for non-Python languages: strip comments, then
    map each lexical token to ID / NUM / STR / <keyword> / <operator-char>."""
    cleaned = _strip_comments_generic(source, spec)
    out: list[str] = []
    for m in _GEN_TOKEN.finditer(cleaned):
        tok = m.group(0)
        c0 = tok[0]
        if c0 in "\"'`":
            out.append("STR")
        elif c0.isdigit():
            out.append("NUM")
        elif c0 == "_" or c0.isalpha():
            out.append(tok if tok in _GENERIC_KEYWORDS else "ID")
        else:
            out.append(tok)
    return out


def _abstract_tokens(source: str, spec: LanguageSpec | None) -> list[str]:
    if spec is not None and spec.name == "python":
        toks = _python_abstract_tokens(source)
        if toks is not None:
            return toks
    return _generic_abstract_tokens(source, spec)


def abstract_normalize(source: str, spec: LanguageSpec | None) -> str:
    """Structure-preserving abstraction: identifiers->ID, numbers->NUM,
    strings->STR, keywords/operators kept. Two renamed-but-otherwise-identical
    units share this string exactly (the Type-2 signal)."""
    return " ".join(_abstract_tokens(source, spec))


def _fingerprint_of_tokens(tokens: list[str]) -> str:
    """The Type-2 fingerprint, computed from an ALREADY-abstracted token list.

    Exists so a caller that needs both the token bag and the fingerprint for the
    same unit can abstract once and derive both, instead of tokenizing the same
    string twice (see ``near_clusters``). ``abstract_fingerprint`` delegates here
    so there is exactly ONE definition of the fingerprint -- deriving it in two
    places would let the near-miss pass and the renamed pass silently disagree
    about what a Type-2 match is.
    """
    return hashlib.sha1(" ".join(tokens).encode("utf-8")).hexdigest()[:12]


def abstract_fingerprint(source: str, spec: LanguageSpec | None) -> str:
    return _fingerprint_of_tokens(_abstract_tokens(source, spec))


def token_bag(source: str, spec: LanguageSpec | None) -> Counter:
    """Multiset of ABSTRACTED tokens — the SourcererCC bag used for near-miss
    (Type-3) overlap. Abstracted (not raw) so a near-copy with renamed locals
    still overlaps heavily."""
    return Counter(_abstract_tokens(source, spec))


class CloneMemo:
    """Per-unit derived fingerprints, computed once and shared by all three
    clone passes.

    WHY: the passes are independent functions over the SAME unit list, and each
    re-derived what a previous one had already computed. ``unit_clusters``
    computes the exact fingerprint; ``renamed_clusters`` computed that exact
    fingerprint AGAIN (it needs it to exclude pure Type-1 clusters) plus the
    abstract one; ``near_clusters`` then derived the abstract one a third time.
    Normalization and abstraction are the two most expensive operations in the
    scan, so this was the dominant redundancy.

    ONLY the two 12-char fingerprints are cached, never the token lists. The
    lists are the memory-heavy part -- ``all_units`` already retains full source
    text at ~22.5x source bytes -- and they are needed only *within*
    ``near_clusters``, which derives its bag and its fingerprint from a single
    tokenization.

    Each entry holds a reference to its unit alongside the value, so an ``id()``
    key can never be recycled onto a different object while the memo is alive.
    Scope one memo to one ``build_index`` call and drop it after: a module-level
    cache would leak across scans.
    """

    __slots__ = ("_spec_by_lang", "_exact", "_abstract")

    def __init__(self, spec_by_lang: dict):
        self._spec_by_lang = spec_by_lang
        self._exact: dict[int, tuple] = {}
        self._abstract: dict[int, tuple] = {}

    def _spec(self, u: CodeUnit) -> LanguageSpec | None:
        return self._spec_by_lang.get(u.language)

    def exact_fp(self, u: CodeUnit) -> str:
        hit = self._exact.get(id(u))
        if hit is None:
            hit = (u, fingerprint(u.source, self._spec(u)))
            self._exact[id(u)] = hit
        return hit[1]

    def abstract_fp(self, u: CodeUnit) -> str:
        hit = self._abstract.get(id(u))
        if hit is None:
            hit = (u, abstract_fingerprint(u.source, self._spec(u)))
            self._abstract[id(u)] = hit
        return hit[1]

    def put_abstract_fp(self, u: CodeUnit, fp: str) -> None:
        """Donate a fingerprint derived from tokens the caller already had.

        ``near_clusters`` must tokenize anyway to build its bag, so it gets the
        abstract fingerprint for free and hands it back rather than leaving a
        later pass to re-abstract the same source.
        """
        if id(u) not in self._abstract:
            self._abstract[id(u)] = (u, fp)



# --------------------------------------------------------------------------- #
# Unit-level clusters (precise)                                                 #
# --------------------------------------------------------------------------- #
def unit_clusters(units: list[CodeUnit], spec_by_lang: dict, root=None,
                  min_loc: int = 4, memo: "CloneMemo | None" = None) -> list[dict]:
    # memo=None keeps every standalone caller (tests, the CLI, a single pass
    # called on its own) working exactly as before -- it just gets a private
    # memo instead of a shared one.
    memo = memo or CloneMemo(spec_by_lang)
    by_print: dict[str, list[CodeUnit]] = defaultdict(list)
    for u in units:
        if u.loc < min_loc:
            continue
        by_print[memo.exact_fp(u)].append(u)

    clusters = []
    for fp, group in by_print.items():
        if len(group) < 2:
            continue
        sites = [{"module": u.module, "name": u.name, "line": u.line, "loc": u.loc}
                 for u in group]
        clusters.append({
            "fingerprint": fp,
            "kind": "unit",
            "language": group[0].language,
            "count": len(group),
            "loc": group[0].loc,
            "name": group[0].name,
            "sites": sites,
            **_safety([u.module for u in group], root),
        })
    clusters.sort(key=lambda c: c["count"] * c["loc"], reverse=True)
    return clusters


# --------------------------------------------------------------------------- #
# Window-level clusters (universal, no parser)                                 #
# --------------------------------------------------------------------------- #
def window_runs(text: str, spec: LanguageSpec | None,
                run_len: int = 6, min_line_len: int = 3) -> list[str]:
    """Distinct normalized ``run_len``-line run hashes for ONE file, in
    first-encounter order.

    Split out of ``window_clusters`` so it can run in a worker process: this is
    the per-file, embarrassingly-parallel half. The ORDER of the returned list
    is load-bearing — the caller replays it into ``run_owners``, whose insertion
    order decides the tie-break order of the final (stable-sorted) cluster list.
    Returning a set here would make the output nondeterministic.
    """
    markers = spec.line_comment if spec else ("//", "#")
    norm = []
    for raw in text.splitlines():
        line = raw.strip()
        if any(line.startswith(m) for m in markers):
            continue
        if len(line) > min_line_len:
            norm.append(line)
    seen_here: set[str] = set()
    out: list[str] = []
    for i in range(max(0, len(norm) - run_len)):
        h = hashlib.sha1("\n".join(norm[i: i + run_len]).encode("utf-8")).hexdigest()[:12]
        if h not in seen_here:
            seen_here.add(h)
            out.append(h)
    return out


def window_clusters_from_runs(runs_by_file: list[tuple[str, list[str]]],
                              run_len: int = 6, root=None) -> list[dict]:
    """Cross-file half of the window pass, over precomputed per-file run hashes.

    ``runs_by_file`` must be in the original file order and each run list in
    first-encounter order (see ``window_runs``) — that reproduces exactly the
    insertion sequence the single-pass implementation produced.
    """
    run_owners: dict[str, set[str]] = defaultdict(set)
    for rel, runs in runs_by_file:
        for h in runs:
            run_owners[h].add(rel)

    by_fileset: dict[frozenset, int] = defaultdict(int)
    for fs in run_owners.values():
        if len(fs) >= 2:
            by_fileset[frozenset(fs)] += 1

    clusters = []
    for fset, n in by_fileset.items():
        paths = sorted(fset)
        clusters.append({
            "kind": "window", "files": paths, "shared_runs": n, "run_len": run_len,
            **_safety(paths, root),
        })
    clusters.sort(key=lambda c: (c["shared_runs"], len(c["files"])), reverse=True)
    return clusters


def window_clusters(files: list[tuple[str, str, LanguageSpec | None]],
                    run_len: int = 6, min_line_len: int = 3, root=None) -> list[dict]:
    """``files`` = [(rel_path, text, spec)]. Cross-file identical normalized runs,
    grouped by the set of files that share them (A,B share N runs).

    Now a composition of the per-file (``window_runs``) and cross-file
    (``window_clusters_from_runs``) halves; behaviour is unchanged.
    """
    return window_clusters_from_runs(
        [(rel, window_runs(text, spec, run_len, min_line_len)) for rel, text, spec in files],
        run_len=run_len, root=root)


# --------------------------------------------------------------------------- #
# Renamed clusters (Type-2, precise) — same structure, different names          #
# --------------------------------------------------------------------------- #
def renamed_clusters(units: list[CodeUnit], spec_by_lang: dict, root=None,
                     min_loc: int = 4, memo: "CloneMemo | None" = None) -> list[dict]:
    """Clusters of units that share an ABSTRACT fingerprint (identical up to
    renamed identifiers/literals) but are NOT already byte-identical exact
    clones. We exclude clusters explained entirely by exact cloning (all members
    share one exact fingerprint) so this reports *renamed-but-not-identical*
    only — the genuine Type-2 signal, additive to ``unit_clusters``."""
    memo = memo or CloneMemo(spec_by_lang)
    by_abstract: dict[str, list[CodeUnit]] = defaultdict(list)
    exact_of: dict[int, str] = {}
    for u in units:
        if u.loc < min_loc:
            continue
        by_abstract[memo.abstract_fp(u)].append(u)
        # This recomputed the exact fingerprint that unit_clusters had ALREADY
        # computed for the same unit -- one full normalize per unit, wasted.
        exact_of[id(u)] = memo.exact_fp(u)

    clusters = []
    for afp, group in by_abstract.items():
        if len(group) < 2:
            continue
        # If every member is byte-identical (one distinct exact fingerprint) it
        # is a pure Type-1 cluster already in unit_clusters -> not a rename.
        if len({exact_of[id(u)] for u in group}) < 2:
            continue
        sites = [{"module": u.module, "name": u.name, "line": u.line, "loc": u.loc}
                 for u in group]
        clusters.append({
            "fingerprint": afp,
            "kind": "renamed",
            "language": group[0].language,
            "count": len(group),
            "loc": group[0].loc,
            "name": group[0].name,
            "names": sorted({u.name for u in group}),
            "sites": sites,
            **_safety([u.module for u in group], root),
        })
    clusters.sort(key=lambda c: c["count"] * c["loc"], reverse=True)
    return clusters


# --------------------------------------------------------------------------- #
# Near-miss clusters (Type-3, advisory) — SourcererCC-style token overlap        #
# --------------------------------------------------------------------------- #
def _overlap(a: Counter, b: Counter) -> float:
    """Multiset overlap = |A intersect B| / |smaller bag|. 1.0 means the smaller
    bag is fully contained in the larger; the SourcererCC similarity measure."""
    inter = sum((a & b).values())
    denom = min(sum(a.values()), sum(b.values()))
    return inter / denom if denom else 0.0


_MIN_BAG = 12          # units with fewer abstract tokens are too generic to judge
_ANON = "<anonymous>"  # inline lambdas/arrows: not meaningful refactor targets

# Languages withheld from the Type-3 (near-miss) pass.
#
# C/C++ were excluded by ACCIDENT until _ts_name learned to read `declarator`:
# every C unit was named "<anonymous>" and the _ANON filter below dropped it.
# Naming them removes the accident, so the exclusion has to become deliberate or
# it silently becomes an admission. It is not safe yet: _GENERIC_KEYWORDS has no
# C type system (int/char/unsigned/sizeof/typedef/struct/volatile/template/...),
# so C's abstracted alphabet collapses to ~16-22 symbols and unrelated functions
# score 0.72-0.90 pairwise -- above the 0.8 threshold. Admitting C requires
# extending _GENERIC_KEYWORDS plus a green false-positive suite; until then,
# fabricating clusters is the worse error, so C/C++ stay out and index.py
# REPORTS the exclusion rather than returning a silent zero.
TYPE3_EXCLUDED_LANGUAGES = {"c", "cpp"}


def _candidate_pairs(rare: list[set], n: int, per_unit_cap: int,
                     pair_cap: int) -> set:
    """Bounded candidate generation over RARE (non-ubiquitous) tokens. Small
    corpora: all pairs. Large corpora: a SourcererCC-style inverted index
    token->units, so only units sharing a rare token are ever compared — the
    O(n^2) blow-up is never paid. ``rare[i]`` is unit i's rare-token SET."""
    pairs: set[tuple[int, int]] = set()
    if n <= 60:  # tiny corpus: compare everything, still trivial work
        return {(i, j) for i in range(n) for j in range(i + 1, n)}

    inverted: dict[str, list[int]] = defaultdict(list)
    for idx in range(n):
        for tok in rare[idx]:
            inverted[tok].append(idx)
    for units_with_tok in inverted.values():
        if not 2 <= len(units_with_tok) <= 400:  # skip still-common tokens
            continue
        for a_pos, i in enumerate(units_with_tok):
            for j in units_with_tok[a_pos + 1: a_pos + 1 + per_unit_cap]:
                pairs.add((i, j) if i < j else (j, i))
                if len(pairs) >= pair_cap:
                    return pairs
    return pairs


def near_clusters(units: list[CodeUnit], spec_by_lang: dict, root=None,
                  min_loc: int = 6, threshold: float = 0.8,
                  min_shared_rare: int = 4, max_cluster: int = 30,
                  per_unit_cap: int = 200, pair_cap: int = 400_000,
                  memo: "CloneMemo | None" = None) -> list[dict]:
    """Advisory Type-3 (near-miss) clusters: units whose abstracted token bags
    overlap >= ``threshold`` but are NOT identical (exact/renamed cover those).

    Overlap is the SourcererCC multiset measure |A∩B| / |min(A,B)| on the
    abstracted bags. Union-find groups transitively similar units; each cluster
    carries ``similarity`` (mean pair overlap) + ``similarity_max``. Never
    auto-collapsed (safety-annotated) — a heuristic, advisory only.

    PRECISION NOTE (honest, load-bearing for the Rust port): abstracting every
    identifier to ``ID`` makes low-entropy code (React/JSX callbacks, thin API
    wrappers) look near-identical, and transitive union-find then chains such a
    family into one giant blob. Three guards keep the signal actionable without
    changing the metric: (1) inline lambdas (``<anonymous>``) are excluded; (2) a
    pair must share >= ``min_shared_rare`` NON-ubiquitous tokens (incidental
    single-token matches don't chain); (3) a cluster stops growing past
    ``max_cluster`` members. All three are bounds, not correctness — a Rust port
    must mirror them to reproduce the output."""
    memo = memo or CloneMemo(spec_by_lang)
    pool = [u for u in units if u.loc >= min_loc and u.name != _ANON
            and u.language not in TYPE3_EXCLUDED_LANGUAGES]
    bags: list[Counter] = []
    afps: list[str] = []
    keep: list[CodeUnit] = []
    for u in pool:
        spec = spec_by_lang.get(u.language)
        # Abstract ONCE and derive both. token_bag() and abstract_fingerprint()
        # each call _abstract_tokens() internally, so calling both here tokenized
        # the same source twice per unit -- the single largest piece of redundant
        # work in the clone passes. Output is unchanged by construction: the bag
        # is the same Counter and the fingerprint comes from the same helper.
        tokens = _abstract_tokens(u.source, spec)
        bag = Counter(tokens)
        if sum(bag.values()) < _MIN_BAG:  # too few tokens to judge similarity
            continue
        keep.append(u)
        bags.append(bag)
        afp = _fingerprint_of_tokens(tokens)
        afps.append(afp)
        # We tokenized for the bag anyway, so the abstract fingerprint was free
        # here -- donate it so renamed_clusters need not re-abstract the same
        # source. Whichever pass runs first pays; the other rides along.
        memo.put_abstract_fp(u, afp)
    n = len(keep)
    if n < 2:
        return []

    # Rare tokens = those not saturating the corpus (drop ID/NUM/STR/common ops).
    df: Counter = Counter()
    for bag in bags:
        df.update(bag.keys())
    ubiq_cut = max(3, int(0.4 * n))  # floor keeps tiny corpora from dropping all
    rare = [{t for t in bag if df[t] <= ubiq_cut} for bag in bags]

    parent = list(range(n))
    size = [1] * n

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb or size[ra] + size[rb] > max_cluster:  # cap runaway growth
            return
        keep_root, drop = (ra, rb) if ra < rb else (rb, ra)
        parent[drop] = keep_root
        size[keep_root] += size[drop]

    edge_overlap: dict[tuple[int, int], float] = {}
    for i, j in _candidate_pairs(rare, n, per_unit_cap, pair_cap):
        if afps[i] == afps[j]:
            continue  # identical (exact or renamed) -> covered elsewhere
        if len(rare[i] & rare[j]) < min_shared_rare:
            continue  # only incidental overlap -> not a real near-clone
        ov = _overlap(bags[i], bags[j])
        if ov >= threshold:
            union(i, j)
            edge_overlap[(i, j)] = ov

    comps: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        comps[find(i)].append(i)

    clusters = []
    for members in comps.values():
        if len(members) < 2:
            continue
        mset = set(members)
        overlaps = [ov for (i, j), ov in edge_overlap.items()
                    if i in mset and j in mset]
        if not overlaps:  # component held only cap-skipped edges
            continue
        group = [keep[i] for i in members]
        sites = [{"module": u.module, "name": u.name, "line": u.line, "loc": u.loc}
                 for u in group]
        clusters.append({
            "kind": "near",
            "language": group[0].language,
            "count": len(group),
            "loc": min(u.loc for u in group),
            "name": group[0].name,
            "names": sorted({u.name for u in group}),
            "similarity": round(sum(overlaps) / len(overlaps), 3),
            "similarity_max": round(max(overlaps), 3),
            "sites": sites,
            **_safety([u.module for u in group], root),
        })
    clusters.sort(key=lambda c: (c["similarity"], c["count"] * c["loc"]), reverse=True)
    return clusters


# --------------------------------------------------------------------------- #
# SAFETY-CLASS annotation                                                       #
# --------------------------------------------------------------------------- #
_HEURISTIC = re.compile(
    r"(?:^|/)(devices?|drivers?|firmware|kernel|hv|motion|scan|safety|bias|"
    r"interlock|relay|actuator)(?:/|_|\.|$)", re.I)


def _is_safety_path(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    try:
        from ..sensitivity import GENERIC_HIGH_RISK_PATHS

        if any(tok in norm for tok in GENERIC_HIGH_RISK_PATHS):
            return True
    except Exception:
        pass
    return bool(_HEURISTIC.search(norm))


def _safety(paths: list[str], root=None) -> dict:
    hits = sorted({p for p in paths if _is_safety_path(p)})
    if hits:
        return {"safety": "judgment-gated — do NOT auto-collapse", "safety_sites": hits}
    return {"safety": None}
