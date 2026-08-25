"""Git plumbing for the s09 eval harness: read-only on the source repository.

Every call that touches a repository the harness did not create goes through
:func:`_run`, which refuses any verb outside ``_READ_ONLY_VERBS`` (``log``,
``rev-list``, ``rev-parse``, ``ls-tree``, ``cat-file``). Pure stdlib plus the
``git`` binary, which is the data source for the task set -- the history IS
the ground truth, so reading it is not optional.

The docstring here used to say "no command in this module can mutate a
repository".  That was wrong in two directions and is corrected in place:

* it was enforced at four call sites and skipped at the fifth --
  :func:`read_blobs` shelled ``cat-file --batch`` directly, past the gate,
  because it needs stdin.  :func:`_run` now takes ``stdin`` and
  ``read_blobs`` goes through it like every other read.
* :func:`make_preimage_clone` *does* write, on purpose.  It writes only into
  a destination directory the caller supplies and which must not already
  exist, and never into the source repository.  It is the one exception, it
  is named, and it is deliberately not routed through the read-only gate.

The precise claim is therefore narrower: calls routed through ``_run`` are
transport-disabled, locally read-only Git plumbing. ``make_preimage_clone``
is an explicit writer outside that gate and outside that claim.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

#: field separator inside one log record
_FS = "\x1f"
#: record separator between log records
_RS = "\x1e"

_READ_ONLY_VERBS = frozenset(
    {"log", "rev-list", "rev-parse", "ls-tree", "cat-file"}
)
_SAFE_GIT_ENV = {
    "GIT_ALLOW_PROTOCOL": "",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PROTOCOL_FROM_USER": "0",
    "GIT_TERMINAL_PROMPT": "0",
}


class GitError(RuntimeError):
    """A git plumbing call failed."""


def _run(repo: Path, args: Sequence[str], stdin: bytes | None = None) -> bytes:
    """Run one read-only git plumbing command against ``repo``.

    The verb allowlist is the whole point: this is the single door every read
    in this package goes through, so "read-only on the source" is one
    checkable property instead of a promise repeated in five docstrings.
    ``stdin`` exists so ``cat-file --batch`` can be fed *through* the gate
    rather than around it. Every inherited ``GIT_*`` variable is removed and
    only explicit safety settings are added back. Promised objects may not be
    fetched lazily: unavailable local evidence is a failure rather than
    permission to contact a remote or rewrite objects.
    """
    if not args or args[0] not in _READ_ONLY_VERBS:
        raise GitError(f"refusing non-read-only git verb: {args[:1]}")
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }
    environment.update(
        {
            "GCM_INTERACTIVE": "Never",
            **_SAFE_GIT_ENV,
        }
    )
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        capture_output=True,
        check=False,
        env=environment,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args[:3])} failed: {detail}")
    return proc.stdout


def rev_parse(repo: Path, rev: str) -> str:
    """Resolve ``rev`` to a full commit sha."""
    return _run(repo, ["rev-parse", rev]).decode("utf-8", "replace").strip()


@dataclass(frozen=True)
class Commit:
    """One non-merge commit with the paths it actually touched."""

    sha: str
    parent: str
    committed_at: int
    subject: str
    body: str
    changed: Tuple[str, ...]

    @property
    def message(self) -> str:
        body = self.body.strip()
        return f"{self.subject}\n\n{body}".strip() if body else self.subject.strip()


def read_history(repo: Path, anchor: str, limit: int) -> List[Commit]:
    """Return up to ``limit`` non-merge commits reachable from ``anchor``.

    Newest first.  Commits without a parent (the root) are skipped: a
    retrieval case needs a pre-image tree to search.
    """
    fmt = f"--pretty=format:{_RS}%H{_FS}%P{_FS}%ct{_FS}%s{_FS}%b{_FS}"
    raw = _run(
        repo,
        ["log", "--no-merges", fmt, "--name-only", f"-n{int(limit)}", anchor],
    ).decode("utf-8", "replace")

    commits: List[Commit] = []
    for chunk in raw.split(_RS):
        if not chunk.strip():
            continue
        fields = chunk.split(_FS)
        if len(fields) < 5:
            continue
        sha, parents, ctime, subject, body = fields[:5]
        tail = fields[5] if len(fields) > 5 else ""
        parent_list = parents.split()
        if not parent_list:
            continue
        changed = tuple(line.strip() for line in tail.splitlines() if line.strip())
        commits.append(
            Commit(
                sha=sha.strip(),
                parent=parent_list[0],
                committed_at=int(ctime),
                subject=subject.strip(),
                body=body,
                changed=changed,
            )
        )
    return commits


def list_tree(repo: Path, rev: str) -> Dict[str, Tuple[str, int]]:
    """Map ``path -> (blob_sha, size)`` for every blob in ``rev``'s tree."""
    raw = _run(repo, ["ls-tree", "-r", "-l", "-z", rev]).decode("utf-8", "replace")
    out: Dict[str, Tuple[str, int]] = {}
    for entry in raw.split("\0"):
        if not entry.strip():
            continue
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) < 4 or parts[1] != "blob":
            continue
        blob, size_text = parts[2], parts[3]
        if size_text == "-":
            continue
        out[path] = (blob, int(size_text))
    return out


