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
recall number until ``confirm_task`` has been called on them
``MINT_CONFIRM_THRESHOLD`` times -- see that constant's docstring for the
rationale. Aggregation/enforcement of the tier gate is the eval harness's job
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
minting).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path

from daedalus.structcore.index import cached_index
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import extract_units

_LOG = logging.getLogger(__name__)

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
    anchor_pool = existing or per_file
    anchor = sorted(anchor_pool, key=lambda r: (-len(anchor_pool[r]), r))[0]
    anchor_syms = per_file[anchor]

    # Cross-file only: a symbol NAME can repeat across files (different
    # symbol, same name) -- keep the larger magnitude rather than letting one
    # silently clobber the other, matching _diffed_symbols' own duplicate-name
    # handling. Guaranteed non-empty: the len(per_file) < 2 check above means
    # at least one OTHER (non-anchor) entry exists in per_file, and every
    # per_file entry is non-empty by construction (the `if sizes:` guard when
    # per_file was built).
    cross_file_sizes: dict[str, int] = {}
    for rel, sizes in per_file.items():
        if rel == anchor:
            continue
        for name, size in sizes.items():
            cross_file_sizes[name] = max(cross_file_sizes.get(name, 0), size)

    ranked = sorted(cross_file_sizes, key=lambda n: (-cross_file_sizes[n], n))
    kept = sorted(ranked[:MUST_INCLUDE_CAP])
    dropped = len(ranked) - len(kept)

    target = (f"{anchor}::{next(iter(anchor_syms))}"
              if len(anchor_syms) == 1 else anchor)

    task = {
        "id": f"mint-{source}-{_short_hash(target, tuple(kept))}",
        "repo": str(Path(repo_root).resolve()).replace("\\", "/"),
        "target": target,
        "must_include": kept,
        "must_include_dropped": dropped,
        "label_provenance": "independent_diff",
        "tier": "quarantine",
        "minted_at_sha": minted_at_sha,
        "confirmations": 0,
        "mint_source": source,
        "skipped_out_of_scope": skipped,
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


def save_minted_tasks(tasks: list[dict], path: str | None = None) -> str:
    """Overwrite the mint store with exactly ``tasks``. Deterministic
    formatting (sorted keys, sorted by id) so the diff is meaningful in
    review -- same contract as ``harness.write_baseline``. Returns the path
    written."""
    p = path or DEFAULT_MINT_STORE_PATH
    ordered = sorted(tasks, key=lambda t: t["id"])
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"schema": 1, "tasks": ordered}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return p


def add_minted_task(task: dict, path: str | None = None) -> str:
    """Persist ``task`` into the mint store, keyed by id. Idempotent: minting
    the same diff twice (same target + same must_include, via the content
    hash in ``_mint_from_diffs``) yields the same id and overwrites in place
    rather than duplicating -- re-running a mint (e.g. after a rebase that
    reproduces an identical patch) must not inflate the quarantine count.
    Returns the path written."""
    by_id = {t["id"]: t for t in load_minted_tasks(path)}
    by_id[task["id"]] = task
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
