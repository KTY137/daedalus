"""artifacts.py — the DATA layer: which files a program moves, and what is in them.

WHY THIS IS A SEPARATE LAYER FROM ``typegraph``
-----------------------------------------------
The type layer describes **shapes declared in code** — what a function says it
takes and returns. This layer describes **artefacts that move between programs**
— which file a script reads, which it writes, and what schema that file actually
carries. In a physics analysis those are genuinely two worlds:

    analysis.cpp  --writes-->  selected.root  (TTree "events": voltage/Float_t …)
    plot_eff.py   --reads--->  selected.root
                  --writes-->  fig/eff_vs_v.pdf
    paper.tex     --figures->  fig/eff_vs_v.pdf   "the efficiency is 98.2%"

Nobody can follow that chain today, because every link is a **convention** — a
path spelled inside a string literal — rather than a declaration, and every hop
crosses a language boundary. A path literal, however, is a path literal in
LaTeX, C++, Python, Fortran, Verilog and a Makefile alike, which is why this
layer generalises where the type layer cannot.

THE PAYOFF IS THE JOIN, NOT THE EDGE
------------------------------------
An edge alone says "this script touches that file". The interesting question is
whether the **schema the code declares** and the **schema the file carries**
agree. A renamed branch, a changed unit, a column that quietly moved — those are
the defects that survive every test suite and then appear in a thesis. So this
module extracts artefact schemas as first-class data (``ArtifactSchema``) and
offers ``compare_schema`` so a later lane can report the DISAGREEMENT, which is
the finding worth acting on.

THREE TIERS, AND WHAT EACH HONESTLY COSTS
-----------------------------------------
tier 0  path literals -> artefact edges. No file is opened. Works for every
        language with a pattern below. This is the cheap universal layer.
tier 1  schema as DECLARED IN CODE (``TTree::Branch("voltage", …)``,
        ``read_csv(names=[…])``). Not implemented here yet; the hook is
        ``SCHEMA_FROM_CODE`` and it reports ``not_supported`` until it exists.
tier 2  schema read FROM THE ARTEFACT. Implemented with stdlib only for CSV,
        JSON and NPY. ROOT/HDF5/Parquet need optional readers (``uproot``,
        ``h5py``, ``pyarrow``); absent, they report ``not_supported`` — never an
        empty schema, because "we could not look" and "there are no columns"
        must not render the same.

INVARIANTS
----------
1. **Refuse to guess.** A literal that does not resolve to a file present in the
   file set is DROPPED and COUNTED, never bound to a near-match. Same rule
   ``markdown.py`` applies to document links. A literal matching more than one
   candidate is AMBIGUOUS and produces no edge.
2. **Metadata only, never the payload.** A ``.root`` file is gigabytes; its
   branch list is kilobytes. Schema reads are bounded by
   ``MAX_SCHEMA_BYTES`` and stop at the header. This layer never ingests data.
3. **Reading is not executing.** No file here is imported, run, or evaluated.
   But parsing a hostile binary is still an attack surface, so every reader is
   bounded and failure is reported as ``unreadable``, never as an empty schema.
4. **Artefacts are not code.** Artefact nodes get their own id namespace and
   never enter ``modules``, ``import_edges``, ``all_units`` or the symbol
   resolver — the same carve-out the type layer publishes in ``excluded_from``.
"""
from __future__ import annotations

import csv
import io
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import PurePosixPath

ARTIFACTS_VERSION = "1"

#: Bounded read for schema extraction. Headers are small; data is not.
MAX_SCHEMA_BYTES = 256 * 1024
MAX_COLUMNS = 512
MAX_LITERALS_PER_FILE = 400

NOT_SUPPORTED = "not_supported"
UNREADABLE = "unreadable"
READ = "read"

# --------------------------------------------------------------------------- #
# What counts as an artefact                                                    #
# --------------------------------------------------------------------------- #
#: suffix -> (family, whether a schema reader exists in THIS module)
ARTIFACT_KINDS: dict[str, tuple[str, bool]] = {
    ".root": ("hep_tree", False),      # needs uproot
    ".h5": ("hdf5", False), ".hdf5": ("hdf5", False),
    ".parquet": ("columnar", False),
    ".csv": ("table", True), ".tsv": ("table", True),
    ".npy": ("array", True), ".npz": ("array", False),
    ".json": ("record", True),
    ".yaml": ("record", False), ".yml": ("record", False),
    ".pdf": ("figure", False), ".png": ("figure", False),
    ".svg": ("figure", False), ".eps": ("figure", False),
    ".pkl": ("opaque", False), ".dat": ("opaque", False), ".bin": ("opaque", False),
    ".txt": ("text", False), ".log": ("text", False),
    ".bib": ("bibliography", False),
}


