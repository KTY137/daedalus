"""Preservation checker -- an asymmetric tripwire on the prose lane.

READ THIS FIRST, AND DO NOT MISREAD IT
--------------------------------------
**This is a tripwire, not a gate. It raises the floor without moving the
ceiling. Human review remains the gate.**

All it proves is a one-directional, syntactic claim: *fact-bearing tokens that
were in the before-text are still somewhere in the after-text.* It says
nothing -- can say nothing -- about whether the rewrite is accurate, complete,
or honest. A rewrite that passes clean has not been checked for correctness;
it has merely been checked for one specific, very common, very cheap-to-detect
kind of damage. See BLIND SPOTS below, which is the load-bearing section of
this file.

A gate people believe is stronger than it is, is worse than no gate. If this
module's existence ever becomes the reason a doc diff is reviewed less
carefully, it has done net harm and should be deleted.

Why it exists anyway
--------------------
The installed self-policy lets the local model write to ``docs/``, ``tests/``
and ``README.md``. Two of those three have a machine-checkable gate: a test
either passes or it doesn't. **Prose had none.** ``verify()``'s per-file
dispatch (``daedalus/verifier.py``) branched on ``.py``, ``.json`` / ``.yaml``,
``.js`` and ``.html`` and nothing else, so a ``.md`` write fell off the end of
that chain and faced only the schema and did_work checks. It was accepted on the
strength of "the report parsed and a file changed", which is exactly the "empty
green" the rest of the harness exists to prevent. Nothing went red when a true
sentence was deleted.

``verify()`` now has a prose branch (``_prose_check``) and it calls
:func:`check_preservation`. It needs a BEFORE-image to compare against, which
the caller supplies as ``prose_before=`` -- built from the writer's own rollback
backups, the only source that is truthful about what the file said at the
instant before the write. Without one the branch blocks with
``status="unknown"``: a check that could not run is refused, and is recorded as
inconclusive rather than as a verdict against the model. **Read the rest of this
docstring before treating that green as meaning anything.**

MEASURED failure this repo actually produced (qwen2.5-coder:7b rewriting
``docs/LOCAL_MODELS.md`` under an instruction that said *"Keep every fact that
is already in the file and do not add any new ones"*)::

    "pointed at an OpenAI-compatible endpoint via three env vars"
        -> "configured via three environment variables"     # fact deleted
    "Per `docs/IMPROVEMENTS_RESEARCH.md`,"
        -> (gone)                                           # cross-ref deleted
    `daedalus`  -> daedalus                                 # markup stripped
    "Recommended models" -> "Recommended Models"            # style churn

Note the first one carries NO markdown markup at all -- the source sentence is
plain prose. That is why the ``term`` class below exists: without it the most
damaging of the four edits would be the one the checker could not see.

So: extract from the BEFORE text the artefacts that carry facts, and report
every one that did not survive into the AFTER text.

What counts as an artefact (and why):

==================  ==========================================================
inline code         backticks are the author asserting "this is an identifier".
                    Env vars, model names, paths, commands. Highest density.
fenced code         a command line is never legitimately "reworded".
links / URLs        a target is a fact with no paraphrase.
path references     repo-relative paths named in prose (outside code).
numbers + units     ``24B``, ``~12-16 GB``, ``2026`` -- the facts a rewriter
                    most likes to smooth away.
table cells         only cells carrying code / a digit / a path. Prose cells
                    are deliberately NOT protected (see BLIND SPOTS).
emphasis spans      the author marking a phrase load-bearing -- but only when
                    the phrase has a fact marker, so ``**and**`` is ignored.
technical terms     bare prose tokens with an internal capital, an acronym, or
                    a digit: ``OpenAI-compatible``, ``MoE``, ``VRAM``, ``MIT``,
                    ``Apache-2.0``. Sentence-initial capitals ("Per", "Best")
                    are excluded, which is what keeps this class quiet.
headings            structure only; reported, never blocking.
==================  ==========================================================

Severity, and what blocks
-------------------------
Comparison happens in a *projection*: markdown markup stripped and whitespace
collapsed, so **line rewrapping and markup churn are invisible** and only real
deletions register.

``LOST``      the artefact's text appears NOWHERE in the after document.
              Highest-confidence deletion. **This, and only this, fails.**
``REDUCED``   fewer occurrences than before, but at least one survives. The
              fact may live on elsewhere; a human should look.
``DEMOTED``   text survived, its markup did not (`` `daedalus` `` -> daedalus).
``RECASED``   text survived modulo case/whitespace only.
``SECTION``   a heading disappeared.
``STRUCTURE`` a table lost rows, or a code fence disappeared.

Only ``LOST`` flips ``ok``. The argument for that line:

* Promotion is a human act, so the checker's *first* job is REPORTING -- a
  60-line prose diff with one quietly-deleted sentence is precisely what a
  reviewer skims past. Turning "read this whole diff" into "look at these two
  lines" is the bulk of the value and needs no veto.
* But the harness's own *acceptance* is not a human act. If a rewrite that
  deleted a load-bearing fact is marked ``ok``, the cascade banks a savings
  claim for damaged output and the doc lane is once again the lane with no
  gate. ``LOST`` is the lowest-false-positive class available, so failing there
  escalates to the strong model -- the same remedy every other check uses.
* The softer classes do NOT block, because each has an honest
  legitimate-improvement story (de-duplicating a repeated mention, dropping
  over-eager backticks, fixing a heading's case, renaming a section). A gate
  that blocks those gets switched off, and a switched-off gate protects
  nothing.

BLIND SPOTS -- what this structurally CANNOT catch
--------------------------------------------------
This is a *deletion* detector over *tokens*. It is blind to:

* **Meaning changes that delete no token.** "is now the *older* tier" ->
  "is an older tier"; "only if you are *not* on Ollama" -> "if you are on
  Ollama". Negation flips and dropped qualifiers are invisible.
* **Spelled-out numbers.** "three env vars" -> "environment variables" loses
  the count and leaves no digit behind.
* **Anything ADDED.** By construction it only asks what vanished. A model that
  invents an ``OLLAMA_TIMEOUT`` env var passes completely clean.
* **Reordering / wrong attachment.** Moving a true fact under the wrong
  heading preserves every artefact.
* **Plain-prose claims.** A sentence with no code, number, link or emphasis is
  unprotected -- including prose table cells, excluded on purpose because
  rewording them is exactly what a good rewrite does.
* **Correct deletions.** It cannot tell an obsolete fact removed on purpose
  from a true one removed by accident. A ``LOST`` means "prove this was
  intended", not "this is wrong".
* **Semantic equivalence.** ``http://localhost:11434`` ->
  ``http://127.0.0.1:11434`` reads as ``LOST`` though it is arguably a fix.
* **Substring arithmetic.** Occurrence counts use word-boundary matching, but
  one artefact can still be contained in another, so a ``REDUCED`` count can be
  off by one. That is a reason ``REDUCED`` does not block.

The sharpest way to put it: a model that deletes every true sentence in a
document and replaces them with false sentences *containing the same code
spans, paths and numbers* passes this checker with zero findings. That is not
a hypothetical bound, it is the actual bound. ``ok is True`` means "no
fact-bearing token vanished", and it must never be read or reported as
"the rewrite is good".

This module is pure and offline: two strings in, findings out. It performs no
I/O, spawns nothing, and reaches no network or model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "LOST", "REDUCED", "DEMOTED", "RECASED", "SECTION", "STRUCTURE",
    "SEVERITY_ORDER", "BLOCKING",
    "Finding", "PreservationResult",
    "check_preservation", "is_prose_path", "project",
]

# --------------------------------------------------------------------------
# severities
# --------------------------------------------------------------------------

LOST = "lost"            # text gone entirely  -- the only blocking severity
REDUCED = "reduced"      # fewer occurrences, >=1 survives
DEMOTED = "demoted"      # text survived, markup did not
SECTION = "section"      # a heading disappeared
RECASED = "recased"      # survived modulo case/whitespace
STRUCTURE = "structure"  # table rows / fences lost

SEVERITY_ORDER = [LOST, REDUCED, DEMOTED, SECTION, RECASED, STRUCTURE]

#: The severities that fail the gate. Deliberately a one-element set -- see the
#: module docstring for the argument. Widening this is a policy decision, not a
#: tuning knob.
BLOCKING = frozenset({LOST})

_PROSE_SUFFIXES = (".md", ".markdown", ".mdx", ".rst", ".txt")


def is_prose_path(rel: str) -> bool:
    """Whether a repo-relative path is prose this checker understands."""
    return str(rel).lower().endswith(_PROSE_SUFFIXES)


# --------------------------------------------------------------------------
# projection -- the comparison space
# --------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_LINK_RE = re.compile(r"\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_MARKUP_CHARS = re.compile(r"[`*_~#>|\\]")
_DASHES = re.compile(r"[‐-―−]")
_APPROX = re.compile(r"[≈~]")
_WS = re.compile(r"\s+")


def project(text: str) -> str:
    """Markup-stripped, whitespace-collapsed view of a markdown document.

    This is the space every comparison happens in, and it is the reason the
    checker is quiet about legitimate edits: rewrapping a paragraph, adding or
    removing backticks, and re-indenting all vanish here, so what remains is
    the words themselves. Artefact keys are normalised through this same
    function, so both sides always speak the same dialect.
    """
    t = _COMMENT_RE.sub(" ", text)
    t = _LINK_RE.sub(r"\1 \2", t)          # keep BOTH the label and the target
    t = _MARKUP_CHARS.sub(" ", t)
    t = _DASHES.sub("-", t)
    t = _APPROX.sub("", t)
    return _WS.sub(" ", t).strip()


def _key(raw: str) -> str:
    return project(raw)


def _count(projection: str, key: str) -> int:
    """Word-boundary occurrences of ``key`` in a projection."""
    if not key:
        return 0
    return len(re.findall(r"(?<!\w)" + re.escape(key) + r"(?!\w)", projection))


# --------------------------------------------------------------------------
# artefact extraction
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"`+([^`\n]+?)`+")
# ``**strong**`` and ``*em*``. Underscore emphasis is deliberately NOT matched:
# it collides with snake_case identifiers such as OLLAMA_EMBED_MODEL.
_STRONG_RE = re.compile(r"\*\*(?!\s)([^*\n]+?)(?<!\s)\*\*")
_EM_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_URL_RE = re.compile(r"https?://[^\s<>)\]\"'`]+")
_PATH_RE = re.compile(r"(?<![\w/.])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,6})(?![\w/])")
_NUM_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*)\s*([A-Za-z%]{1,4})?(?![\w.])")
_TERM_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^[\s|:-]+$")
_FACT_MARKER_RE = re.compile(r"[0-9A-Z/:.\-]")


def _split_fences(text: str) -> tuple[list[list[str]], str]:
    """Return (fence bodies, everything outside fences)."""
    fences: list[list[str]] = []
    outside: list[str] = []
    cur: list[str] | None = None
    marker: str | None = None
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if cur is None:
            if m:
                cur, marker = [], m.group(1)[0] * 3
                continue
            outside.append(line)
        else:
            if m and line.strip().startswith(marker or "```"):
                fences.append(cur)
                cur, marker = None, None
                continue
            cur.append(line)
    if cur is not None:                     # unterminated fence still counts
        fences.append(cur)
    return fences, "\n".join(outside)


def _strip_inline_code(text: str) -> str:
    """Blank out inline-code spans so prose-only classes don't double-report a
    path/number that the code-span class already protects."""
    return _INLINE_CODE_RE.sub(" ", text)


def _has_fact_marker(key: str) -> bool:
    """Whether an emphasised phrase looks like a fact rather than tone.

    ``**OpenAI-compatible endpoint**`` yes (uppercase, two words);
    ``**and**`` / ``*older*`` / ``*not*`` no. Emphasis is a weak, stylistic
    signal, so it is filtered; backticks are not, because a backtick IS the
    author asserting the token is technical.
    """
    return bool(_FACT_MARKER_RE.search(key)) or len(key.split()) >= 2


# Extractors return the artefact's RAW source text. Matching always happens on
# ``_key(raw)`` (the projection), but the raw form is what gets reported, so a
# human sees `docs/IMPROVEMENTS_RESEARCH.md` and not the projection's
# underscore-eaten `docs/IMPROVEMENTS RESEARCH.md`.

def _inline_code_keys(text: str) -> list[str]:
    _, outside = _split_fences(text)
    return [m for m in _INLINE_CODE_RE.findall(outside) if len(_key(m)) >= 2]


def _emphasis_keys(text: str) -> list[str]:
    _, outside = _split_fences(text)
    raw = _STRONG_RE.findall(outside) + _EM_RE.findall(outside)
    return [r for r in raw if len(_key(r)) >= 2 and _has_fact_marker(_key(r))]


def _fence_keys(text: str) -> list[str]:
    fences, _ = _split_fences(text)
    return [line.strip() for body in fences for line in body if len(_key(line)) >= 4]


def _link_keys(text: str) -> list[str]:
    _, outside = _split_fences(text)
    targets = [t for _, t in _LINK_RE.findall(outside)]
    targets += _URL_RE.findall(_strip_inline_code(_LINK_RE.sub(" ", outside)))
    return [t for t in targets if len(_key(t)) >= 2]


def _path_keys(text: str) -> list[str]:
    _, outside = _split_fences(text)
    bare = _URL_RE.sub(" ", _strip_inline_code(outside))
    return [p for p in _PATH_RE.findall(bare) if len(_key(p)) >= 2]


def _number_keys(text: str) -> list[str]:
    """Digit-bearing facts, normalised so ``~12-16 GB`` and ``12-16GB`` agree.

    Extracted (not substring-counted) from the projection on BOTH sides, so
    spacing and unit casing never create a phantom finding.
    """
    _, outside = _split_fences(text)
    proj = project(_strip_inline_code(outside))
    keys: list[str] = []
    for num, unit in _NUM_RE.findall(proj):
        num = num.replace(",", "")
        if unit:
            keys.append(f"{num}{unit.lower()}")
        elif len(num.replace(".", "")) >= 2:
            # bare single digits ("stage-1") are noise; two digits or more
            # ("2026", "2.0") are facts.
            keys.append(num)
    return keys


def _table_rows(text: str) -> list[list[str]]:
    _, outside = _split_fences(text)
    rows: list[list[str]] = []
    for line in outside.splitlines():
        m = _TABLE_ROW_RE.match(line)
        if not m or _TABLE_SEP_RE.match(line):
            continue
        rows.append([c.strip() for c in m.group(1).split("|")])
    return rows


def _table_cell_keys(text: str) -> list[str]:
    """Fact-bearing table cells only: a cell must carry inline code, a digit,
    or a real path/URL. Pure-prose cells are left unprotected on purpose --
    rewording them is exactly what a legitimate rewrite does, and flagging that
    is how a gate earns its way to being switched off.

    MEASURED calibration: an earlier version admitted any cell containing "/",
    which made the live qwen2.5-coder:7b rewrite report the cell "the coder
    that reads/writes" -> "The coder for reading/writing" as LOST. That is a
    legitimate rewording of prose and a blocking false positive, so a bare
    slash no longer qualifies -- the path must actually look like a path.
    """
    out: list[str] = []
    for row in _table_rows(text):
        for cell in row:
            if not cell:
                continue
            fact_bearing = (
                "`" in cell
                or re.search(r"\d", cell)
                or _PATH_RE.search(cell)
                or _URL_RE.search(cell)
            )
            if not fact_bearing:
                continue
            if len(_key(cell)) >= 2:
                out.append(cell)
    return out


def _is_technical_term(tok: str) -> bool:
    """Whether a bare prose token is a technical term worth protecting.

    Deliberately narrow, because this is the only class that reads UNMARKED
    prose and so is the only one that could get noisy. A token qualifies on:

    * an **internal** capital -- ``OpenAI``, ``MoE``. Requiring the capital to
      be internal is what excludes sentence-initial words ("Per", "Best",
      "Re-benchmark") and ordinary proper nouns ("Ollama", "Sonnet"), which
      would otherwise flood the report.
    * an all-caps run of 2+ -- ``VRAM``, ``MIT``.
    * a digit next to letters -- ``Apache-2.0``, ``stage-1``.

    Plain hyphenated English ("well-tested", "multi-step", "purpose-built") is
    excluded on purpose: a rewriter is allowed to touch those.
    """
    core = tok.strip(".,;:")
    if len(core) < 2:
        return False
    if re.search(r"(?<=.)[A-Z]", core):
        return True
    if core.isupper():
        return True
    return bool(re.search(r"\d", core) and re.search(r"[A-Za-z]", core))


def _term_keys(text: str) -> list[str]:
    _, outside = _split_fences(text)
    proj = project(_strip_inline_code(outside))
    out: list[str] = []
    for m in _TERM_TOKEN_RE.finditer(proj):
        tok = m.group(0)
        if not _is_technical_term(tok):
            continue
        # A token sitting right after a number is a UNIT ("12-16 GB"), and the
        # number class already owns it -- with spacing normalised, so "12-16GB"
        # is correctly a non-event. MEASURED: without this, the control case
        # "~12-16 GB" -> "12-16GB" reported GB as LOST and BLOCKED a rewrite
        # that had changed nothing but whitespace.
        head = proj[:m.start()].rstrip()
        if head and head[-1].isdigit():
            continue
        out.append(tok)
    return out


def _heading_keys(text: str) -> list[str]:
    _, outside = _split_fences(text)
    out: list[str] = []
    for line in outside.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            k = _key(m.group(2))
            if k:
                out.append(k)
    return out


#: class name -> extractor. Order fixes report priority and cross-class dedupe:
#: the most specific / highest-confidence class claims a shared key first.
_TEXT_CLASSES: list[tuple[str, object]] = [
    ("code", _inline_code_keys),
    ("fence", _fence_keys),
    ("link", _link_keys),
    ("path", _path_keys),
    ("table_cell", _table_cell_keys),
    ("emphasis", _emphasis_keys),
    ("term", _term_keys),
]

#: classes whose markup loss (text intact) is worth a DEMOTED note
_MARKUP_CLASSES = {"code": _inline_code_keys, "emphasis": _emphasis_keys}


# --------------------------------------------------------------------------
# result types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: str
    artefact: str
    before: int = 0
    after: int = 0
    note: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity in BLOCKING

    def describe(self) -> str:
        art = self.artefact if len(self.artefact) <= 70 else self.artefact[:67] + "..."
        head = f"[{self.severity}] {self.kind}: {art!r}"
        if self.note:
            return f"{head} ({self.note})"
        if self.before or self.after:
            return f"{head} ({self.before}x -> {self.after}x)"
        return head

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "severity": self.severity,
            "artefact": self.artefact, "before": self.before,
            "after": self.after, "note": self.note,
        }


@dataclass
class PreservationResult:
    ok: bool
    findings: list[Finding] = field(default_factory=list)

    @property
    def lost(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == LOST]

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    def of(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def summary(self, limit: int = 3) -> str:
        """One line, safe to drop straight into a verifier check ``detail``."""
        if not self.findings:
            return "all fact-bearing artefacts preserved"
        blocking = self.blocking
        head = blocking or self.findings
        shown = "; ".join(f.describe() for f in head[:limit])
        extra = len(head) - limit
        tail = f" (+{extra} more)" if extra > 0 else ""
        counts = ", ".join(
            f"{sev}={len(self.of(sev))}" for sev in SEVERITY_ORDER if self.of(sev)
        )
        return f"{counts} | {shown}{tail}"

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "findings": [f.as_dict() for f in self.findings],
            "summary": self.summary(),
        }


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------


def _multiset(keys: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k in keys:
        out[k] = out.get(k, 0) + 1
    return out


def _keyed(raws: list[str]) -> tuple[dict[str, int], dict[str, str]]:
    """(normalised key -> count, normalised key -> raw text to display)."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for raw in raws:
        k = _key(raw)
        counts[k] = counts.get(k, 0) + 1
        display.setdefault(k, raw.strip() or k)
    return counts, display


