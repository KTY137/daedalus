"""mint.py -- independent-oracle task minting: labels the slicer did NOT choose.

Every task in ``daedalus.eval.tasks`` today was hand-picked by a human who then
verified the pick by running ``semantic_slice`` -- circular, because the label
is graded against the exact process that produced it (see tasks.py:1-8). This
module mints ``must_include`` labels from a source that has no opinion about
the import graph at all: a byte-for-byte diff of what actually changed on
disk, either a landed offload edit or a real git commit.

*** DO NOT expand a minted ``must_include`` through ``graph.callees`` / the
import closure -- here or anywhere downstream of this module. *** The moment a
minted label is reachable by walking the same graph the slicer walks, it stops
being independent and the entire reason this file exists evaporates.
``must_include`` is ONLY: symbols whose extracted source differs between
before and after, plus symbols that were added or removed outright. Nothing
transitive, ever -- not even "just one hop of direct callees". A future
contributor who wants richer minted labels needs a THIRD provenance value, not
a quiet edit to this one.

Minted tasks land with ``"tier": "quarantine"`` and
``"label_provenance": "independent_diff"`` and are barred from any go/no-go
recall number until a PROMOTION WITNESS exists for them. There are two, and
``promotion_witness`` returns which one applies rather than a bare boolean:

  ``recurrence``  -- ``confirmations >= MINT_CONFIRM_THRESHOLD``, the original
                     rule, unchanged in meaning.
  ``noise_audit`` -- every threat that constant's comment NAMES, checked and
                     found absent (``audit_noise_threats``).

The second exists because the first never fires. That comment predicts the
threshold stays "low enough to actually accumulate ... instead of never
firing"; measured 2026-09-10, zero confirmations across 400 first-parent
commits and all 48 stored tasks. Recurrence was only ever a proxy for "the
named threats are absent", so the threats are now checked directly -- as a
SEPARATE witness, never by incrementing ``confirmations``, because a count
whose entries mean two different things is a count of nothing. Aggregation/enforcement of the tier gate is the eval harness's job
(a sibling module owns harness.py/report.py); this module only stamps the
fields honestly.

Two more independence rules, both enforced inside ``_mint_from_diffs``:

SCOPE: a changed file is eligible as ``target`` OR as a label source only if
it appears in ``cached_index(repo)["modules"]`` -- the exact membership test
slice.py's own neighborhood expansion uses (``rel in modules``, slice.py
around line 225; that is THE scope boundary, not a second opinion about it).
A minified ``dist/*.js`` build artifact is real text with hundreds of
mechanical "symbols" but was never part of the project the slicer reasons
about -- scoring recall against it measures nothing, and it is usually not
even indexed (``dist`` is a hard-excluded dir, see structcore/index.py
``_IGNORE_DIRS``). Changed files that fail this test are recorded in
``skipped_out_of_scope`` on the diagnostics returned alongside the task (and
on the task itself when one is minted) -- never silently dropped.

CROSS-FILE ONLY: ``must_include`` never contains a symbol defined in the file
chosen as ``target``. The slice always emits its focus file IN FULL, so a
same-file label is recalled by construction -- that is the exact circularity
class this module exists to break, reintroduced through the back door if
same-file symbols were allowed in. A commit/edit where only one in-scope file
has any diffed symbols therefore has no valid label source at all: it mints
nothing rather than minting a label=[] task (``harness._recall`` returns a
vacuous 1.0 for an empty ``must_include``, which would be worse than not
minting). THE SAME GUARD APPLIES AFTER LABEL HYGIENE BELOW: the junk /
cross-language / secret-floor filters can themselves drain every candidate
label, and an emptied-by-filtering ``must_include`` is exactly as vacuous as
an empty one from a single-file diff -- ``_mint_from_diffs`` re-checks
non-emptiness once, after filtering, and mints nothing (with a ``reason``)
if nothing survives.

LABEL HYGIENE (lane A1 -- the honest number, not a hidden one): three more
filters, applied inside ``_mint_from_diffs``, each recording what it dropped
rather than silently discarding it:

  * JUNK: a diffed name that fails ``_is_junk_label`` (not a plausible
    identifier under any supported language's rules, or one of a small set of
    node-text markers that are never legitimate exported symbol names in ANY
    of them -- ``if``/``<anonymous>``/etc.) never becomes a ``must_include``
    entry -- dropped names land in ``labels_filtered_junk`` (sorted). This
    list is deliberately narrow: a name that is a real, commonly-used
    identifier in even one supported language (``delete`` as a Python/Django
    method, ``New`` as a Go exported constructor) is NOT junk just because it
    is also a reserved word in some other language.
  * CROSS-LANGUAGE: a label may only come from a file whose language FAMILY
    (``_language_family(languages.spec_for(...).name)``) matches the
    TARGET's -- a TS symbol co-committed with a Python target measures
    nothing about the Python slicer. Families group languages the slicer's
    own import graph routinely crosses (a C++ file and its own ``.h``; a
    ``.ts`` file and the ``.js`` it imports) -- those are NOT cross-language
    for this filter's purposes, since the label genuinely can turn up in a
    same-family neighbour's slice. Filtered names land in
    ``labels_filtered_cross_language`` (sorted). This is orthogonal to
    CROSS-FILE ONLY above, not a relaxation of it.
  * FLOOR-TRIPPING LABEL SOURCE EXCLUSION: ``sensitivity.secret_floor_rule``
    is run against every anchor CANDIDATE's current content before target
    selection. A file that trips the floor is dropped from the ANCHOR POOL
    (recorded in ``skipped_secret_floor``) -- pointing a task at it is
    unanswerable, since ``semantic_slice`` fails that file closed by design
    (see slice.py's FOCUS GATE) -- AND from label consideration: the same
    egress gate that fails the file closed as a FOCUS also withholds it as a
    NEIGHBOUR, in every lane, at every emission point (slice.py's
    ``_emit_ok``) -- so a symbol defined only in a floor-tripping file can
    never appear in ANY slice, focus or otherwise, and scoring recall against
    it would just be a guaranteed, permanent miss mislabeled as a slicer
    defect. Filtered names land in ``labels_filtered_secret_floor`` (sorted).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path

from daedalus.sensitivity import secret_floor_rule
from daedalus.structcore.index import cached_index
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import extract_units

_LOG = logging.getLogger(__name__)

# JUNK FILTER (label hygiene, lane A1): a diffed "symbol name" that is not a
# plausible identifier is parser noise, not a real label -- ``<anonymous>``
# (an unnamed closure/callback our extractor still has to name *something*)
# or a keyword the language grammar hands back as a node text in some grammar
# edge case (`if`, `else`, ...).
#
# Name-shape check: unicode-aware (a non-ASCII identifier -- ``café`` -- is
# legal Python/JS/etc and must not be treated as noise just for using
# non-ASCII letters) and allows a leading/embedded ``$`` (legal anywhere in a
# JS/TS identifier, e.g. Angular's ``$scope``) on top of the universal
# letter/digit/underscore identifier shape.
#
# Keyword check: deliberately NARROW, and case-SENSITIVE. Real reserved
# words are fixed-case in every language here (always lowercase) -- a
# PascalCase match (``New``, ``Default``, ``Case``, ``Switch``) is essentially
# never grammar-recovery noise and near-always a real exported identifier
# (a Go constructor named ``New``, a C#/Java ``Default``/``Case`` member, a
# class literally named ``Switch``). The set below is further limited to
# words that are reserved in EVERY supported language and implausible as a
# real symbol name in any of them -- unlike ``new``/``delete``/``default``/
# ``case``/``switch``/``static``/``of``/``in``, which are ordinary, common
# identifiers in at least one supported language (Python has none of these as
# keywords at all) and were previously flagged as junk regardless of case,
# silently deflating recall for real symbols like a Python/Django ``delete``
# view method or a Go ``New`` constructor.
_IDENTIFIER_RE = re.compile(r"^(?:[^\W\d]|\$)[\w$]*$")
_JUNK_KEYWORDS = frozenset({
    "if", "elif", "else", "for", "while", "do",
    "try", "except", "catch", "finally", "throw", "raise",
    "return", "yield", "break", "continue", "pass",
    "const", "let", "var", "function", "def", "class", "struct", "enum",
    "interface", "import", "export", "from", "as",
    "typeof", "instanceof", "async", "await",
    "public", "private", "protected", "this", "self", "super",
    "true", "false", "null", "none", "undefined", "nil",
    "<anonymous>",
})


# CROSS-LANGUAGE FAMILY (label hygiene, lane A1): languages the slicer's own
# import graph routinely crosses, so a label source in the "other" member is
# NOT cross-language for recall purposes -- imports.py resolves a C/C++
# ``#include "foo.h"`` regardless of whether the includer is ``.c`` or
# ``.cpp`` (``.h`` is its own LanguageSpec, name "c"), and a ``.ts`` file's
# ``import`` can resolve straight to a co-located ``.js`` module. Every
# LanguageSpec name NOT listed here maps to its own singleton family (its
# prior, unchanged behavior) -- this is purely additive grouping, not a
# relaxation of the filter for any language pair not named below.
_LANGUAGE_FAMILIES: dict[str, str] = {
    "c": "c_cpp", "cpp": "c_cpp",
    "javascript": "js_ts", "typescript": "js_ts",
}


def _language_family(lang_name: str | None) -> str | None:
    """The cross-language filter's equality key for ``lang_name`` -- see
    ``_LANGUAGE_FAMILIES`` above. ``None`` (no LanguageSpec) stays ``None``
    and therefore never equals any real family, same fail-closed behavior as
    before this grouping existed."""
    if lang_name is None:
        return None
    return _LANGUAGE_FAMILIES.get(lang_name, lang_name)


def _is_junk_label(name: str) -> bool:
    """True if ``name`` cannot be a real symbol label -- see the JUNK FILTER
    comment above. Checked name-shape-first (a non-identifier like
    ``<anonymous>`` never reaches the keyword set at all). The keyword check
    is intentionally case-SENSITIVE (see the comment above ``_JUNK_KEYWORDS``
    for why) -- ``name`` is matched as-is, never lowercased."""
    if not _IDENTIFIER_RE.match(name):
        return True
    return name in _JUNK_KEYWORDS

# Below this many independent confirmations a mint stays quarantined and is
# excluded from go/no-go. Rationale: a SINGLE diff-derived label can be a
# false positive from mechanical noise our line-based unit diff can't see
# through (a reformat-only touch that happens to shift a docstring, a rename
# that round-trips to byte-identical source under a new name, a generated-file
# regen) -- one confirmation only rules out "this one mint was a fluke", not
# "this label generalizes". Three independent mints landing on the same
# must_include set is a defensible floor before the label influences a
# headline number, while staying low enough to actually accumulate from real
# (comparatively infrequent) commit/offload activity instead of never firing.
MINT_CONFIRM_THRESHOLD = 3

_GIT_TIMEOUT = 30.0

# Persisted mint store -- the load path that was missing entirely before this
# fix. Without it, mint_task_from_landed_edit/mint_from_commit returned
# in-memory dicts that evaporated at process exit and daedalus.eval.tasks.TASKS
# stayed a hardcoded literal forever, so an "independent_diff"/"temporal_churn"
# label could never actually join the corpus. Sibling of harness.py's
# DEFAULT_BASELINE_PATH: same directory, same "JSON file, sorted keys,
# schema-versioned" contract. Absence of the file (a fresh checkout, or a repo
# where nothing has ever been minted) means "nothing minted yet", not an error
# -- see ``load_minted_tasks``.
DEFAULT_MINT_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "minted_tasks.json")

# The repository's OWN corpus file, resolved from this module's location and
# deliberately NOT the same name as the constant above. They hold the same
# value at import, but ``DEFAULT_MINT_STORE_PATH`` is routinely monkeypatched
# to a tmp file by tests that mint against throwaway fixtures -- so gating the
# portability refusal on it would fire on exactly those legitimate callers
# (measured: it broke ``test_mint_commit_cli_then_all_tasks_picks_it_up_via_
# default_path``, which mints from a temp repo that HAS no portable label).
# This constant tracks the real committed file, which is the only artifact the
# refusal is protecting.
_COMMITTED_STORE_PATH = os.path.normcase(os.path.realpath(DEFAULT_MINT_STORE_PATH))


def _git(repo_root, *args: str) -> str | None:
    """Run git in ``repo_root``; stdout on success, ``None`` on ANY failure
    (missing git, not a repo, bad ref, timeout, non-zero exit). Minting must
    degrade to "nothing minted", never raise -- a caller looping over commits
    or landed edits cannot be allowed to die on the first unreadable one."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, timeout=_GIT_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _is_linked_worktree(repo_root) -> bool:
    """True if ``repo_root`` is a git LINKED WORKTREE, not a primary checkout.

    A minted task USED TO store ``repo`` as an absolute path, and the mint
    store is append-only, so that path had to stay resolvable for the whole
    life of the corpus -- which it did not: 17 stored tasks ended up pinned to
    a checkout on another machine. Since 2026-09-09 the stored value is a
    portable label (``_portable_repo_label``), so the failure this guard
    describes is now caught at the store boundary too. The guard stays: minting
    from a worktree that is about to be deleted is still worth refusing at the
    source. A linked worktree is by construction
    temporary: ``daedalus.spine.attempt`` creates one per candidate and deletes
    it in a ``finally:``. Minting from one therefore writes a task that can
    NEVER be evaluated again -- ``daedalus.eval.tasks.resolve_task_repo`` takes
    the absolute-path branch, finds the directory gone, and raises
    ``cannot resolve task repo label`` for the rest of that task's life. One
    dead row per attempt, forever, in a store nothing prunes.

    Detection is the git on-disk contract, not a path heuristic: ``git worktree
    add`` writes ``.git`` as a FILE holding a ``gitdir:`` pointer, whereas a
    primary checkout has ``.git`` as a DIRECTORY. A bare repo and a plain
    non-repo directory both read as "not a linked worktree" and are left to the
    existing git-failure paths, which already degrade to "nothing minted".

    The pointer alone is NOT enough, and this was measured rather than assumed:
    a SUBMODULE also has ``.git`` as a ``gitdir:`` file, and a submodule
    checkout is perfectly permanent -- refusing to mint from one would be a
    false refusal, and a docstring saying "linked worktree" while the code also
    caught submodules would be a claim its control did not implement.

    Nor is the pointer's PATH enough: matching a ``worktrees`` path component
    would fire on any ordinary repository that happens to live under a
    directory someone named ``worktrees``. So the admin directory the pointer
    resolves to is inspected STRUCTURALLY, which is what actually distinguishes
    them (measured on real git artifacts, not inferred from documentation):

        linked worktree  .git/worktrees/<id>/  HEAD ORIG_HEAD commondir gitdir index logs
        submodule        .git/modules/<name>/  HEAD config description hooks index info
                                               logs objects packed-refs refs

    ``commondir`` and ``gitdir`` together appear only in the linked-worktree
    admin layout. Requiring BOTH means an unreadable or unexpected target fails
    toward "not ephemeral", i.e. toward minting -- which is the correct
    direction for a false negative here, because the alternative is refusing to
    mint from ordinary repositories.
    """
    try:
        dot_git = Path(repo_root) / ".git"
        if not dot_git.is_file():
            return False
        with open(dot_git, "r", encoding="utf-8", errors="replace") as fh:
            pointer = fh.read(4096)
        if not pointer.startswith("gitdir:"):
            return False
        target = pointer.split(":", 1)[1].strip()
        if not target:
            return False
        admin = Path(target)
        if not admin.is_absolute():
            admin = Path(repo_root) / admin
        return (admin / "commondir").is_file() and (admin / "gitdir").is_file()
    except OSError:
        return False