def artifact_family(rel: str) -> str | None:
    """The artefact family for a path, or None if it is not an artefact."""
    suf = PurePosixPath(rel.replace("\\", "/")).suffix.lower()
    kind = ARTIFACT_KINDS.get(suf)
    return kind[0] if kind else None


def artifact_node_id(rel: str) -> str:
    """Own namespace. Must be impossible to mistake for a module rel path —
    the type layer learned the same lesson with ``type:``/``field:``."""
    return f"artifact:{rel.replace(chr(92), '/')}"


def is_artifact_node_id(node_id: str) -> bool:
    return isinstance(node_id, str) and node_id.startswith("artifact:")


# --------------------------------------------------------------------------- #
# Tier 0 — path literals, per language                                          #
# --------------------------------------------------------------------------- #
# Each rule: (relation, regex with a `p` group, note). `relation` is the DIRECTION
# the code asserts; where a call is genuinely ambiguous about direction the
# relation is `touches` rather than a guess.
_TEX = [
    ("includes",  r"\\(?:input|include|subfile)\s*\{\s*(?P<p>[^}\s]+)\s*\}", "LaTeX source include"),
    ("figures",   r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{\s*(?P<p>[^}\s]+)\s*\}", "figure in a document"),
    ("reads",     r"\\(?:bibliography|addbibresource)\s*\{\s*(?P<p>[^}\s]+)\s*\}", "bibliography"),
    ("reads",     r"\\(?:pgfplotstable)?(?:table|addplot\s*(?:\[[^\]]*\])?)\s*(?:\[[^\]]*\])?\s*\{\s*(?P<p>[^}\s]*\.(?:csv|dat|txt|tsv))\s*\}", "plotted data table"),
]
_PY = [
    ("reads",  r"\b(?:uproot\.open|h5py\.File|np\.load|numpy\.load|pd\.read_\w+|pandas\.read_\w+|json\.load\w*)\s*\(\s*[fru]?['\"](?P<p>[^'\"]+)['\"]", "reader call"),
    ("writes", r"\b(?:to_csv|to_parquet|to_root|savefig|np\.save|numpy\.save|to_hdf)\s*\(\s*[fru]?['\"](?P<p>[^'\"]+)['\"]", "writer call"),
    ("touches", r"\bopen\s*\(\s*[fru]?['\"](?P<p>[^'\"]+\.[A-Za-z0-9]{1,8})['\"]", "open() — mode not read here"),
]
_CPP = [
    ("reads",  r"\bTFile\s*::\s*Open\s*\(\s*\"(?P<p>[^\"]+)\"", "ROOT file opened"),
    ("reads",  r"\b(?:TChain|TFileCollection)\s*\w*\s*(?:\.|->)\s*Add\s*\(\s*\"(?P<p>[^\"]+)\"", "chain input"),
    ("writes", r"\bnew\s+TFile\s*\(\s*\"(?P<p>[^\"]+)\"\s*,\s*\"(?:RECREATE|NEW|CREATE)\"", "ROOT file created"),
    ("includes", r'^\s*#\s*include\s*"(?P<p>[^"]+)"', "local header"),
]
_FORTRAN = [
    ("touches", r"\bOPEN\s*\([^)]*FILE\s*=\s*['\"](?P<p>[^'\"]+)['\"]", "OPEN statement"),
    ("includes", r"^\s*INCLUDE\s+['\"](?P<p>[^'\"]+)['\"]", "INCLUDE"),
]
_VERILOG = [
    ("reads", r"\$readmem[bh]\s*\(\s*\"(?P<p>[^\"]+)\"", "memory initialisation"),
    ("includes", r"^\s*`include\s+\"(?P<p>[^\"]+)\"", "include directive"),
]
_MAKE = [
    # A Makefile states producer and product outright — the only place in this
    # table where direction is declared rather than inferred from a call name.
    ("writes", r"^(?P<p>[^\s:#=][^:#=]*?)\s*:(?!=)", "make target"),
]
_SHELL = [
    ("writes", r"(?<![>])>\s*(?P<p>[^\s>|;&]+\.[A-Za-z0-9]{1,8})", "redirect"),
    ("reads",  r"<\s*(?P<p>[^\s<|;&]+\.[A-Za-z0-9]{1,8})", "input redirect"),
]