def read_blobs(repo: Path, shas: Iterable[str]) -> Dict[str, bytes]:
    """Fetch many blobs in one ``cat-file --batch`` process.

    Returns ``sha -> raw bytes``.  Unknown or non-blob objects are skipped
    rather than raising, so a partial tree cannot abort a whole run.
    """
    wanted = [s for s in dict.fromkeys(shas)]
    if not wanted:
        return {}
    buf = _run(
        repo,
        ["cat-file", "--batch"],
        stdin=("\n".join(wanted) + "\n").encode("ascii"),
    )

    out: Dict[str, bytes] = {}
    pos = 0
    end = len(buf)
    while pos < end:
        nl = buf.find(b"\n", pos)
        if nl < 0:
            break
        header = buf[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) < 3:
            # "<sha> missing" -- nothing follows it
            continue
        sha, kind, size_text = header[0], header[1], header[2]
        size = int(size_text)
        payload = buf[pos : pos + size]
        pos += size + 1  # trailing newline after the payload
        if kind == "blob":
            out[sha] = payload
    return out


def log_name_only(repo: Path, revision: str, limit: int) -> List[str]:
    """Paths touched by the last ``limit`` non-merge commits up to ``revision``.

    Exists so ``RecencyPrior`` stops shelling ``git log`` straight out of
    ``retrievers.py``.  That was the fifth call site the read-only gate never
    saw; routing it here means the allowlist covers every git call the
    package makes, and a test can prove it by watching this door.

    Returns paths in first-seen order, newest commit first.  Duplicates are
    preserved -- the caller decides what "recent" means.
    """
    raw = _run(
        repo,
        [
            "log", "--no-merges", "--pretty=format:", "--name-only",
            f"-n{int(limit)}", revision,
        ],
    ).decode("utf-8", "replace")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def read_rename_stats(repo: Path, anchor: str, limit: int) -> Dict[str, Tuple[int, int]]:
    """Map ``sha -> (rename_entries, diff_entries)`` for the same history.

    Exists so the cross-plane corpus can reject rename-dominated commits
    without shelling ``git`` around the read-only gate.  ``read_history``
    uses ``--name-only``, which prints a rename's destination and hides its
    source; that is fine for gold (the destination is absent from the parent
    tree and drops out) but it means a rename-heavy commit looks small.  The
    same commit under ``diff.renames=false`` reports both sides, and the
    sources ARE in the parent tree.  Reading the statuses here is what lets a
    rule see the difference instead of inheriting whichever git config the
    machine happened to have.
    """
    raw = _run(
        repo,
        [
            "log", "--no-merges", f"--pretty=format:{_RS}%H", "--name-status",
            f"-n{int(limit)}", anchor,
        ],
    ).decode("utf-8", "replace")

    out: Dict[str, Tuple[int, int]] = {}
    current = ""
    renames = 0
    total = 0
    for chunk in raw.split(_RS):
        if not chunk.strip():
            continue
        lines = chunk.splitlines()
        if not lines:
            continue
        current = lines[0].strip()
        renames = 0
        total = 0
        for line in lines[1:]:
            if not line.strip():
                continue
            status = line.split("\t")[0]
            total += 1
            if status.startswith("R"):
                renames += 1
        if current:
            out[current] = (renames, total)
    return out


def make_preimage_clone(source: Path, revision: str, dest: Path) -> Path:
    """Materialise a bare repository containing ONLY ``revision`` and its ancestors.

    This is the sandbox behind ``QueryView.revision``'s "read nothing after
    the case" rule.  A stated norm is not a boundary: a retriever handed the
    real repository can walk forward to the very commit whose diff is the
    answer key, and an executed probe scored MRR 1.000 doing exactly that,
    detected by nothing.  A retriever handed *this* repository cannot,
    because the future is not merely unreferenced -- it is absent from the
    object store.

    Built by pushing one commit into a fresh bare repo: ``git push`` computes
    the object closure of what it sends, so ancestors come along and
    descendants cannot.  ``dest`` must not exist; this function is the only
    writer in this module and it writes nowhere else.
    """
    if dest.exists():
        raise GitError(f"pre-image clone destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    init = subprocess.run(
        ["git", "init", "--quiet", "--bare", str(dest)],
        capture_output=True,
        check=False,
    )
    if init.returncode != 0:
        raise GitError(
            "git init --bare failed: " + init.stderr.decode("utf-8", "replace").strip()
        )
    push = subprocess.run(
        ["git", "-C", str(source), "push", "--quiet", str(dest),
         f"{revision}:refs/heads/preimage"],
        capture_output=True,
        check=False,
    )
    if push.returncode != 0:
        raise GitError(
            f"pushing pre-image {revision[:12]} failed: "
            + push.stderr.decode("utf-8", "replace").strip()
        )
    head = subprocess.run(
        ["git", "-C", str(dest), "symbolic-ref", "HEAD", "refs/heads/preimage"],
        capture_output=True,
        check=False,
    )
    if head.returncode != 0:
        raise GitError(
            "setting HEAD in the pre-image clone failed: "
            + head.stderr.decode("utf-8", "replace").strip()
        )
    return dest


def contains_commit(repo: Path, sha: str) -> bool:
    """True when ``sha`` is present in ``repo``'s object store at all.

    The assertion a pre-image clone has to survive: not "the future is
    unreachable from HEAD" but "the future is not here".
    """
    try:
        _run(repo, ["cat-file", "-e", f"{sha}^{{commit}}"])
    except GitError:
        return False
    return True
