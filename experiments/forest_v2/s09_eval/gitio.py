"""Read-only git plumbing for the s09 eval harness.

Only ever runs plumbing that reads: ``log``, ``rev-parse``, ``ls-tree``,
``cat-file --batch``.  No command in this module can mutate a repository.
Pure stdlib plus the ``git`` binary, which is the data source for the task
set -- the history IS the ground truth, so reading it is not optional.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

#: field separator inside one log record
_FS = "\x1f"
#: record separator between log records
_RS = "\x1e"

_READ_ONLY_VERBS = frozenset({"log", "rev-parse", "ls-tree", "cat-file"})


class GitError(RuntimeError):
    """A git plumbing call failed."""


def _run(repo: Path, args: Sequence[str]) -> bytes:
    if not args or args[0] not in _READ_ONLY_VERBS:
        raise GitError(f"refusing non-read-only git verb: {args[:1]}")
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
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
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input=("\n".join(wanted) + "\n").encode("ascii"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git cat-file --batch failed: {detail}")

    out: Dict[str, bytes] = {}
    buf = proc.stdout
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