LITERAL_RULES: dict[str, list[tuple[str, str, str]]] = {
    "latex": _TEX, "python": _PY, "cpp": _CPP, "c": _CPP,
    "fortran": _FORTRAN, "verilog": _VERILOG, "make": _MAKE, "shell": _SHELL,
}

#: Which language a file's literals should be read with. Deliberately by suffix,
#: not by the ``LanguageSpec`` registry: this table includes formats that carry
#: no code units at all (``.tex``, ``Makefile``) and therefore have no spec.
LITERAL_LANGUAGES = {
    ".tex": "latex", ".sty": "latex", ".cls": "latex",
    ".py": "python",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp", ".hpp": "cpp", ".h": "cpp",
    ".C": "cpp", ".c": "c",
    ".f": "fortran", ".f90": "fortran", ".f77": "fortran", ".for": "fortran",
    ".v": "verilog", ".sv": "verilog", ".vh": "verilog",
    ".mk": "make", ".sh": "shell", ".bash": "shell",
}
LITERAL_FILENAMES = {"makefile": "make", "gnumakefile": "make"}

_COMPILED = {lang: [(rel, re.compile(pat, re.M), note) for rel, pat, note in rules]
             for lang, rules in LITERAL_RULES.items()}


def literal_language(rel: str) -> str | None:
    p = PurePosixPath(rel.replace("\\", "/"))
    by_name = LITERAL_FILENAMES.get(p.name.lower())
    if by_name:
        return by_name
    return LITERAL_LANGUAGES.get(p.suffix)


@dataclass(frozen=True)
class PathLiteral:
    """One path-shaped literal, before resolution. Inert."""
    relation: str            # reads | writes | includes | figures | touches
    raw: str                 # exactly as written
    line: int
    note: str
    language: str

    def to_dict(self) -> dict:
        return {"relation": self.relation, "raw": self.raw, "line": self.line,
                "note": self.note, "language": self.language}


def extract_literals(rel: str, text: str) -> list[PathLiteral]:
    """Path literals in one file, in source order. No resolution, no I/O."""
    lang = literal_language(rel)
    if not lang:
        return []
    starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    out: list[PathLiteral] = []
    seen: set[tuple] = set()
    for relation, rx, note in _COMPILED[lang]:
        for m in rx.finditer(text):
            raw = (m.group("p") or "").strip()
            if not raw or len(raw) > 400:
                continue
            key = (relation, raw, line_of(m.start()))
            if key in seen:
                continue
            seen.add(key)
            out.append(PathLiteral(relation, raw, line_of(m.start()), note, lang))
            if len(out) >= MAX_LITERALS_PER_FILE:
                return out
    return out


# --------------------------------------------------------------------------- #
# Resolution — refuse to guess                                                  #
# --------------------------------------------------------------------------- #
#: LaTeX omits the extension on \input and \includegraphics. Trying candidates
#: is resolution, not guessing, PROVIDED that more than one hit is reported as
#: ambiguous rather than silently taking the first.
_TEX_INPUT_SUFFIXES = (".tex",)
_TEX_FIGURE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")


def _candidates(lit: PathLiteral, from_rel: str) -> list[str]:
    raw = lit.raw.replace("\\", "/").lstrip("./")
    base = PurePosixPath(from_rel.replace("\\", "/")).parent
    roots = [raw]
    if str(base) not in (".", ""):
        roots.append(str(base / raw))
    out: list[str] = []
    for r in roots:
        out.append(r)
        if not PurePosixPath(r).suffix:
            if lit.relation == "includes" and lit.language == "latex":
                out += [r + s for s in _TEX_INPUT_SUFFIXES]
            elif lit.relation == "figures":
                out += [r + s for s in _TEX_FIGURE_SUFFIXES]
    # de-duplicate, preserve order
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


@dataclass(frozen=True)
class ArtifactEdge:
    source: str              # the code/document rel path that names it
    target: str              # artifact node id, or a rel path for a doc/code target
    relation: str
    line: int
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target,
                "relation": self.relation, "line": self.line,
                "attributes": dict(sorted(self.attributes.items()))}


@dataclass
class ResolveReport:
    edges: list[ArtifactEdge] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    external: list[dict] = field(default_factory=list)

    def counts(self) -> dict:
        return {"edges": len(self.edges), "unresolved": len(self.unresolved),
                "ambiguous": len(self.ambiguous), "external": len(self.external)}


