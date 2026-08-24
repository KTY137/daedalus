"""THE BOOTSTRAP ENTRY POINT -- one attempt, driven to the gate, with a receipt.

WHY THIS FILE EXISTS AT ALL. The first real bootstrap of this repository was
driven by a throwaway script that had **no** ``if __name__ == "__main__":``
guard. ``daedalus.structcore.index`` uses a spawn-based
``ProcessPoolExecutor``, and on Windows every spawned worker re-imports the
main module -- so each worker re-ran the driver's top level and started its own
attempt. Ten attempts (intent_ids 56-64) ran in parallel; eight died of
``TimeoutError`` from their own contention. Nothing escaped the worktrees and
the primary checkout was untouched, but the run measured nothing it set out to
measure. A guarded, committed entry point is the fix, and it is committed
precisely so that the next person does not write the unguarded one again.

WHY ``tools/`` AND NOT A ``daedalus.spine`` SUBCOMMAND.

* ``daedalus/spine/bootstrap.py`` ALREADY has a correct ``main()`` behind a
  ``__main__`` guard. ``python -m daedalus.spine.bootstrap`` is not the bug and
  does not need replacing. A second product entry point with slightly different
  semantics is the "second, drifting copy" failure that ``bootstrap.py``'s own
  docstring warns about for its derived sources -- the same argument applies to
  the thing that starts the loop.
* ``daedalus/spine/`` is a declared ``high_risk_path`` in this repository's own
  ``.agentenv/agentenv.json``. A measurement harness does not belong behind a
  fence whose purpose is to keep candidate writes out.
* Every other harness that produces a receipt this repository trusts already
  lives here: ``tools/gate_discrimination.py``, ``tools/operability_drill.py``,
  ``tools/self_test.py``, ``tools/system_check.py``. This is one of those, not
  a product feature.

WHAT IT ADDS OVER ``shadow_run`` -- three things, each forced by a measured
defect rather than by taste.

1. A WORKTREE-LOCAL POLICY STAMP. ``offload()`` reads ``test_command`` from the
   TARGET repo's ``.agentenv/agentenv.json`` -- which, inside an attempt, is
   the worktree's own copy -- and passes it to ``verifier.verify()``, whose
   ``timeout_s`` default is 120. The committed ``test_command`` is the whole
   suite. The whole suite does not finish in 120 s. So at that revision the
   committed configuration could not pass, verify always failed, the write was
   always rolled back, the artefact was always empty, and
   ``TaskAttempt._run_with_ledger`` SKIPS the gate on an empty artefact -- the
   gate never ran. ``--worktree-test-command`` writes a faster command into the
   WORKTREE's copy only, before ``offload`` reads it, and restores the original
   bytes afterwards, verified by sha256 both ways. It never touches the primary
   checkout's config, and because the restore happens before
   ``TaskAttempt._capture_patch`` runs, the stamp cannot appear in the candidate
   patch. The receipt records the override verbatim; a run that used one is not
   a run of the committed configuration and must not be reported as one.

2. A PROMOTION VERDICT ON BOTH AXES. ``gate_discrimination()`` is asked twice:
   once against the revision the candidate was actually BUILT on
   (``base_revision``), and once against the primary checkout's LIVE head at the
   moment the attempt finished. In a repository where several agents commit
   concurrently these differ routinely -- measured: a 14-minute discrimination
   measurement started at ``f18ff5c`` and a new commit landed 2 minutes into it,
   so the receipt was stale before it was written. Reporting only one of the two
   numbers would hide either the guard working or the guard firing spuriously.

3. A PRIMARY-CHECKOUT FINGERPRINT, taken before and after. ``TaskAttempt`` has
   no apply path, which is a property of the code; this is the independent
   observation that says so for THIS run. HEAD, tracked and non-ignored
   untracked status (with path-content digests), and the surviving
   ``daedalus-attempt*`` branch list are recorded on both sides.

WHAT IT REFUSES TO DO. It does not promote, it has no ``--promote`` flag, and
it does not apply a patch. The receipt identifies the effective gate kind,
scope, argv and output digest. For the default pytest gate, non-empty
``gate_paths`` mean SCOPED; that green is not the whole-suite green that
production's ``gate_paths: []`` candidates would demand. An explicit
``--gate-command`` is labelled ``custom-command`` and makes no pytest or
whole-suite claim.

    python tools/bootstrap_receipt.py --single --live --local-only \
        --repo-root C:/path/to/target \
        --instruction "..." --paths docs/X.md --gate-paths tests/test_a.py \
        --worktree-test-command "python -m pytest tests/test_a.py -q"

    python tools/bootstrap_receipt.py --concurrent 4 ...   # contention
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

REPO_CONFIG_REL = ".agentenv/agentenv.json"
DEFAULT_RUN_REL = Path("runs") / "spine" / "bootstrap"
DEFAULT_ARTIFACT_REL = DEFAULT_RUN_REL / "patches"
DEFAULT_LEDGER_REL = Path("runs") / "spine" / "spine.sqlite3"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_CANDIDATE = 2


# --------------------------------------------------------------------------- #
# observing the primary checkout from outside                                  #
# --------------------------------------------------------------------------- #
def _git_bytes(args: Sequence[str], cwd: Path) -> bytes:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          timeout=120)
    return proc.stdout


def _git_text(args: Sequence[str], cwd: Path) -> str:
    return _git_bytes(args, cwd).decode("utf-8", "replace")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _status_entries(raw: bytes) -> list[dict[str, str]]:
    """Parse ``git status --porcelain=v1 -z`` without guessing at spaces.

    Under ``-z`` paths are literal NUL-delimited bytes. Rename/copy records carry
    a second path token; keeping it explicitly avoids the human-format
    ``old -> new`` ambiguity and makes filenames containing whitespace safe.
    """
    records = raw.split(b"\0")
    out: list[dict[str, str]] = []
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not rec:
            continue
        if len(rec) < 4 or rec[2:3] != b" ":
            continue
        code = rec[:2].decode("ascii", "replace")
        path = rec[3:].decode("utf-8", "replace").replace("\\", "/")
        row = {"code": code, "path": path}
        if ("R" in code or "C" in code) and i < len(records):
            old = records[i]
            i += 1
            row["orig_path"] = old.decode("utf-8", "replace").replace("\\", "/")
        out.append(row)
    return sorted(out, key=lambda row: (row["path"], row["code"],
                                       row.get("orig_path", "")))


def _path_digest(repo_root: Path, rel: str) -> str | None:
    """Digest one status path, including collapsed untracked directories.

    ``--untracked-files=normal`` deliberately reports ``?? app/`` rather than
    thousands of files. For such a directory we ask Git for the non-ignored
    files below it and hash names plus bytes. This catches a candidate leaking
    ``app/probe.ts`` into an already-untracked ``app/`` while keeping ignored
    dependency trees such as ``node_modules`` out of both the receipt and scan.
    """
    target = repo_root / rel.rstrip("/")
    if target.is_file():
        try:
            return hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            return None
    if not target.is_dir():
        return None

    listed = _git_bytes(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", rel.rstrip("/")], repo_root)
    names = sorted(
        p.decode("utf-8", "replace").replace("\\", "/")
        for p in listed.split(b"\0") if p)
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("utf-8", "replace"))
        digest.update(b"\0")
        path = repo_root / name
        try:
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def primary_fingerprint(repo_root: Path) -> dict:
    """What the primary checkout looks like from the outside, right now.

    Ignored files remain excluded, but untracked files do not: a candidate that
    creates a new file in the primary checkout is still a leak. ``normal`` keeps
    large untracked trees collapsed, and ``_path_digest`` binds their non-ignored
    contents so a change under an already-present directory remains visible.
    """
    repo_root = Path(repo_root).resolve()
    head = _git_text(["rev-parse", "HEAD"], repo_root).strip()
    status_raw = _git_bytes(
        ["status", "--porcelain=v1", "-z", "--untracked-files=normal"],
        repo_root)
    entries = _status_entries(status_raw)
    path_digests = {
        row["path"]: _path_digest(repo_root, row["path"])
        for row in entries
    }
    diff = _git_text(["diff", "--stat"], repo_root)
    branches = [b.strip().lstrip("* ") for b in
                _git_text(["branch", "--list", "daedalus-attempt*"],
                          repo_root).splitlines() if b.strip()]
    return {
        "head": head,
        # Kept for receipt readers written before untracked evidence landed.
        "tracked_status": [f"{row['code']} {row['path']}" for row in entries],
        "status_entries": entries,
        "status_path_sha256": path_digests,
        "tracked_status_sha256": hashlib.sha256(status_raw).hexdigest(),
        "diff_stat_sha256": _sha(diff),
        "attempt_branches": branches,
    }


def _leak_check(before: dict, after: dict, candidate_paths: Sequence[str]) -> dict:
    """Did THIS attempt's bytes reach the primary checkout?

    ``primary_quiet`` -- "nothing tracked changed at all" -- is the check you
    want in a quiet repository and the wrong one here: measured, six other
    agents were editing this tree while the attempt ran, so three unrelated
    files went dirty between the two fingerprints and a bare equality check
    reported a leak that did not happen. Equality is still recorded, because a
    quiet tree is stronger evidence when you can get it -- but the ATTRIBUTABLE
    claim is ``candidate_paths_leaked``: of the paths this candidate actually
    wrote inside its worktree, which ones changed state in the primary
    checkout? That set being empty is a statement about this attempt. The
    delta is reported in full either way, so a reader can attribute every
    entry instead of trusting a boolean.
    """
    def _paths(fp: dict) -> dict[str, dict[str, str | None]]:
        out: dict[str, dict[str, str | None]] = {}
        entries = fp.get("status_entries")
        if isinstance(entries, list):
            for row in entries:
                if not isinstance(row, dict) or not row.get("path"):
                    continue
                path = str(row["path"]).replace("\\", "/")
                out[path] = {
                    "code": str(row.get("code") or ""),
                    "digest": (fp.get("status_path_sha256") or {}).get(path),
                }
            return out
        # Backward-compatible input shape used by old receipts and small tests.
        for line in fp.get("tracked_status") or ():
            if len(line) >= 4 and line[2] == " ":
                path = line[3:].strip().replace("\\", "/")
                out[path] = {"code": line[:2], "digest": None}
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                out[parts[1].strip().replace("\\", "/")] = {
                    "code": parts[0], "digest": None}
        return out

    b, a = _paths(before), _paths(after)
    appeared = sorted(set(a) - set(b))
    disappeared = sorted(set(b) - set(a))
    changed_state = sorted(
        p for p in (set(a) & set(b)) if a[p]["code"] != b[p]["code"])
    content_changed = sorted(
        p for p in (set(a) & set(b))
        if a[p].get("digest") != b[p].get("digest"))
    delta = (set(appeared) | set(disappeared) | set(changed_state)
             | set(content_changed))
    cand = {str(p).replace("\\", "/") for p in candidate_paths}

    def _overlap(candidate: str, evidence: str) -> bool:
        c = candidate.strip("/").lower()
        e = evidence.strip("/").lower()
        return bool(c and e and (
            c == e or c.startswith(e + "/") or e.startswith(c + "/")))

    evidence_by_candidate = {
        c: sorted(e for e in delta if _overlap(c, e))
        for c in sorted(cand)
    }
    leaked = sorted(c for c, evidence in evidence_by_candidate.items() if evidence)
    return {
        "head_unchanged": before["head"] == after["head"],
        "appeared": appeared,
        "disappeared": disappeared,
        "changed_state": changed_state,
        "content_changed": content_changed,
        "candidate_paths": sorted(cand),
        "candidate_path_evidence": evidence_by_candidate,
        "candidate_paths_leaked": leaked,
        "no_candidate_path_reached_the_primary_checkout": not leaked,
        "attempt_branches_after": after["attempt_branches"],
        "primary_quiet": (
            before["head"] == after["head"] and not delta
            and before["diff_stat_sha256"] == after["diff_stat_sha256"]
            and before.get("tracked_status_sha256")
            == after.get("tracked_status_sha256")),
    }


def _worktree_root_state(repo_root: Path) -> dict:
    from daedalus.kairos.worktree import GitWorktreeManager

    root = GitWorktreeManager(str(repo_root)).worktree_root
    try:
        entries = sorted(p.name for p in root.iterdir())
    except OSError:
        entries = []
    return {"path": str(root), "entries": entries}


# --------------------------------------------------------------------------- #
# the worktree-local policy stamp                                              #
# --------------------------------------------------------------------------- #
class _WorktreeConfigStamp:
    """Temporarily rewrite ``test_command`` in the WORKTREE's project config.

    Restores the original BYTES (not a re-serialised equivalent) and verifies
    the restoration by sha256. If the restore cannot be verified the runner
    raises, which fails the attempt loudly -- a silently unrestored config would
    ride into ``_capture_patch`` and contaminate the candidate patch with the
    harness's own edit.
    """

    def __init__(self, worktree: Path, test_command: str | None,
                 test_timeout_s: int | None = None) -> None:
        self.path = Path(worktree) / REPO_CONFIG_REL
        self.test_command = test_command
        self.test_timeout_s = test_timeout_s
        self.record: dict = {"applied": False, "path": str(self.path)}
        self._original: bytes | None = None

    def __enter__(self) -> "_WorktreeConfigStamp":
        if self.test_command is None:
            self.record["detail"] = "no override requested; the worktree's own config was used"
            return self
        if not self.path.exists():
            self.record["detail"] = f"no {REPO_CONFIG_REL} in the worktree; nothing stamped"
            return self
        self._original = self.path.read_bytes()
        doc = json.loads(self._original.decode("utf-8"))
        self.record["original_test_command"] = doc.get("test_command")
        self.record["original_sha256"] = hashlib.sha256(self._original).hexdigest()
        doc["test_command"] = self.test_command
        if self.test_timeout_s is not None:
            doc["test_timeout_s"] = int(self.test_timeout_s)
        doc["_comment_harness_override"] = (
            "TEMPORARY, written by tools/bootstrap_receipt.py into this WORKTREE "
            "copy only and reverted before the patch is captured. Never committed.")
        self.path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        self.record.update({"applied": True, "test_command": self.test_command,
                            "test_timeout_s": self.test_timeout_s})
        return self

    def __exit__(self, *exc: Any) -> bool:
        if self._original is None:
            return False
        self.path.write_bytes(self._original)
        now = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.record["restored_sha256"] = now
        self.record["restored"] = (now == self.record.get("original_sha256"))
        if not self.record["restored"]:
            raise RuntimeError(
                "the worktree project config could not be restored to its "
                "original bytes; refusing to let the harness's own edit reach "
                "the candidate patch")
        return False


def stamped_offload_runner(*, live: bool, paths: list[str] | None,
                           local_only: bool, test_command: str | None,
                           test_timeout_s: int | None,
                           stamp_sink: dict,
                           project: str | None = None) -> Any:
    """``offload_runner`` plus the worktree-local config stamp.

    Pinned to ``ctx.worktree`` exactly like ``attempt.offload_runner`` -- the
    runner is never handed the primary checkout's path.
    """
    def _runner(ctx: Any) -> Any:
        from daedalus.config import resolve_project
        from daedalus.offload import offload

        kwargs: dict[str, Any] = {"live": bool(live)}
        if paths:
            kwargs["paths"] = list(paths)
        if project:
            kwargs["project"] = project
        if local_only:
            kwargs["availability"] = {"claude_cli": False, "ollama": True,
                                      "deepseek": False, "codex_cli": False}
        stamp = _WorktreeConfigStamp(
            ctx.worktree, test_command, test_timeout_s)
        try:
            with stamp:
                pdata = resolve_project(str(ctx.worktree), project)
                stamp.record["project"] = project
                stamp.record["effective_test_command"] = (
                    (pdata or {}).get("test_command"))
                stamp.record["effective_test_cwd"] = (
                    (pdata or {}).get("test_cwd"))
                stamp.record["effective_test_timeout_s"] = (
                    (pdata or {}).get("test_timeout_s"))
                result = offload(
                    ctx.task.instruction, str(ctx.worktree), **kwargs)
                checks = ((result.get("verify") or {}).get("checks") or [])
                tests_check = next(
                    (c for c in checks if c.get("name") == "tests"), None)
                if tests_check is not None:
                    available = dict(tests_check)
                    stamp.record["verify_binding"] = {
                        "command": stamp.record["effective_test_command"],
                        "cwd": stamp.record["effective_test_cwd"],
                        "timeout_s": available.get("timeout_s"),
                        "status": available.get("status"),
                        # VerifyResult exposes the bounded detail, not the raw
                        # child output. Bind what exists and say what does not.
                        "available_check_sha256": _sha(json.dumps(
                            available, sort_keys=True, separators=(",", ":"),
                            default=str)),
                        "output_sha256": None,
                        "raw_output_digest_available": False,
                    }
                else:
                    stamp.record["verify_binding"] = None
                return result
        finally:
            # This must run AFTER __exit__, otherwise the receipt misses the
            # byte-exact restoration verdict it claims to record.
            stamp_sink.update(stamp.record)
    return _runner


def _execution_binding(result: Any, stamp: dict) -> dict:
    """Commands and digests that make this receipt replayable/auditable."""
    gate = result.gates.summary() if result.gates is not None else None
    return {
        "verify": stamp.get("verify_binding"),
        # GateResult is the authoritative source: it carries the argv that
        # ACTUALLY ran, the full-output digest and effective containment.
        "gate": gate,
    }


# --------------------------------------------------------------------------- #
# one attempt                                                                  #
# --------------------------------------------------------------------------- #
def run_single(*, repo_root: Path, task_id: str, instruction: str,
               paths: list[str] | None,
               gate_paths: tuple[str, ...], base_revision: str | None,
               live: bool, local_only: bool, test_command: str | None,
               test_timeout_s: int | None, artifact_dir: Path | None,
               ledger_path: Path, project: str | None = None,
               gate_command: tuple[str, ...] | None = None,
               keep_worktree: bool = False,
               leased: bool = False) -> dict:
    from daedalus.spine.attempt import (TaskAttempt, TaskSpec, command_gate,
                                        run_attempt)
    from daedalus.spine.bootstrap import gate_discrimination
    from daedalus.spine.ledger import SpineLedger

    target = Path(repo_root).resolve()
    ledger_path = Path(ledger_path).resolve()
    started = time.monotonic()
    before = primary_fingerprint(target)
    stamp: dict = {}

    # The declared write paths ARE the attempt's scope: since 68b8d856 an
    # undeclared scope refuses the attempt (empty is not "declare nothing"),
    # so a caller that wants a candidate must say where it may land.
    task = TaskSpec(task_id=task_id, instruction=instruction,
                    base_revision=base_revision, gate_paths=tuple(gate_paths),
                    target_paths=tuple(paths or ()))
    runner = stamped_offload_runner(
        live=live, paths=paths, local_only=local_only,
        test_command=test_command, test_timeout_s=test_timeout_s,
        stamp_sink=stamp, project=project)

    ledger = SpineLedger(ledger_path)
    try:
        attempt_kwargs: dict[str, Any] = {
            "runner": runner,
            "repo_root": str(target),
            # NOT handed to the attempt. `TaskAttempt._persist` now refuses any
            # caller-chosen path inside the attempt's own checkout (the
            # primary-tree fence, and rightly: candidate bytes landing in the
            # tree under improvement is how a later `git add -A` commits them).
            # This tool's contract is the OPPOSITE and deliberate: for an
            # external target the whole receipt bundle -- receipt, ledger,
            # artifact -- lives under the target, self-contained. Both stand:
            # the attempt deposits nothing, and the TOOL writes the patch bytes
            # below, beside the receipt it already writes there unfenced.
            "artifact_dir": None,
            "keep_worktree": keep_worktree,
            "ledger": ledger,
        }
        if gate_command is not None:
            attempt_kwargs["gate"] = command_gate(gate_command)
        if leased:
            # THE CALLER ACQUIRES; the attempt only consumes (the scheduler
            # rule, applied to the attempt door). The attempt object exists
            # first because its branch IS the effect key the issuer's
            # intent-ledger contract is run over, and the lease legitimately
            # precedes the intent that run() records. A deny is fail-closed:
            # no worktree, no runner, exit through the normal report path
            # with the issuer's own reasons.
            from daedalus.kernel.offload_lease import (
                WaveLeaseDenied, acquire_attempt_lease)

            attempt = TaskAttempt(task, **attempt_kwargs)
            head = base_revision or subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(target), check=True,
                capture_output=True, text=True).stdout.strip()
            lease = acquire_attempt_lease(
                target,
                source_revision=str(head),
                mission_id=f"bootstrap-{task_id}",
                attempt_id=attempt.branch,
                effect_key=attempt.branch,
                writable_paths=tuple(paths or ()),
                # The NAMED mechanism (containment.attempt requires one; the
                # issuer still DERIVES the verdict itself and trusts nothing
                # here): TaskAttempt runs candidate code only inside a
                # GitWorktreeManager worktree outside the checkout.
                contained=True,
                containment_evidence=(
                    "TaskAttempt isolated worktree via GitWorktreeManager; "
                    "candidate code never sees the primary checkout"),
            )
            if isinstance(lease, WaveLeaseDenied):
                res = None
                lease_denied = tuple(lease.reasons)
            else:
                attempt._attempt_lease = lease
                res = attempt.run()
                lease_denied = ()
            if res is None:
                return {
                    "schema": "bootstrap-receipt-lease-denied/1",
                    "task_id": task_id,
                    "leased": True,
                    "lease_denied": list(lease_denied),
                    "attempt": {"state": "lease_refused",
                                "error": "; ".join(lease_denied)},
                    "storage": {"receipt": False},
                }
        else:
            res = run_attempt(task, **attempt_kwargs)
    finally:
        ledger.close()

    after = primary_fingerprint(target)
    built_on = res.base_revision
    at_base = gate_discrimination(target, head=built_on) if built_on else None
    at_live = gate_discrimination(target, head=after["head"])

    diff_text = None
    changed = tuple(res.artifact.changed_paths) if res.artifact else ()
    if res.artifact is not None and not res.artifact.is_empty:
        diff_text = res.artifact.diff

    # The tool's own deposit (see the attempt_kwargs comment above): patch
    # bytes land beside the receipt, written by the same hand that writes the
    # receipt. A failure to deposit is reported, never fatal -- the patch text
    # itself is already embedded in the receipt under "patch".
    artifact_path: str | None = None
    artifact_note: str | None = None
    if artifact_dir and res.artifact is not None and not res.artifact.is_empty:
        try:
            dep = Path(artifact_dir) / f"{res.artifact.diff_sha256}.patch"
            dep.parent.mkdir(parents=True, exist_ok=True)
            dep.write_bytes(res.artifact.diff_bytes)
            artifact_path = str(dep)
        except OSError as e:
            artifact_note = f"artifact could not be deposited: {e}"
    leak = _leak_check(before, after, changed)
    gate_kind = "custom-command" if gate_command is not None else "pytest"
    gate_scope = (
        "custom-command"
        if gate_command is not None
        else ("whole-suite" if not gate_paths else "scoped")
    )

    return {
        "harness": "tools/bootstrap_receipt.py",
        "code_root": str(CODE_ROOT),
        "target_repo": str(target),
        "project": project,
        "pid": os.getpid(),
        "task_id": task_id,
        "instruction": instruction,
        "declared_paths": list(paths or []),
        "gate_paths": list(gate_paths),
        "gate_kind": gate_kind,
        "gate_scope": gate_scope,
        "live": bool(live),
        "local_only": bool(local_only),
        "worktree_config_stamp": stamp,
        "execution_binding": _execution_binding(res, stamp),
        "duration_s": round(time.monotonic() - started, 3),
        "attempt": res.to_dict(),
        "gate_output_tail": (res.gates.output[-4000:] if res.gates else None),
        "patch": diff_text,
        "primary_before": before,
        "primary_after": after,
        "primary_unchanged": leak["primary_quiet"],
        "primary_leak": leak,
        "worktree_root_after": _worktree_root_state(target),
        "storage": {
            "ledger_path": str(ledger_path),
            "artifact_dir": str(artifact_dir) if artifact_dir else None,
            "artifact_path": artifact_path,
            "artifact_note": artifact_note,
            "receipt_path": None,
        },
        "promotion": {
            "at_base_revision": {"head": built_on,
                                 **(at_base.to_dict() if at_base else {})},
            "at_live_head": {"head": after["head"], **at_live.to_dict()},
            # The product asks about the LIVE head (shadow_run reads
            # picker._head_sha), so that is the authoritative answer here.
            "promotion_allowed": bool(at_live.proven),
        },
    }


# --------------------------------------------------------------------------- #
# N at once                                                                    #
# --------------------------------------------------------------------------- #
def run_concurrent(n: int, argv_tail: Sequence[str], out_dir: Path,
                   repo_root: Path) -> dict:
    """Launch N INDEPENDENT PROCESSES of this same script in ``--single`` mode.

    Processes, not threads, because the accident being reproduced was a process
    fan-out: ten spawned interpreters each running their own attempt against one
    shared ``.git``. Threads would share a GIL and a git lock and would not test
    the thing that broke.

    Every child gets the SAME ``--task-id``, deliberately. ``TaskSpec.digest``
    is then identical across all N, so the only thing keeping their branches,
    worktrees and ledger effect keys apart is the uuid nonce
    ``TaskAttempt.__init__`` adds for exactly this case. Different task ids
    would make the isolation look fine without testing it.
    """
    target = Path(repo_root).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    before = primary_fingerprint(target)
    procs = []
    started = time.monotonic()
    for i in range(n):
        out = out_dir / f"concurrent-{i}.json"
        cmd = [sys.executable, str(Path(__file__).resolve()), "--single",
               "--out", str(out), *argv_tail]
        log = open(out_dir / f"concurrent-{i}.log", "wb")
        procs.append((i, out, log,
                      subprocess.Popen(cmd, cwd=str(CODE_ROOT), stdout=log,
                                       stderr=subprocess.STDOUT)))
    codes = []
    for i, out, log, p in procs:
        codes.append({"index": i, "returncode": p.wait(), "out": str(out)})
        log.close()
    after = primary_fingerprint(target)

    receipts = []
    for row in codes:
        try:
            receipts.append(json.loads(Path(row["out"]).read_text(encoding="utf-8")))
        except Exception as e:                      # noqa: BLE001
            receipts.append({"error": f"{type(e).__name__}: {e}", "index": row["index"]})

    def _field(name: str) -> list:
        return [(r.get("attempt") or {}).get(name) for r in receipts]

    branches = [b for b in _field("branch") if b]
    worktrees = [w for w in _field("worktree_path") if w]
    intents = [i for i in _field("intent_id") if i is not None]
    return {
        "harness": "tools/bootstrap_receipt.py --concurrent",
        "code_root": str(CODE_ROOT),
        "target_repo": str(target),
        "n": n,
        "duration_s": round(time.monotonic() - started, 3),
        "returncodes": codes,
        "states": _field("state"),
        "intent_ids": intents,
        "branches_distinct": len(set(branches)) == len(branches) == n,
        "worktrees_distinct": len(set(worktrees)) == len(worktrees) == n,
        "intent_ids_distinct": len(set(intents)) == len(intents) == n,
        "all_worktrees_removed": all(_field("worktree_removed")) and len(receipts) == n,
        "cleanup_errors": [c for c in _field("cleanup_error") if c],
        "reap_errors": [c for c in _field("reap_error") if c],
        "promotion_allowed_any": any(
            (r.get("promotion") or {}).get("promotion_allowed") for r in receipts),
        "primary_before": before,
        "primary_after": after,
        "primary_leak": _leak_check(before, after, sorted({
            p for r in receipts
            for p in ((r.get("attempt") or {}).get("artifact") or {}).get("changed_paths", [])})),
        "worktree_root_after": _worktree_root_state(target),
        "receipts": receipts,
    }


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _argv_json(value: str) -> tuple[str, ...]:
    """Argparse converter for an explicit argv JSON array.

    No shell splitting is performed. If the operator intentionally wants a
    shell, the shell executable and every flag must be present in the array.
    """
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"gate command must be JSON argv: {exc.msg}") from exc
    if (not isinstance(parsed, list) or not parsed
            or any(not isinstance(arg, str) or not arg for arg in parsed)):
        raise argparse.ArgumentTypeError(
            "gate command must be a non-empty JSON array of non-empty strings")
    return tuple(parsed)


def _target_path(repo_root: Path, raw: str | None,
                 default_rel: Path) -> Path:
    value = Path(raw) if raw else default_rel
    return value.resolve() if value.is_absolute() else (repo_root / value).resolve()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tools/bootstrap_receipt.py",
        description="Drive ONE bootstrap attempt to the gate and write a receipt. "
                    "Promotes nothing; there is no flag that promotes.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--single", action="store_true", help="one attempt")
    mode.add_argument("--concurrent", type=int, metavar="N",
                      help="N independent processes, same task id, for contention")
    p.add_argument("--repo-root", default=str(CODE_ROOT),
                   help="TARGET git checkout. Worktree, fingerprints, gate "
                        "discrimination and default runtime storage all bind "
                        "to this repo (default: the Daedalus code checkout).")
    p.add_argument("--project", default=None,
                   help="optional projects/<name>.json profile passed to offload")
    p.add_argument("--task-id", default="bootstrap-receipt")
    p.add_argument("--instruction", required=True)
    p.add_argument("--paths", nargs="*", default=None,
                   help="paths hint handed to offload (routing + context)")
    p.add_argument("--gate-paths", nargs="*", default=(),
                   help="pytest targets for the SPINE gate. Empty = whole suite, "
                        "which is what the live picker's candidates carry.")
    p.add_argument("--base-revision", default=None,
                   help="build the candidate on this revision instead of HEAD. "
                        "Use it to match a discrimination receipt in a repo "
                        "whose HEAD moves under you.")
    p.add_argument("--live", action="store_true")
    p.add_argument("--leased", action="store_true",
                   help="acquire a python.attempt Effect Lease for this "
                        "attempt (the caller acquires, the attempt consumes); "
                        "an issuer deny refuses the run fail-closed")
    p.add_argument("--local-only", action="store_true")
    p.add_argument("--worktree-test-command", default=None,
                   help="TEMPORARY override of test_command in the WORKTREE's "
                        "config only. Recorded in the receipt. A run that uses "
                        "one is not a run of the committed configuration.")
    p.add_argument("--worktree-test-timeout-s", type=int, default=None)
    p.add_argument(
        "--gate-command", "--gate-argv-json", dest="gate_command",
        type=_argv_json, default=None, metavar="JSON_ARGV",
        help="replace the default pytest spine gate with an explicit JSON argv "
             "array, e.g. '[\"npm.cmd\",\"--prefix\",\"design/visual-lab\","
             "\"run\",\"build\"]'. The harness never shell-splits this value.")
    p.add_argument(
        "--artifact-dir", default=None,
        help=f"patch directory; relative paths resolve under TARGET (default: "
             f"{DEFAULT_ARTIFACT_REL.as_posix()})")
    p.add_argument(
        "--ledger-path", default=None,
        help=f"spine ledger; relative paths resolve under TARGET (default: "
             f"{DEFAULT_LEDGER_REL.as_posix()})")
    p.add_argument("--keep-worktree", action="store_true")
    p.add_argument(
        "--out", default=None,
        help=f"receipt path; relative paths resolve under TARGET (default: "
             f"{(DEFAULT_RUN_REL / '<task-id>.json').as_posix()})")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.bootstrap_receipt",
        REGISTRY_BY_ID["tools.bootstrap_receipt"].effects,
        (process_guard_boundary_decision(),),
    )
    target = Path(args.repo_root).resolve()
    artifact_dir = _target_path(
        target, args.artifact_dir, DEFAULT_ARTIFACT_REL)
    ledger_path = _target_path(
        target, args.ledger_path, DEFAULT_LEDGER_REL)

    if args.concurrent:
        tail = [
            "--repo-root", str(target),
            "--instruction", args.instruction,
            "--task-id", args.task_id,
            "--artifact-dir", str(artifact_dir),
            "--ledger-path", str(ledger_path),
        ]
        if args.project:
            tail += ["--project", args.project]
        if args.paths:
            tail += ["--paths", *args.paths]
        if args.gate_paths:
            tail += ["--gate-paths", *args.gate_paths]
        if args.base_revision:
            tail += ["--base-revision", args.base_revision]
        if args.live:
            tail.append("--live")
        if args.local_only:
            tail.append("--local-only")
        if args.worktree_test_command:
            tail += ["--worktree-test-command", args.worktree_test_command]
        if args.worktree_test_timeout_s:
            tail += ["--worktree-test-timeout-s", str(args.worktree_test_timeout_s)]
        if args.gate_command:
            tail += ["--gate-command", json.dumps(list(args.gate_command))]
        out = _target_path(
            target, args.out, DEFAULT_RUN_REL / "contention.json")
        report = run_concurrent(args.concurrent, tail, out.parent, target)
        report["project"] = args.project
        report["storage"] = {
            "ledger_path": str(ledger_path),
            "artifact_dir": str(artifact_dir),
            "receipt_path": str(out),
            "defaults_relative_to_target": {
                "ledger": args.ledger_path is None,
                "artifact": args.artifact_dir is None,
                "receipt": args.out is None,
            },
        }
    else:
        report = run_single(
            repo_root=target,
            task_id=args.task_id, instruction=args.instruction,
            paths=args.paths, gate_paths=tuple(args.gate_paths),
            base_revision=args.base_revision, live=args.live,
            local_only=args.local_only,
            test_command=args.worktree_test_command,
            test_timeout_s=args.worktree_test_timeout_s,
            artifact_dir=artifact_dir, ledger_path=ledger_path,
            project=args.project, gate_command=args.gate_command,
            leased=args.leased)
        out = _target_path(
            target, args.out, DEFAULT_RUN_REL / f"{args.task_id}.json")
        report["storage"]["receipt_path"] = str(out)
        report["storage"]["defaults_relative_to_target"] = {
            "ledger": args.ledger_path is None,
            "artifact": args.artifact_dir is None,
            "receipt": args.out is None,
        }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if args.concurrent:
        print(f"n={report['n']} states={report['states']}")
        print(f"branches_distinct={report['branches_distinct']} "
              f"worktrees_distinct={report['worktrees_distinct']} "
              f"intent_ids_distinct={report['intent_ids_distinct']}")
        print(f"all_worktrees_removed={report['all_worktrees_removed']} "
              f"cleanup_errors={report['cleanup_errors']}")
        print(f"no_candidate_path_leaked="
              f"{report['primary_leak']['no_candidate_path_reached_the_primary_checkout']} "
              f"head_unchanged={report['primary_leak']['head_unchanged']} "
              f"promotion_allowed_any={report['promotion_allowed_any']}")
        print(f"worktree_root_after={report['worktree_root_after']['entries']}")
    elif report.get("schema") == "bootstrap-receipt-lease-denied/1":
        print("state              : lease_refused (no worktree, no runner)")
        for reason in report.get("lease_denied", ()):
            print(f"  deny             : {reason}")
    else:
        a = report["attempt"]
        print(f"state              : {a['state']}")
        print(f"base_revision      : {a['base_revision']}")
        print(f"artifact           : "
              f"{(a['artifact'] or {}).get('byte_length')} bytes  "
              f"{(a['artifact'] or {}).get('changed_paths')}")
        print(f"gate               : {a['gates']}")
        print(f"worktree_removed   : {a['worktree_removed']}  "
              f"cleanup_error={a['cleanup_error']}")
        print(f"primary quiet      : {report['primary_leak']['primary_quiet']}  "
              f"(delta appeared={report['primary_leak']['appeared']})")
        print(f"candidate leaked   : "
              f"{report['primary_leak']['candidate_paths_leaked']}  "
              f"clean={report['primary_leak']['no_candidate_path_reached_the_primary_checkout']}")
        print(f"promotion_allowed  : {report['promotion']['promotion_allowed']}")
        print(f"  at base revision : "
              f"{report['promotion']['at_base_revision'].get('proven')} -- "
              f"{report['promotion']['at_base_revision'].get('reason')}")
        print(f"  at live head     : "
              f"{report['promotion']['at_live_head'].get('proven')} -- "
              f"{report['promotion']['at_live_head'].get('reason')}")
    print(f"receipt: {out}")

    if args.concurrent:
        return EXIT_OK
    return EXIT_OK if report["attempt"]["state"] == "clean" else EXIT_NO_CANDIDATE


# THE GUARD. Without this, a spawn-based ProcessPoolExecutor anywhere in the
# import graph re-imports this module in every worker and re-runs the whole
# bootstrap once per core. That is not a hypothetical -- see the module
# docstring for the ten-attempt incident this line exists to prevent.
if __name__ == "__main__":
    raise SystemExit(main())