def check_preservation(before: str, after: str) -> PreservationResult:
    """Report every fact-bearing artefact of ``before`` that did not survive.

    Pure and offline. ``ok`` is False only when something was ``LOST`` -- see
    the module docstring for why the softer severities are reported instead.
    """
    findings: list[Finding] = []
    before_proj, after_proj = project(before), project(after)
    before_fold, after_fold = before_proj.casefold(), after_proj.casefold()
    seen: set[str] = set()

    # --- text artefacts: did the words survive anywhere at all? -------------
    for kind, extract in _TEXT_CLASSES:
        counts, display = _keyed(extract(before))                  # type: ignore[operator]
        for key, n_before in counts.items():
            if key in seen:
                continue           # one deletion, one finding
            seen.add(key)
            shown = display[key]
            n_after = _count(after_proj, key)
            if n_after == 0:
                # Before calling it lost, check whether only the CASE moved --
                # a rewriter re-capitalising a phrase has not deleted a fact.
                if _count(after_fold, key.casefold()) > 0:
                    findings.append(Finding(kind, RECASED, shown, n_before, 0,
                                            note="survives with different case"))
                else:
                    findings.append(Finding(kind, LOST, shown, n_before, 0))
                continue
            if n_after < _count(before_proj, key):
                findings.append(Finding(kind, REDUCED, shown, n_before, n_after))

    # --- numbers: extracted from BOTH projections, never substring-matched --
    num_before, num_after = _multiset(_number_keys(before)), _multiset(_number_keys(after))
    for key, n_before in num_before.items():
        n_after = num_after.get(key, 0)
        if n_after == 0:
            findings.append(Finding("number", LOST, key, n_before, 0))
        elif n_after < n_before:
            findings.append(Finding("number", REDUCED, key, n_before, n_after))

    # --- markup demotion: the words stayed, the markup didn't --------------
    already = {f.artefact for f in findings}
    for kind, extract in _MARKUP_CLASSES.items():
        m_before, disp = _keyed(extract(before))    # type: ignore[operator]
        m_after, _ = _keyed(extract(after))
        for key, n_before in m_before.items():
            if disp[key] in already:
                continue                            # already reported harder
            n_after = m_after.get(key, 0)
            if n_after < n_before:
                findings.append(Finding(
                    kind, DEMOTED, disp[key], n_before, n_after,
                    note="text kept, markup stripped"))

    # --- headings: structure, reported only --------------------------------
    h_before, h_after = _heading_keys(before), _heading_keys(after)
    fold_after = {h.casefold(): h for h in h_after}
    exact_after = set(h_after)
    for h in h_before:
        if h in exact_after:
            continue
        if h.casefold() in fold_after:
            findings.append(Finding(
                "heading", RECASED, h, note=f"re-cased to {fold_after[h.casefold()]!r}"))
        else:
            findings.append(Finding("heading", SECTION, h, note="heading removed"))

    # --- coarse structure: rows and fences ---------------------------------
    rows_b, rows_a = len(_table_rows(before)), len(_table_rows(after))
    if rows_a < rows_b:
        findings.append(Finding("table", STRUCTURE, "table rows", rows_b, rows_a,
                                note="table lost rows"))
    fen_b, fen_a = len(_split_fences(before)[0]), len(_split_fences(after)[0])
    if fen_a < fen_b:
        findings.append(Finding("fence", STRUCTURE, "code fences", fen_b, fen_a,
                                note="code fence removed"))

    rank = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    findings.sort(key=lambda f: (rank.get(f.severity, 99), f.kind, f.artefact))
    return PreservationResult(ok=not any(f.blocking for f in findings), findings=findings)