_URL = re.compile(r"^[a-z][a-z0-9+.-]*://|^(?:mailto|doi):", re.I)


def resolve_literals(literals_by_file: dict, known_files) -> ResolveReport:
    """Bind literals to real files. Deterministic; every list sorted at the end.

    ``known_files`` is the authoritative set of repo-relative POSIX paths. A
    literal that names nothing in it is COUNTED, never bound to a near-match —
    and one that names several is counted as ambiguous, because picking the
    first would be a stably reproduced fabrication.
    """
    known = {str(k).replace("\\", "/") for k in known_files}
    lower = {}
    for k in sorted(known):
        lower.setdefault(k.lower(), []).append(k)

    rep = ResolveReport()
    for from_rel in sorted(literals_by_file):
        for lit in literals_by_file[from_rel]:
            if _URL.match(lit.raw):
                # An off-tree URL has no second node, so it is an attribute of
                # the referring file, never an edge. Same rule as markdown.py.
                rep.external.append({"from": from_rel, "raw": lit.raw, "line": lit.line})
                continue
            hits: list[str] = []
            for cand in _candidates(lit, from_rel):
                if cand in known:
                    hits.append(cand)
                else:
                    ci = lower.get(cand.lower(), [])
                    hits.extend(ci)
            uniq = sorted(dict.fromkeys(hits))
            if not uniq:
                rep.unresolved.append({"from": from_rel, "raw": lit.raw,
                                       "line": lit.line, "relation": lit.relation})
                continue
            if len(uniq) > 1:
                rep.ambiguous.append({"from": from_rel, "raw": lit.raw, "line": lit.line,
                                      "relation": lit.relation, "candidates": uniq})
                continue
            target = uniq[0]
            fam = artifact_family(target)
            rep.edges.append(ArtifactEdge(
                source=from_rel,
                target=artifact_node_id(target) if fam else target,
                relation=lit.relation, line=lit.line,
                attributes={"raw": lit.raw, "note": lit.note,
                            "language": lit.language,
                            "family": fam or "source",
                            "provenance": "declared"},
            ))
    rep.edges.sort(key=lambda e: (e.relation, e.source, e.target, e.line))
    rep.unresolved.sort(key=lambda d: (d["from"], d["line"], d["raw"]))
    rep.ambiguous.sort(key=lambda d: (d["from"], d["line"], d["raw"]))
    rep.external.sort(key=lambda d: (d["from"], d["line"], d["raw"]))
    return rep


# --------------------------------------------------------------------------- #
# Tier 2 — the schema an artefact actually carries                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Column:
    name: str
    dtype: str = ""          # as the format spells it; "" when the format has none
    shape: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "dtype": self.dtype, "shape": self.shape}


@dataclass(frozen=True)
class ArtifactSchema:
    """What is inside one artefact — or an honest reason we do not know."""
    rel: str
    family: str
    status: str                      # READ | NOT_SUPPORTED | UNREADABLE
    columns: tuple[Column, ...] = ()
    detail: str = ""
    truncated: bool = False
    provenance: str = "observed"     # read from the artefact, so: a sample

    @property
    def known(self) -> bool:
        """True only when the schema was actually read. An empty column list on a
        NOT_SUPPORTED artefact is not 'no columns' — it is 'we did not look'."""
        return self.status == READ

    def to_dict(self) -> dict:
        return {"rel": self.rel, "family": self.family, "status": self.status,
                "known": self.known, "columns": [c.to_dict() for c in self.columns],
                "detail": self.detail, "truncated": self.truncated,
                "provenance": self.provenance}


def _csv_schema(rel: str, blob: bytes) -> ArtifactSchema:
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ArtifactSchema(rel, "table", UNREADABLE, detail="not valid UTF-8")
    first = text.split("\n", 1)[0]
    if not first.strip():
        return ArtifactSchema(rel, "table", UNREADABLE, detail="empty first line")
    delim = "\t" if rel.lower().endswith(".tsv") else None
    if delim is None:
        try:
            delim = csv.Sniffer().sniff(first, delimiters=",;\t| ").delimiter
        except csv.Error:
            delim = ","
    names = next(csv.reader(io.StringIO(first), delimiter=delim), [])
    cols = tuple(Column(n.strip()) for n in names[:MAX_COLUMNS] if n.strip())
    if not cols:
        return ArtifactSchema(rel, "table", UNREADABLE, detail="no header fields")
    return ArtifactSchema(rel, "table", READ, cols,
                          detail=f"header row, delimiter {delim!r}",
                          truncated=len(names) > MAX_COLUMNS)