def _show(repo_root, ref: str, rel: str) -> str | None:
    """Blob contents of ``rel`` at ``ref``, or ``None`` if it didn't exist
    there (distinct from an empty-but-present file, which is a real "")."""
    return _git(repo_root, "show", f"{ref}:{rel}")


def _read_worktree(repo_root, rel: str) -> str | None:
    """Current on-disk contents of ``rel``, or ``None`` if it's gone (deleted
    by the edit being minted)."""
    try:
        return (Path(repo_root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _resolve_sha(repo_root, ref: str) -> str | None:
    out = _git(repo_root, "rev-parse", ref)
    return out.strip() if out else None


def _short_hash(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


def _portable_repo_label(repo_root) -> str:
    """Turn a minting root into a reference ``tasks.resolve_task_repo`` can
    resolve on ANY machine -- not only the one that happened to mint.

    THE DEFECT THIS EXISTS TO PREVENT, measured 2026-09-09. Both mint sites
    used to write ``str(Path(repo_root).resolve())``, an absolute host path,
    straight into ``minted_tasks.json`` -- a file that is COMMITTED. The store
    then held 17 tasks pinned to ``C:/Users/nukei/Desktop/agent_env``, a
    checkout on a different machine that does not exist here, so
    ``resolve_task_repo`` raised on every one of them; and 31 more pinned to a
    throwaway git worktree, which resolved only for as long as the process
    happened to be running inside it. A task corpus that names one developer's
    filesystem is not a frozen public task set, and Gate 3's freeze obligation
    is exactly that it be one.

    The labels are the ones ``resolve_task_repo`` already understands, so this
    adds no second naming scheme (plan §5). ``agent_env`` in particular is
    derived from the harness's own location, which is the point: it means "the
    checkout this code is running from", so a self-minted task follows the
    repository to any machine or worktree instead of pointing back at ours.

    An unrecognized root (a test's temp fixture) is returned unchanged rather
    than guessed at. Persisting one is refused separately, by
    ``_refuse_nonportable_repos`` at the store boundary -- minting one in
    memory is legitimate, writing one into the committed corpus is not.
    """
    # ``from .tasks import ...`` and NOT ``from . import tasks``: the latter
    # scores an edge to the PACKAGE ``daedalus.eval`` as well as to the
    # submodule, and that package edge closes a cycle -- it grew the existing
    # ``daedalus.eval`` strongly-connected component from 4 members to 5.
    # tests/contracts/test_import_scc_hierarchy.py caught it via the component
    # digest. Importing the submodule directly is one edge, mint -> tasks, and
    # joins no component.
    from .tasks import AGENT_ENV_ROOT, FOURFOLD_WIKI_FIXTURE, SUNNY_GARDEN_FIXTURE

    resolved = Path(repo_root).resolve()
    for label, root in (("agent_env", AGENT_ENV_ROOT),
                        ("sunny_garden", SUNNY_GARDEN_FIXTURE),
                        ("fourfold_wiki_app", FOURFOLD_WIKI_FIXTURE)):
        if not root:
            continue
        try:
            if Path(root).resolve() == resolved:
                return label
        except OSError:
            continue
    return str(resolved).replace("\\", "/")


# Ceiling on must_include -- see _mint_from_diffs for the ranking/drop rule.
# ~25 keeps a minted task's label set in the same ballpark as the hand-picked
# tasks in tasks.py (single digits to low tens); a giant refactor commit could
# otherwise mint a task with hundreds of labels, which is both an unrealistic
# recall target and a store-bloat problem (every entry round-trips through
# JSON on every load/save).
MUST_INCLUDE_CAP = 25


def _diff_magnitude(before_srcs: list[str], after_srcs: list[str]) -> int:
    """Deterministic size proxy for one symbol, used only to rank which
    labels survive ``MUST_INCLUDE_CAP`` -- NOT a precision diff. Counts the
    +/- lines in a unified diff between the joined before/after source blocks
    (``before_srcs``/``after_srcs`` are lists because a name can repeat across
    sibling classes/closures -- see ``_diffed_symbols``). A pure add or remove
    counts its whole body; an in-place edit counts only the lines that moved.
    """
    before_lines = "\n".join(before_srcs).splitlines()
    after_lines = "\n".join(after_srcs).splitlines()
    diff = difflib.unified_diff(before_lines, after_lines, lineterm="", n=0)
    return sum(1 for line in diff
               if line[:1] in ("+", "-") and line[:3] not in ("+++", "---"))


def _diffed_symbols(rel: str, before_text: str | None, after_text: str | None) -> dict[str, int]:
    """Map of {symbol name -> diff magnitude} for symbols whose extracted
    source differs, plus pure adds/removes.

    Matched by NAME against a (name -> sorted source list) map rather than a
    single name->source dict, so duplicate names (same-named methods on
    sibling classes, nested closures) don't silently clobber each other and
    under-report a real change. A file with no language spec (unsupported
    extension) contributes nothing -- there is no unit-level ground truth to
    diff, only whole-file text, and this module deliberately doesn't fall back
    to that (a whole-file "changed" label would be far too coarse to be an
    honest must_include). The magnitude is only ever used for cap-ranking in
    ``_mint_from_diffs``; it plays no part in WHETHER a symbol counts as
    changed (that's the ``!=`` comparison below).
    """
    spec = spec_for(rel)
    if spec is None:
        return {}
    before_units = extract_units(rel, before_text or "", spec)
    after_units = extract_units(rel, after_text or "", spec)
    before_map: dict[str, list[str]] = {}
    for u in before_units:
        before_map.setdefault(u.name, []).append(u.source)
    after_map: dict[str, list[str]] = {}
    for u in after_units:
        after_map.setdefault(u.name, []).append(u.source)
    changed: dict[str, int] = {}
    for name in set(before_map) | set(after_map):
        before_srcs = sorted(before_map.get(name, []))
        after_srcs = sorted(after_map.get(name, []))
        if before_srcs != after_srcs:
            changed[name] = _diff_magnitude(before_srcs, after_srcs)
    return changed


def _in_scope_modules(repo_root) -> frozenset[str]:
    """The scope membership test -- ``rel in modules`` -- exactly as slice.py
    uses it for its own neighborhood expansion (slice.py, ``rel not in
    modules`` around line 225). A file this module would target or draw a
    label from must be a file the slicer itself would ever consider part of
    "the project"; otherwise the label measures nothing the slicer claims to
    do. Degrades to an empty scope (so callers mint nothing rather than
    crash) on ANY indexing failure -- minting must never raise on a caller
    looping over commits, same contract as ``_git``.
    """
    try:
        idx = cached_index(repo_root)
    except Exception:
        return frozenset()
    return frozenset(idx.get("modules") or {})


def _mint_from_diffs(
    files: dict[str, tuple[str | None, str | None]], *,
    repo_root, minted_at_sha: str | None, source: str, in_scope: frozenset[str],
) -> tuple[dict | None, dict]:
    """Build ONE aggregate quarantined task from a set of file diffs, scoped
    and cross-file-labeled per the module docstring. Returns ``(task,
    diagnostics)``.

    ``files`` maps rel path -> (before_text, after_text); ``None`` on either
    side means the path did not exist there (a create or a delete). ``files``
    keys not present in ``in_scope`` are excluded from BOTH target and label
    consideration entirely -- they never reach ``_diffed_symbols`` at all, so
    an out-of-scope file that would raise/misbehave under unit-level parsing
    (a minified bundle, say) can never even get that far.

    ``diagnostics["skipped_out_of_scope"]`` is always present (sorted, maybe
    empty). ``diagnostics["reason"]`` is present only when ``task`` is
    ``None``, explaining why nothing minted -- callers that only need the
    task (the two public mint_* entry points, which predate this diagnostics
    dict and whose ``dict | None`` / ``list[dict]`` return the CLI depends on)
    are free to ignore it; ``_log_mint_diagnostics`` is how it reaches an
    observable channel without changing that return contract.

    The task's ``target`` (the anchor the slicer will be pointed at) is,
    among in-scope files that have at least one diffed symbol, the one that
    still EXISTS after the edit with the most diffed symbols, ties broken by
    path for determinism -- a deleted file cannot be a slice target. A single
    changed symbol in the anchor earns symbol-level precision
    (``target::symbol``); more than one keeps the target file-level, since a
    symbol-scoped target can't honestly represent labels that live outside
    its own one-hop slice. ``must_include`` is every diffed symbol in every
    OTHER in-scope touched file (never the anchor's own), capped at
    ``MUST_INCLUDE_CAP`` keeping the largest-magnitude symbols
    (``must_include_dropped`` records how many were cut, so a capped task
    never silently reads as full coverage).
    """
    skipped = sorted(rel for rel in files if rel not in in_scope)
    diagnostics: dict = {"skipped_out_of_scope": skipped}

    # EPHEMERAL REPO ROOT -- refused before any work, for every caller.
    # Placed here rather than at the one known bad call site (offload_runner
    # pins offload's repo_root to the candidate worktree, attempt.py:707) so
    # that closing it does not depend on remembering it at the NEXT call site.
    # See ``_is_linked_worktree`` for why a task minted here is permanently
    # unevaluable rather than merely wrong.
    if _is_linked_worktree(repo_root):
        diagnostics["reason"] = (
            f"refusing to mint from a linked git worktree ({str(repo_root)!r}): "
            "a minted task stores an absolute repo path, and a worktree is "
            "deleted by whoever created it -- the task would be permanently "
            "unresolvable"
        )
        diagnostics["refused_ephemeral_repo"] = True
        return None, diagnostics

    scoped = {rel: v for rel, v in files.items() if rel in in_scope}

    per_file: dict[str, dict[str, int]] = {}
    for rel, (before_text, after_text) in scoped.items():
        sizes = _diffed_symbols(rel, before_text, after_text)
        if sizes:
            per_file[rel] = sizes

    if len(per_file) < 2:
        if not per_file:
            diagnostics["reason"] = "no in-scope file had a unit-level change"
        else:
            (only_rel,) = per_file
            diagnostics["reason"] = (
                f"only one in-scope file changed symbols ({only_rel!r}); "
                "no cross-file labels exist to mint"
            )
        return None, diagnostics

    existing = {rel: syms for rel, syms in per_file.items() if scoped[rel][1] is not None}

    # FLOOR-TRIPPING LABEL SOURCE EXCLUSION -- see module docstring. Used
    # below for BOTH the anchor pool (a floor-tripping file can't be pointed
    # at -- semantic_slice's FOCUS GATE fails it closed) and, further down,
    # the cross-file label loop (the same file is withheld as a NEIGHBOUR in
    # every lane too, so its symbols can never be recalled either). Computed
    # over ALL of per_file (not just `existing`) so a deleted-but-still-named
    # path (e.g. a rename that trips a path-marker rule) is caught too; the
    # content check degrades to "" for a deleted file (nothing left on disk
    # to scan).
    floor_tripped = sorted(
        rel for rel in per_file
        if secret_floor_rule(rel, scoped[rel][1] or "") is not None
    )
    diagnostics["skipped_secret_floor"] = floor_tripped

    anchor_pool = {rel: syms for rel, syms in (existing or per_file).items()
                   if rel not in floor_tripped}
    if not anchor_pool:
        # Every file that could anchor this task trips the secret floor --
        # there is no safe target to mint, full stop (never fall back to an
        # unsafe anchor just to produce a task).
        diagnostics["reason"] = (
            "every candidate anchor file trips the secret floor; no safe "
            "target exists"
        )
        return None, diagnostics
    anchor = sorted(anchor_pool, key=lambda r: (-len(anchor_pool[r]), r))[0]
    anchor_syms = per_file[anchor]
    target_lang = spec_for(anchor)
    target_lang_name = target_lang.name if target_lang else None

    # Cross-file only: a symbol NAME can repeat across files (different
    # symbol, same name) -- keep the larger magnitude rather than letting one
    # silently clobber the other, matching _diffed_symbols' own duplicate-name
    # handling. NOT guaranteed non-empty any more: the len(per_file) < 2 check
    # above only guarantees at least one OTHER (non-anchor) per_file entry
    # existed BEFORE filtering -- the junk / cross-language / secret-floor
    # filters below can still drain every one of its symbols, so the
    # post-filter emptiness guard after this loop is load-bearing, not
    # defensive dead code. JUNK / CROSS-LANGUAGE / SECRET-FLOOR filtering (see
    # module docstring) happens per (file, name) occurrence, BEFORE the
    # max-magnitude merge -- a name filtered out of one file's occurrence can
    # still be kept from another (matching-family, non-junk, non-floor-
    # tripping) file's occurrence.
    cross_file_sizes: dict[str, int] = {}
    labels_filtered_junk: set[str] = set()
    labels_filtered_cross_language: set[str] = set()
    labels_filtered_secret_floor: set[str] = set()
    target_family = _language_family(target_lang_name)
    for rel, sizes in per_file.items():
        if rel == anchor:
            continue
        if rel in floor_tripped:
            # FLOOR-TRIPPING LABEL SOURCE EXCLUSION (see module docstring):
            # semantic_slice withholds this file as a neighbour in EVERY
            # lane, so any symbol defined only here can never appear in any
            # slice -- keeping it in must_include would be a guaranteed,
            # permanent miss mislabeled as a slicer defect, not a real signal.
            labels_filtered_secret_floor.update(sizes)
            continue
        rel_lang = spec_for(rel)
        rel_lang_name = rel_lang.name if rel_lang else None
        for name, size in sizes.items():
            if _is_junk_label(name):
                labels_filtered_junk.add(name)
                continue
            if rel_lang_name is None or _language_family(rel_lang_name) != target_family:
                labels_filtered_cross_language.add(name)
                continue
            cross_file_sizes[name] = max(cross_file_sizes.get(name, 0), size)

    if not cross_file_sizes:
        # Label hygiene filtered every cross-file candidate -- see CROSS-FILE
        # ONLY in the module docstring: minting must_include=[] here would be
        # exactly as vacuous (harness._recall's 1.0-for-empty) as the
        # single-file case already guarded above, just reached by a different
        # path. Diagnostics carry what was filtered even though there is no
        # task dict to carry it on, so the drop is reported, never silent.
        diagnostics["labels_filtered_junk"] = sorted(labels_filtered_junk)
        diagnostics["labels_filtered_cross_language"] = sorted(labels_filtered_cross_language)
        diagnostics["labels_filtered_secret_floor"] = sorted(labels_filtered_secret_floor)
        diagnostics["reason"] = (
            "label hygiene (junk/cross-language/secret-floor filters) "
            "dropped every cross-file candidate symbol; no valid label "
            "source remains"
        )
        return None, diagnostics

    ranked = sorted(cross_file_sizes, key=lambda n: (-cross_file_sizes[n], n))
    kept = sorted(ranked[:MUST_INCLUDE_CAP])
    dropped = len(ranked) - len(kept)

    target = (f"{anchor}::{next(iter(anchor_syms))}"
              if len(anchor_syms) == 1 else anchor)

    task = {
        "id": f"mint-{source}-{_short_hash(target, tuple(kept))}",
        "repo": _portable_repo_label(repo_root),
        "target": target,
        "must_include": kept,
        "must_include_dropped": dropped,
        "label_provenance": "independent_diff",
        "tier": "quarantine",
        "minted_at_sha": minted_at_sha,
        "confirmations": 0,
        "mint_source": source,
        "skipped_out_of_scope": skipped,
        "labels_filtered_junk": sorted(labels_filtered_junk),
        "labels_filtered_cross_language": sorted(labels_filtered_cross_language),
        "labels_filtered_secret_floor": sorted(labels_filtered_secret_floor),
        "skipped_secret_floor": floor_tripped,
    }
    return task, diagnostics


def _log_mint_diagnostics(diagnostics: dict, *, source: str, repo_root) -> None:
    """The "reported, never silent" channel for information that doesn't fit
    the two public mint_* entry points' pre-existing ``dict | None`` /
    ``list[dict]`` return shape (kept as-is because __main__.py's CLI wiring
    depends on it). A task that DID mint carries its own
    ``skipped_out_of_scope``/``must_include_dropped`` fields; this is what
    surfaces the same information -- and the no-task-minted ``reason`` -- for
    the cases where there is no task dict to carry it.
    """
    skipped = diagnostics.get("skipped_out_of_scope")
    if skipped:
        _LOG.info("mint(%s, %s): skipped out-of-scope changed file(s): %s",
                   source, repo_root, skipped)
    reason = diagnostics.get("reason")
    if reason:
        _LOG.info("mint(%s, %s): nothing minted -- %s", source, repo_root, reason)


def mint_task_from_landed_edit(report: dict, repo_root: str) -> dict | None:
    """Mint one quarantined task from a landed offload edit.

    ``report`` is (or contains the same "wrote" field as) the dict
    ``daedalus.offload.offload()`` returns for a write that passed
    verification. ``report["wrote"]`` IS ``disk_changed`` from
    offload.py:194-197 -- the files that ACTUALLY changed on disk, found by
    diffing a before/after content-hash snapshot taken around the run. That is
    the independent oracle here; the model's self-reported ``files_changed``
    is deliberately not read, for the same reason offload.py itself refuses to
    trust it for the write-mode gate.

    The edit is assumed uncommitted (offload writes straight into the working
    tree and never commits): "before" is read from git HEAD, "after" from the
    file currently on disk. A file the run created has no HEAD blob (before =
    None); a file it deleted has nothing left on disk (after = None). Returns
    ``None`` if there is nothing to mint: no writes reported, every write's
    content is symbol-identical to HEAD (e.g. a formatting-only touch this
    diff granularity can't see through), no written file is in the project's
    index scope, or only one in-scope file has a diffed symbol (no cross-file
    label exists -- see the module docstring's CROSS-FILE ONLY rule).
    """
    disk_changed = sorted({str(rel).replace("\\", "/") for rel in (report.get("wrote") or [])})
    if not disk_changed:
        return None
    sha = _resolve_sha(repo_root, "HEAD")
    files: dict[str, tuple[str | None, str | None]] = {}
    for rel in disk_changed:
        before = _show(repo_root, "HEAD", rel) if sha else None
        after = _read_worktree(repo_root, rel)
        files[rel] = (before, after)
    task, diagnostics = _mint_from_diffs(
        files, repo_root=repo_root, minted_at_sha=sha, source="landed_edit",
        in_scope=_in_scope_modules(repo_root),
    )
    _log_mint_diagnostics(diagnostics, source="landed_edit", repo_root=repo_root)
    return task


def mint_from_commit(repo_root: str, sha: str) -> list[dict]:
    """Mint quarantined task(s) from one real git commit.

    Same idea as ``mint_task_from_landed_edit``, but against history that
    already exists -- this is what lets minting be exercised deterministically
    in tests without a live offload run (a temp git fixture IS real git
    history; ``git show`` gives exact before/after text with no mocking).

    Currently mints a single aggregate task per commit (via the same
    ``_mint_from_diffs`` used for landed edits); returns a list so a future
    split (e.g. one task per hunk, for very large commits) is additive rather
    than a signature change. Returns ``[]`` for an unresolvable ref, a commit
    that touches no in-scope file, or one where only a single in-scope file
    has a diffed symbol (no cross-file label exists) -- never raises.
    """
    full_sha = _resolve_sha(repo_root, sha)
    if not full_sha:
        return []
    # --root: a commit with no parent (the very first commit of history) is
    # diffed against the empty tree instead of silently producing no rows.
    # No-op for every other commit (it already has a parent to diff against).
    name_status = _git(repo_root, "diff-tree", "--no-commit-id", "--name-status",
                       "-r", "--root", full_sha)
    if name_status is None:
        return []
    parent = _resolve_sha(repo_root, f"{full_sha}^")  # None for a root commit

    files: dict[str, tuple[str | None, str | None]] = {}
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rel = parts[-1].replace("\\", "/")  # tail path (new path for a rename)
        before = _show(repo_root, parent, rel) if parent else None
        after = _show(repo_root, full_sha, rel)
        files[rel] = (before, after)

    task, diagnostics = _mint_from_diffs(
        files, repo_root=repo_root, minted_at_sha=full_sha, source="commit",
        in_scope=_in_scope_modules(repo_root),
    )
    _log_mint_diagnostics(diagnostics, source="commit", repo_root=repo_root)
    return [task] if task else []


# --------------------------------------------------------------------------- #
# THIRD PROVENANCE: independent_text_diff -- data and knowledge plane labels   #
# --------------------------------------------------------------------------- #
#
# WHY A THIRD VALUE AND NOT AN EDIT. This module's own docstring says a
# contributor wanting richer minted labels "needs a THIRD provenance value, not
# a quiet edit to this one". This is that value. Nothing above this line
# changes: ``independent_diff`` keeps its symbol semantics, and no consumer can
# confuse a Markdown heading with a Python symbol because the provenance says
# which it is.
#
# WHY IT EXISTS. Gate 3's task corpus was measured (2026-09-09) as 27 code
# tasks drawn from this repository against 4 non-code tasks drawn from a
# six-file fixture. A cross-plane comparison over those two sets varies plane
# and corpus together, so any difference between them is unattributable -- the
# same defect class as the s08 false verdict. Minting non-code tasks from the
# same repository is what removes the confound.
#
# SCOPE IS A DIFFERENT QUESTION HERE, and reuses an existing answer.
# ``_in_scope_modules`` is the code index: 681 modules on this repository, of
# which zero are .md/.json/.yaml. A documentation file can never be in it, so
# the existing scope test would reject every candidate. The boundary used
# instead is ``structcore.index._IGNORE_DIRS`` -- the SAME exclusion the code
# index walks with -- plus generated artifacts and the fixture trees. Measured:
# that drops exactly one candidate of 130.
#
# INDEPENDENCE IS STRONGER HERE, AND MUST NOT BE OVERSTATED. The slicer never
# walks documentation, so a doc label cannot be reachable through the import
# graph -- the circularity ``independent_diff`` was built against does not
# apply. It does NOT make the label independent of the commit message, which is
# the query. That residual is inherited from the existing corpus, not fixed
# here, and no caller should read this provenance as claiming otherwise.

#: Extensions whose gold labels are free text rather than identifiers, split by
#: the plane ``eval.gate3.taskset.classify_task_plane`` will assign them.
_KNOWLEDGE_TEXT_EXTENSIONS = frozenset({".md", ".mdx", ".rst", ".txt", ".adoc"})
_DATA_TEXT_EXTENSIONS = frozenset({".json"})

#: Machine-written artifacts: the prose equivalent of a minified bundle. Real
#: text with mechanical structure that nobody authored and nobody searches for.
_GENERATED_TEXT_PATHS = frozenset({"docs/work-packets/index.json"})

#: Top-level trees that hold EXECUTION OUTPUT rather than the project's own
#: text. ``runs/`` carries receipts, evidence bundles and content-addressed
#: store locators -- a locator like
#: ``runs/.../store/locators/sha256/03/9c0c....json`` is real JSON with real
#: top-level keys and was authored by nobody. Found by acceptance criterion A7
#: (every minted target must still exist in the repository root): a locator
#: from a deleted run tripped it, which is the symptom, and being machine
#: output is the cause.
_GENERATED_TEXT_ROOTS = frozenset({"runs"})

_MD_HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*$", re.MULTILINE)


def _text_in_scope(rel: str) -> bool:
    """The scope boundary for prose and data, reusing the code index's own.

    A file is in scope when no directory component is ignored or dot-prefixed,
    it is not a generated artifact, and it is not fixture or example text --
    the last because minting from the fixture is exactly the confound this
    path exists to remove.
    """
    from daedalus.structcore.index import _IGNORE_DIRS

    parts = rel.split("/")
    if any(d in _IGNORE_DIRS or d.startswith(".") for d in parts[:-1]):
        return False
    if rel in _GENERATED_TEXT_PATHS or parts[0] in _GENERATED_TEXT_ROOTS:
        return False
    return "/fixtures/" not in rel and not rel.startswith("examples/")


def _text_plane_of(rel: str) -> str | None:
    suffix = Path(rel).suffix.lower()
    if suffix in _KNOWLEDGE_TEXT_EXTENSIONS:
        return "knowledge"
    if suffix in _DATA_TEXT_EXTENSIONS:
        return "data"
    return None


def _new_text_labels(rel: str, before: str | None, after: str | None) -> set[str]:
    """Labels present after and absent before. Never transitive, ever.

    Markdown: heading text. JSON: top-level object keys. A nested-key walk
    would re-introduce exactly the transitivity this module forbids, so a
    label is only ever something the diff itself put there.
    """
    plane = _text_plane_of(rel)
    if plane is None or after is None:
        return set()
    if plane == "knowledge":
        old = {m.group(1).strip() for m in _MD_HEADING_RE.finditer(before or "")}
        new = {m.group(1).strip() for m in _MD_HEADING_RE.finditer(after)}
        return {h for h in new - old if h}
    try:
        parsed_after = json.loads(after)
    except (ValueError, TypeError):
        return set()
    if not isinstance(parsed_after, dict):
        return set()
    old_keys: set[str] = set()
    if before:
        try:
            parsed_before = json.loads(before)
        except (ValueError, TypeError):
            parsed_before = None
        if isinstance(parsed_before, dict):
            old_keys = set(parsed_before)
    return {str(k) for k in set(parsed_after) - old_keys if str(k)}


def _mint_from_text_diffs(
    files,
    *,
    repo_root,
    minted_at_sha: str | None,
    source: str,
):
    """Mint one data/knowledge task from a commit's text diffs.

    Mirrors ``_mint_from_diffs``'s shape and honesty rules: out-of-scope files
    are recorded rather than dropped, floor-tripping files are excluded from
    both anchor and label roles, and ``must_include`` never contains a label
    from the target file.
    """
    diagnostics: dict = {"skipped_out_of_scope": [], "reason": None}

    scoped: dict = {}
    for rel, pair in files.items():
        if _text_plane_of(rel) is None:
            continue
        if not _text_in_scope(rel):
            diagnostics["skipped_out_of_scope"].append(rel)
            continue
        scoped[rel] = pair
    diagnostics["skipped_out_of_scope"] = sorted(diagnostics["skipped_out_of_scope"])

    floor_tripped = sorted(
        rel for rel in scoped
        if secret_floor_rule(rel, scoped[rel][1] or "") is not None
    )
    for rel in floor_tripped:
        scoped.pop(rel, None)
    diagnostics["skipped_secret_floor"] = floor_tripped

    labels_by_file = {
        rel: _new_text_labels(rel, before, after)
        for rel, (before, after) in scoped.items()
    }
    with_labels = {rel: names for rel, names in labels_by_file.items() if names}

    if len(with_labels) < 2:
        diagnostics["reason"] = (
            "fewer than two in-scope text files carry a new label, so no "
            "cross-file label exists"
        )
        return None, diagnostics

    # The anchor is the file with the FEWEST new labels: it is the one whose own
    # content explains the least, so the labels that must be retrieved from
    # elsewhere carry the most of the task. Ties break on path for determinism.
    anchor = sorted(with_labels, key=lambda rel: (len(with_labels[rel]), rel))[0]

    cross_file: set[str] = set()
    for rel, names in with_labels.items():
        if rel != anchor:
            cross_file |= names
    # A label the anchor also introduces is recalled by construction.
    cross_file -= with_labels[anchor]

    if not cross_file:
        diagnostics["reason"] = "every label is also introduced by the anchor file"
        return None, diagnostics

    ranked = sorted(cross_file)
    kept = ranked[:MUST_INCLUDE_CAP]
    task = {
        "id": "mint-text-%s-%s" % (source, _short_hash(anchor, tuple(kept))),
        "repo": _portable_repo_label(repo_root),
        "target": anchor,
        "must_include": kept,
        "must_include_dropped": len(ranked) - len(kept),
        "label_provenance": "independent_text_diff",
        "tier": "quarantine",
        "minted_at_sha": minted_at_sha,
        "confirmations": 0,
        "mint_source": source,
        "text_plane": _text_plane_of(anchor),
        "skipped_out_of_scope": diagnostics["skipped_out_of_scope"],
        "skipped_secret_floor": floor_tripped,
    }
    return task, diagnostics


def mint_text_from_commit(repo_root: str, sha: str) -> list:
    """Mint quarantined data/knowledge task(s) from one real git commit.

    The ``independent_text_diff`` sibling of :func:`mint_from_commit`. Returns
    ``[]`` -- never raises -- for an unresolvable ref, a commit touching no
    in-scope text file, or one where no cross-file label exists.
    """
    full_sha = _resolve_sha(repo_root, sha)
    if not full_sha:
        return []
    name_status = _git(repo_root, "diff-tree", "--no-commit-id", "--name-status",
                       "-r", "--root", full_sha)
    if name_status is None:
        return []
    parent = _resolve_sha(repo_root, "%s^" % full_sha)

    files: dict = {}
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rel = parts[-1].replace("\\", "/")
        files[rel] = (
            _show(repo_root, parent, rel) if parent else None,
            _show(repo_root, full_sha, rel),
        )

    task, diagnostics = _mint_from_text_diffs(
        files, repo_root=repo_root, minted_at_sha=full_sha, source="commit",
    )
    _log_mint_diagnostics(diagnostics, source="text-commit", repo_root=repo_root)
    return [task] if task else []


def confirm_task(task: dict) -> dict:
    """Record one independent confirmation of a minted task, in place.

    Promotes ``task["tier"]`` from ``"quarantine"`` to ``"primary"`` once
    ``confirmations`` reaches ``MINT_CONFIRM_THRESHOLD``. A no-op on a task
    that is not currently quarantined: a primary task doesn't need more
    confirming, and "confirming" a hand_reachable task is meaningless -- it
    was never gated in the first place. Returns the same (mutated) dict for
    convenient chaining; callers that need the pre-mutation task should copy
    it first.
    """
    if task.get("tier") != "quarantine":
        return task
    task["confirmations"] = int(task.get("confirmations", 0)) + 1
    if task["confirmations"] >= MINT_CONFIRM_THRESHOLD:
        task["tier"] = "primary"
    return task


def load_minted_tasks(path: str | None = None) -> list[dict]:
    """Read the persisted mint store, or ``[]`` if it does not exist yet.

    This is the ONLY load path by which a minted task can reach
    ``daedalus.eval.harness.all_tasks()`` and therefore any go/no-go number --
    without it, ``mint_task_from_landed_edit``/``mint_from_commit`` produced
    dicts that lived only as long as the caller's local variable. Sorted by id
    for deterministic iteration (PYTHONHASHSEED-independent), matching the
    rest of this repo's output-determinism rule."""
    p = path or DEFAULT_MINT_STORE_PATH
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return sorted(data.get("tasks", []), key=lambda t: t["id"])


#: Bumped when a threat check changes meaning, so a stored audit can never be
#: read as if it had been produced by today's rules. An audit without a version
#: is not trusted.
NOISE_AUDIT_VERSION = 1

#: Path fragments that mark a generated artifact (threat T3). Deliberately
#: literal and small, mirroring the discipline of ``separate_indices``'s
#: extension sets: auditable from one place, no globbing, no content sniffing.
_GENERATED_PATH_MARKERS = ("dist/", "build/", "node_modules/", ".min.",
                           "generated", "_pb2", "runs/", "lock")


def _structural_dump(src: str) -> str | None:
    """Python source reduced to structure: AST with docstrings dropped.

    Two sources with the same dump differ only in formatting, comments and
    docstrings -- exactly threat T1's "reformat-only touch that happens to
    shift a docstring". Returns ``None`` when the source does not parse, which
    is reported as undecided rather than guessed at.
    """
    import ast

    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    try:
        return ast.dump(tree, annotate_fields=False)
    except RecursionError:
        return None


def audit_noise_threats(task: dict, repo_root) -> dict:
    """Check the three threats ``MINT_CONFIRM_THRESHOLD``'s comment names.

    WHY THIS EXISTS. That comment justifies the threshold by naming exactly
    three ways a single mint could be noise -- T1 a reformat-only touch that
    shifts a docstring, T2 a rename that round-trips to byte-identical source
    under a new name, T3 a generated-file regen -- and then predicts the
    threshold stays "low enough to actually accumulate ... instead of never
    firing". Measured 2026-09-10: ZERO confirmations across 400 first-parent
    commits and all 48 stored tasks. The prediction is false; the gate never
    opens, so it never admits a task and never validates one either.

    Recurrence was only ever a PROXY for "these three are absent". This checks
    them directly. See docs/G3_THE_QUARANTINE_GATE_CANNOT_OPEN_20260910.md.

    WHAT IT DOES NOT COVER, stated because it is the whole limit of the
    argument: the three NAMED threats, and nothing else. Recurrence in
    principle also guards against threats nobody wrote down; in practice it
    fires never, so it guards nothing. But "the named threats are absent" is a
    strictly smaller claim than "this label is safe", and a caller must not
    round one to the other. That is why the result is recorded as its own
    witness kind rather than incrementing ``confirmations``: a stored
    confirmation count whose entries mean two different things is a count of
    nothing.

    Verdict vocabulary, per threat:
      ``impossible`` -- ruled out by construction, not by inspection
      ``clean``      -- checked and absent
      ``fired``      -- the threat is present; the task is noise
      ``undecided``  -- cannot be checked here; never silently treated as clean
    """
    sha = task.get("minted_at_sha")
    rel = (task.get("target") or "").split("::", 1)[0]
    out = {"version": NOISE_AUDIT_VERSION, "minted_at_sha": sha}

    # T3 is decidable from the path alone, always, and independently of git.
    low = rel.lower()
    out["t3_generated"] = "fired" if any(m in low for m in _GENERATED_PATH_MARKERS) else "clean"

    if not sha or not rel:
        out["t1_cosmetic"] = out["t2_rename_roundtrip"] = "undecided"
        # A fired T3 decides the verdict even here: a generated artifact is
        # noise whatever its provenance turns out to be, and letting an
        # undecidable T1 outrank it would quietly downgrade a KNOWN threat to
        # an unknown one.
        out["verdict"] = "fired" if out["t3_generated"] == "fired" else "undecided"
        return out

    after = _show(repo_root, sha, rel)
    if after is None:
        # The target did not exist at the revision the task claims to come
        # from. Measured on two stored tasks whose paths are post-relocation
        # while their SHAs predate the commits that created them. The labels
        # may be fine; the PROVENANCE cannot be checked, and an entry whose
        # provenance cannot be checked must not sit indistinguishable from one
        # whose can.
        out["t1_cosmetic"] = out["t2_rename_roundtrip"] = "undecided"
        out["verdict"] = ("fired" if out["t3_generated"] == "fired"
                          else "unverifiable_provenance")
        return out

    parent = _resolve_sha(repo_root, f"{sha}^")
    before = _show(repo_root, parent, rel) if parent else None

    if before is None:
        # The anchor was ADDED by this commit. T1 and T2 both presuppose a
        # prior version of the file: you cannot reformat, or rename within,
        # something that did not exist. Ruled out by construction.
        out["t1_cosmetic"] = out["t2_rename_roundtrip"] = "impossible"
    elif not rel.endswith(".py"):
        # Markdown and JSON need their own normalizer. Not built here, and
        # reported as undecided rather than assumed clean.
        out["t1_cosmetic"] = out["t2_rename_roundtrip"] = "undecided"
    else:
        da, db = _structural_dump(after), _structural_dump(before)
        if da is None or db is None:
            out["t1_cosmetic"] = out["t2_rename_roundtrip"] = "undecided"
        else:
            # T1: the bytes changed but the structure did not -> cosmetic.
            out["t1_cosmetic"] = "fired" if (da == db and after != before) else "clean"
            # T2: a label names a symbol whose structure already existed under
            # a different name in the parent -- the "rename that round-trips to
            # byte-identical source" case.
            out["t2_rename_roundtrip"] = _audit_rename_roundtrip(
                task, before, after)

    decided = [out["t1_cosmetic"], out["t2_rename_roundtrip"], out["t3_generated"]]
    if "fired" in decided:
        out["verdict"] = "fired"
    elif "undecided" in decided:
        out["verdict"] = "undecided"
    else:
        out["verdict"] = "clean"
    return out


def _audit_rename_roundtrip(task: dict, before: str, after: str) -> str:
    """T2: is a minted label just an old symbol wearing a new name?"""
    import ast

    def bodies(src):
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError):
            return None
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stripped = ast.parse("pass")
                stripped.body = list(node.body)
                dumped = _structural_dump(ast.unparse(stripped))
                if dumped is not None:
                    found[node.name] = dumped
        return found

    old, new = bodies(before), bodies(after)
    if old is None or new is None:
        return "undecided"
    old_shapes = {v: k for k, v in old.items()}
    for label in task.get("must_include") or ():
        shape = new.get(label)
        if shape is None:
            continue
        twin = old_shapes.get(shape)
        if twin is not None and twin != label:
            return "fired"
    return "clean"


def promotion_witness(task: dict) -> str | None:
    """Which evidence, if any, entitles ``task`` to leave quarantine.

    Two witnesses, deliberately NOT merged into one counter:

    ``recurrence``   -- ``confirmations >= MINT_CONFIRM_THRESHOLD``, the
                        original rule, unchanged in meaning.
    ``noise_audit``  -- every named threat checked and absent, at the current
                        ``NOISE_AUDIT_VERSION``.

    The kind is returned rather than a bare boolean so a consumer can filter to
    one. A comparison that wants only the older, broader witness can still
    have it; what it cannot do is read a mixed population as homogeneous.
    """
    if int(task.get("confirmations") or 0) >= MINT_CONFIRM_THRESHOLD:
        return "recurrence"
    audit = task.get("noise_audit")
    if (isinstance(audit, dict)
            and audit.get("version") == NOISE_AUDIT_VERSION
            and audit.get("verdict") == "clean"):
        return "noise_audit"
    return None


def _refuse_nonportable_repos(tasks: list[dict]) -> None:
    """Refuse to write a task whose ``repo`` is an absolute host path into the
    repository's OWN committed corpus.

    This is the boundary the 2026-09-09 defect crossed. Minting a task against
    a temp fixture is fine and tests do it; what is not fine is that value
    reaching ``minted_tasks.json``, which is committed, shared, and supposed to
    be a frozen public task set. An absolute path survives exactly one machine:
    the store shipped 17 tasks pinned to ``C:/Users/nukei/...`` that raised on
    every resolution attempt here, and 31 pinned to a disposable worktree.

    SCOPE, stated rather than implied: this fires only when writing
    ``DEFAULT_MINT_STORE_PATH``. A caller writing its own scratch store at some
    other path is not policed, because no mechanism here can tell which files a
    repository commits, and pretending otherwise would advertise a guarantee
    this does not have. It covers the whole of the surface where the defect
    actually occurred, which is one file.
    """
    from .tasks import resolve_task_repo

    bad = []
    for task in tasks:
        repo = task.get("repo")
        if not isinstance(repo, str):
            continue
        # An ALLOWLIST, not a path-shape test. The first version rejected
        # ``os.path.isabs`` only, which let ``../../nukei/Desktop/agent_env``
        # through untouched -- just as unportable, and not absolute. Asking
        # "does this resolve as a declared label" refuses both, and refuses
        # anything else unportable nobody has thought of yet.
        if os.path.isabs(repo) or os.sep in repo or "/" in repo:
            bad.append(repo)
            continue
        try:
            resolve_task_repo(repo)
        except Exception:
            bad.append(repo)
    bad = sorted(set(bad))
    if bad:
        raise ValueError(
            "refusing to persist %d task repo reference(s) that are not a "
            "portable label: %s. Use a label resolve_task_repo understands "
            "(agent_env / sunny_garden / fourfold_wiki_app / a registered "
            "project) -- see _portable_repo_label. A corpus that names one "
            "machine's filesystem is not reproducible on any other."
            % (len(bad), ", ".join(repr(b) for b in bad)))


def save_minted_tasks(tasks: list[dict], path: str | None = None) -> str:
    """Overwrite the mint store with exactly ``tasks``. Deterministic
    formatting (sorted keys, sorted by id) so the diff is meaningful in
    review -- same contract as ``harness.write_baseline``. Returns the path
    written."""
    p = path or DEFAULT_MINT_STORE_PATH
    if os.path.normcase(os.path.realpath(p)) == _COMMITTED_STORE_PATH:
        _refuse_nonportable_repos(tasks)
    ordered = sorted(tasks, key=lambda t: t["id"])
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"schema": 1, "tasks": ordered}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return p


def add_minted_task(task: dict, path: str | None = None) -> str:
    """Persist ``task`` into the mint store, keyed by id.

    Idempotent on RE-MINTING THE SAME COMMIT: same target + same must_include
    yields the same id (the content hash in ``_mint_from_diffs``), and if the
    incoming task carries the same ``minted_at_sha`` as the stored one it
    overwrites in place. Re-running ``--mint-commit`` on one SHA, or a rebase
    reproducing an identical patch, must not inflate anything.

    CONFIRMS ON AN INDEPENDENT MINT. When the same id arrives from a
    *different* ``minted_at_sha``, that is the thing
    ``MINT_CONFIRM_THRESHOLD``'s rationale describes -- "three independent
    mints landing on the same must_include set" -- so it records a
    confirmation rather than silently overwriting.

    Why this is here rather than left to ``--confirm-mint``: the threshold's
    stated semantics and its mechanism had drifted apart.
    ``confirm_minted_task`` increments a counter for a task id and verifies
    nothing about independence, and ``__main__`` states plainly that it has no
    automatic caller. A task therefore reached ``primary`` -- and influenced a
    go/no-go number -- on three unverified operator assertions. A differing
    ``minted_at_sha`` is checkable evidence that two mints were independent,
    so the confirmation now rests on something the store can see.
    ``--confirm-mint`` keeps working unchanged for the operator path.

    Returns the path written.
    """
    stored = load_minted_tasks(path)
    by_id = {t["id"]: t for t in stored}
    existing = by_id.get(task["id"])

    if existing is None:
        by_id[task["id"]] = task
        return save_minted_tasks(list(by_id.values()), path)

    same_source = existing.get("minted_at_sha") == task.get("minted_at_sha")
    if same_source:
        # The same commit, re-minted. Refresh the record, count nothing.
        task = dict(task)
        task["confirmations"] = existing.get("confirmations", 0)
        task["tier"] = existing.get("tier", task.get("tier", "quarantine"))
        by_id[task["id"]] = task
        return save_minted_tasks(list(by_id.values()), path)

    # An independent mint of the same label set. Keep the FIRST record -- its
    # minted_at_sha is the provenance of the original observation -- and
    # record that a second source agreed, retaining the agreeing shas so the
    # claim is inspectable rather than a bare integer.
    agreeing = list(existing.get("confirmed_by_sha") or [])
    incoming_sha = task.get("minted_at_sha")
    if incoming_sha and incoming_sha not in agreeing:
        agreeing.append(incoming_sha)
        existing["confirmed_by_sha"] = agreeing
        confirm_task(existing)
    by_id[task["id"]] = existing
    return save_minted_tasks(list(by_id.values()), path)


def confirm_minted_task(task_id: str, path: str | None = None) -> dict | None:
    """Load the store, confirm ONE task by id (see ``confirm_task``), persist
    the mutation, and return the updated task -- or ``None`` if ``task_id`` is
    not in the store. The only durable way a quarantined mint accumulates
    confirmations and eventually promotes to primary; ``confirm_task`` alone
    only mutates an in-memory dict that would otherwise evaporate."""
    tasks = load_minted_tasks(path)
    for t in tasks:
        if t["id"] == task_id:
            confirm_task(t)
            save_minted_tasks(tasks, path)
            return t
    return None
