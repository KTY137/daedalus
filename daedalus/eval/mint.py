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
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import extract_units

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


def _diffed_symbols(rel: str, before_text: str | None, after_text: str | None) -> list[str]:
    """Symbol names whose extracted source differs, plus pure adds/removes.

    Matched by NAME against a (name -> sorted source list) map rather than a
    single name->source dict, so duplicate names (same-named methods on
    sibling classes, nested closures) don't silently clobber each other and
    under-report a real change. A file with no language spec (unsupported
    extension) contributes nothing -- there is no unit-level ground truth to
    diff, only whole-file text, and this module deliberately doesn't fall back
    to that (a whole-file "changed" label would be far too coarse to be an
    honest must_include).
    """
    spec = spec_for(rel)
    if spec is None:
        return []
    before_units = extract_units(rel, before_text or "", spec)
    after_units = extract_units(rel, after_text or "", spec)
    before_map: dict[str, list[str]] = {}
    for u in before_units:
        before_map.setdefault(u.name, []).append(u.source)
    after_map: dict[str, list[str]] = {}
    for u in after_units:
        after_map.setdefault(u.name, []).append(u.source)
    changed = [name for name in (set(before_map) | set(after_map))
               if sorted(before_map.get(name, [])) != sorted(after_map.get(name, []))]
    return sorted(changed)


def _mint_from_diffs(
    files: dict[str, tuple[str | None, str | None]], *,
    repo_root, minted_at_sha: str | None, source: str,
) -> dict | None:
    """Build ONE aggregate quarantined task from a set of file diffs.

    ``files`` maps rel path -> (before_text, after_text); ``None`` on either
    side means the path did not exist there (a create or a delete).

    The task's ``target`` (the anchor the slicer will be pointed at) is the
    changed file that still EXISTS after the edit with the most diffed
    symbols, ties broken by path for determinism -- a deleted file cannot be a
    slice target. If literally everything touched was deleted, there is no
    valid anchor and this returns ``None`` rather than minting an unusable
    task. ``must_include`` still aggregates every diffed symbol across every
    touched file (including deletions) -- an edit that spans multiple files
    genuinely needs all of them to reason about, and a slice from a single
    anchor file failing to reach a symbol in an unrelated file is exactly the
    kind of miss this module exists to surface (see the module docstring: the
    static import graph is NOT consulted to "help" this along).
    """
    per_file: dict[str, list[str]] = {}
    for rel, (before_text, after_text) in files.items():
        syms = _diffed_symbols(rel, before_text, after_text)
        if syms:
            per_file[rel] = syms
    if not per_file:
        return None

    existing = {rel: syms for rel, syms in per_file.items() if files[rel][1] is not None}
    anchor_pool = existing or per_file
    anchor = sorted(anchor_pool, key=lambda r: (-len(anchor_pool[r]), r))[0]
    anchor_syms = per_file[anchor]

    must_include = sorted({s for syms in per_file.values() for s in syms})
    # A single changed symbol in a single touched file earns symbol-level
    # precision; anything broader (multiple symbols, or multiple files) stays
    # file-level, since a symbol-scoped target can't honestly represent labels
    # that live outside its own one-hop slice.
    target = (f"{anchor}::{anchor_syms[0]}"
              if len(per_file) == 1 and len(anchor_syms) == 1 else anchor)

    return {
        "id": f"mint-{source}-{_short_hash(target, tuple(must_include))}",
        "repo": str(Path(repo_root).resolve()).replace("\\", "/"),
        "target": target,
        "must_include": must_include,
        "label_provenance": "independent_diff",
        "tier": "quarantine",
        "minted_at_sha": minted_at_sha,
        "confirmations": 0,
        "mint_source": source,
    }


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
    ``None`` if there is nothing to mint (no writes reported, or every write's
    content is symbol-identical to HEAD -- e.g. a formatting-only touch this
    diff granularity can't see through, or the file has no language spec).
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
    return _mint_from_diffs(files, repo_root=repo_root, minted_at_sha=sha, source="landed_edit")


def mint_from_commit(repo_root: str, sha: str) -> list[dict]:
    """Mint quarantined task(s) from one real git commit.

    Same idea as ``mint_task_from_landed_edit``, but against history that
    already exists -- this is what lets minting be exercised deterministically
    in tests without a live offload run (a temp git fixture IS real git
    history; ``git show`` gives exact before/after text with no mocking).

    Currently mints a single aggregate task per commit (via the same
    ``_mint_from_diffs`` used for landed edits); returns a list so a future
    split (e.g. one task per hunk, for very large commits) is additive rather
    than a signature change. Returns ``[]`` for an unresolvable ref or a
    commit whose diff yields nothing worth minting -- never raises.
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

    task = _mint_from_diffs(files, repo_root=repo_root, minted_at_sha=full_sha, source="commit")
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