def _json_schema(rel: str, blob: bytes) -> ArtifactSchema:
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # A bounded read can truncate valid JSON, so say which it was.
        return ArtifactSchema(rel, "record", UNREADABLE,
                             detail=f"{exc.__class__.__name__} (a bounded "
                                    f"{MAX_SCHEMA_BYTES}-byte read may have cut it)")
    if isinstance(data, dict):
        cols = tuple(Column(str(k), type(v).__name__) for k, v in list(data.items())[:MAX_COLUMNS])
        return ArtifactSchema(rel, "record", READ, cols, detail="top-level object keys")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        cols = tuple(Column(str(k), type(v).__name__) for k, v in list(data[0].items())[:MAX_COLUMNS])
        return ArtifactSchema(rel, "record", READ, cols,
                             detail="keys of the FIRST record — later records may differ")
    return ArtifactSchema(rel, "record", READ, (),
                          detail=f"top level is {type(data).__name__}, which has no fields")


def _npy_schema(rel: str, blob: bytes) -> ArtifactSchema:
    """NPY header, parsed with struct — the format is documented and stable."""
    if not blob.startswith(b"\x93NUMPY"):
        return ArtifactSchema(rel, "array", UNREADABLE, detail="missing NPY magic")
    try:
        major = blob[6]
        if major == 1:
            (hlen,) = struct.unpack("<H", blob[8:10])
            head = blob[10:10 + hlen]
        else:
            (hlen,) = struct.unpack("<I", blob[8:12])
            head = blob[12:12 + hlen]
        meta = head.decode("latin1")
        dtype = re.search(r"'descr':\s*'([^']+)'", meta)
        shape = re.search(r"'shape':\s*\(([^)]*)\)", meta)
        names = re.findall(r"\('([^']+)',\s*'([^']+)'", meta)   # structured dtype
    except (IndexError, struct.error, UnicodeDecodeError) as exc:
        return ArtifactSchema(rel, "array", UNREADABLE, detail=exc.__class__.__name__)
    sh = (shape.group(1).strip() if shape else "")
    if names:
        cols = tuple(Column(n, d, sh) for n, d in names[:MAX_COLUMNS])
        return ArtifactSchema(rel, "array", READ, cols, detail="structured dtype fields")
    return ArtifactSchema(rel, "array", READ,
                          (Column("<array>", dtype.group(1) if dtype else "", sh),),
                          detail="unstructured array")


#: Formats whose schema needs a reader this module does not carry. Named so the
#: report can say WHICH dependency would light each one up, instead of a blanket
#: "unsupported".
OPTIONAL_READERS = {
    "hep_tree": "uproot", "hdf5": "h5py", "columnar": "pyarrow",
    "record_yaml": "PyYAML",
}

#: Tier-1 hook: schema as declared in code (``TTree::Branch``, ``read_csv(names=)``).
#: Not implemented. Named so its absence is visible rather than assumed away.
SCHEMA_FROM_CODE = NOT_SUPPORTED


def read_schema(rel: str, blob: bytes, *, truncated: bool = False) -> ArtifactSchema:
    """Schema for one artefact from a BOUNDED read of its head. Never the payload.

    The caller does the I/O and passes at most ``MAX_SCHEMA_BYTES``; this keeps
    the module pure and testable, and keeps the read bound in one place.
    """
    fam = artifact_family(rel)
    if fam is None:
        return ArtifactSchema(rel, "unknown", NOT_SUPPORTED,
                              detail="suffix is not a known artefact family")
    suf = PurePosixPath(rel.replace("\\", "/")).suffix.lower()
    if suf in (".csv", ".tsv"):
        s = _csv_schema(rel, blob)
    elif suf == ".json":
        s = _json_schema(rel, blob)
    elif suf == ".npy":
        s = _npy_schema(rel, blob)
    else:
        dep = OPTIONAL_READERS.get("record_yaml" if suf in (".yaml", ".yml") else fam)
        return ArtifactSchema(rel, fam, NOT_SUPPORTED,
                              detail=(f"needs the optional {dep} reader" if dep
                                      else f"{fam} carries no readable schema"))
    if truncated and s.status == READ:
        return ArtifactSchema(s.rel, s.family, s.status, s.columns,
                              detail=s.detail + "; read was truncated at the byte bound",
                              truncated=True, provenance=s.provenance)
    return s


# --------------------------------------------------------------------------- #
# The join — where the code's claim meets the file's reality                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SchemaComparison:
    """Agreement between a DECLARED shape and an OBSERVED artefact schema.

    ``missing_in_artifact`` is the one that bites: the code names a field the
    file does not have. That is the renamed-branch defect, and it survives every
    test suite that does not read the file.
    """
    artifact: str
    declared_from: str
    matched: tuple[str, ...] = ()
    missing_in_artifact: tuple[str, ...] = ()
    extra_in_artifact: tuple[str, ...] = ()
    dtype_conflicts: tuple[dict, ...] = ()
    comparable: bool = True
    reason: str = ""

    @property
    def agrees(self) -> bool:
        return (self.comparable and not self.missing_in_artifact
                and not self.dtype_conflicts)

    def to_dict(self) -> dict:
        return {"artifact": self.artifact, "declared_from": self.declared_from,
                "comparable": self.comparable, "agrees": self.agrees,
                "reason": self.reason, "matched": list(self.matched),
                "missing_in_artifact": list(self.missing_in_artifact),
                "extra_in_artifact": list(self.extra_in_artifact),
                "dtype_conflicts": [dict(sorted(d.items())) for d in self.dtype_conflicts]}


def compare_schema(schema: ArtifactSchema, declared_fields, *,
                   declared_from: str = "", dtype_map=None) -> SchemaComparison:
    """Compare an artefact schema against declared field names (and optionally
    declared types). ``declared_fields`` is a mapping name -> declared type, or
    any iterable of names.

    NOT comparable is a first-class answer. If the schema was never read, this
    returns ``comparable=False`` with the reason — it does not report every
    declared field as missing, which would turn "we could not look" into a wall
    of false findings.
    """
    if not schema.known:
        return SchemaComparison(schema.rel, declared_from, comparable=False,
                                reason=f"schema {schema.status}: {schema.detail}")
    if isinstance(declared_fields, dict):
        declared = dict(declared_fields)
    else:
        declared = {str(n): "" for n in declared_fields}
    if not declared:
        return SchemaComparison(schema.rel, declared_from, comparable=False,
                                reason="nothing was declared to compare against")

    have = {c.name: c for c in schema.columns}
    matched = sorted(set(declared) & set(have))
    conflicts = []
    if dtype_map:
        for name in matched:
            want = declared.get(name) or ""
            got = have[name].dtype or ""
            if want and got and not dtype_map(want, got):
                conflicts.append({"field": name, "declared": want, "artifact": got})
    return SchemaComparison(
        artifact=schema.rel, declared_from=declared_from,
        matched=tuple(matched),
        missing_in_artifact=tuple(sorted(set(declared) - set(have))),
        extra_in_artifact=tuple(sorted(set(have) - set(declared))),
        dtype_conflicts=tuple(conflicts),
    )


# --------------------------------------------------------------------------- #
def chain_from(rep: ResolveReport, target_rel: str, *, max_hops: int = 8) -> list[dict]:
    """Walk the produce/consume chain backwards from an artefact.

    Answers "where did this figure come from" — the question a thesis reviewer
    asks. Deterministic (sorted frontier), bounded, and it reports the hop that
    ran out rather than presenting a truncated chain as complete.
    """
    writes: dict[str, list[str]] = {}
    reads: dict[str, list[str]] = {}
    for e in rep.edges:
        if e.relation in ("writes", "figures", "includes"):
            writes.setdefault(e.target, []).append(e.source)
        if e.relation in ("reads", "touches"):
            reads.setdefault(e.source, []).append(e.target)

    want = artifact_node_id(target_rel) if artifact_family(target_rel) else target_rel
    chain: list[dict] = []
    frontier = [want]
    seen = {want}
    for hop in range(max_hops):
        producers = sorted({p for node in frontier for p in writes.get(node, [])})
        if not producers:
            break
        inputs = sorted({i for p in producers for i in reads.get(p, [])})
        chain.append({"hop": hop, "artifacts": sorted(frontier),
                      "produced_by": producers, "which_read": inputs})
        frontier = [i for i in inputs if i not in seen]
        seen.update(frontier)
        if not frontier:
            break
    else:
        chain.append({"hop": max_hops, "truncated": True,
                      "note": f"stopped at the {max_hops}-hop bound; the chain may continue"})
    return chain
