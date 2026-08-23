"""Facts about the tree a session stands in. Everything here is derived from
git and two files (``.mcp.json``, the sweeps log); nothing is a clock, so the
rendered card is identical for an identical repository state (a cache-stable
prefix, see the package docstring)."""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ._common import HOOKS_DIR_REL, git

NL = chr(10)
SWEEPS_LOG_REL = ".claude/watchdog/docs/sweeps.log"
SOURCE_SCOPES = ("daedalus", "tools", "tests", "scripts")

#: Serena tools that mutate the project or Serena's memory store. A session
#: whose Serena is indexed on another tree must not call these — the edit would
#: land in that other tree (incident 2026-08-22, four edits into the archive).
SERENA_WRITE_TOOLS = frozenset(
    {
        "replace_symbol_body",
        "insert_after_symbol",
        "insert_before_symbol",
        "replace_content",
        "replace_in_files",
        "rename_symbol",
        "safe_delete_symbol",
        "write_memory",
        "edit_memory",
        "delete_memory",
        "rename_memory",
    }
)


def _norm(path: str | os.PathLike) -> str:
    text = str(Path(path).resolve())
    return text.lower() if os.name == "nt" else text


def serena_configured_root(root: Path) -> Path | None:
    """The ``--project`` Serena is started with in this tree's ``.mcp.json``,
    or None when there is no such configuration. This is the CONFIGURED root;
    the live server's identity is not observable from a hook."""
    try:
        data = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        args = data["mcpServers"]["serena"]["args"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(args, list):
        return None
    for i, item in enumerate(args):
        if item == "--project" and i + 1 < len(args) and isinstance(args[i + 1], str):
            return Path(args[i + 1])
        if isinstance(item, str) and item.startswith("--project="):
            return Path(item.split("=", 1)[1])
    return None


def serena_root_mismatch(root: Path) -> Path | None:
    """The configured Serena root when it is NOT this tree, else None."""
    configured = serena_configured_root(root)
    if configured is None:
        return None
    return configured if _norm(configured) != _norm(root) else None


@dataclass(frozen=True)
class TreeFacts:
    name: str
    branch: str
    head: str
    dirty_count: int
    dirty_dirs: tuple[str, ...]
    archived_tag: str
    serena_mismatch: str
    serena_configured: bool

    def tree_line(self) -> str:
        # ASCII only: this line lands in a cp1252 console (shift.py learned it first).
        bits = [f"TREE: {self.name} | {self.branch or 'detached'} @{self.head or '?'}"]
        if self.dirty_count:
            dirs = ", ".join(self.dirty_dirs) if self.dirty_dirs else "-"
            bits.append(f"dirty: {self.dirty_count} files ({dirs})")
        if self.serena_mismatch:
            bits.append(f"configured serena root: {self.serena_mismatch} != this tree -> Serena WRITE tools denied")
        elif self.serena_configured:
            bits.append("configured serena root: this tree")
        return " | ".join(bits)

    def archived_line(self) -> str:
        if not self.archived_tag:
            return ""
        return f"ARCHIVED TREE ({self.archived_tag}): history only; work belongs in the live tree"


def dirty_summary(root: Path) -> tuple[int, tuple[str, ...]]:
    # The hooks' own state directory is excluded by pathspec, so the count is
    # the same whether or not the tree ignores runs/hooks/.
    status = git(
        root, "status", "--porcelain", "--untracked-files=normal", "--",
        ".", f":(exclude){HOOKS_DIR_REL}", ":(exclude)runs/arch_memory.shown",
    )
    if not status:
        return 0, ()
    count = 0
    dirs: Counter[str] = Counter()
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if path.startswith(HOOKS_DIR_REL) or path == "runs/arch_memory.shown":
            continue  # the hooks' own state is never "dirty work"
        count += 1
        first = path.split("/", 1)[0]
        dirs[first] += 1
    top = tuple(name for name, _n in dirs.most_common(3))
    return count, top


def archived_tag(root: Path) -> str:
    """An ``archive/*`` tag on HEAD, or one matching the branch name (the
    archived checkpoint line carries later commits than its tag). Secondary
    signal: the user-level ``orient`` hook has the authoritative root list."""
    tags = git(root, "tag", "--points-at", "HEAD")
    for tag in tags.splitlines():
        if tag.startswith("archive/"):
            return tag
    branch = git(root, "branch", "--show-current")
    if branch and branch != "main":
        tail = branch.rsplit("/", 1)[-1]
        for tag in git(root, "tag", "--list", f"archive/*{tail}*").splitlines():
            if tag:
                return tag
    return ""


def tree_facts(root: Path) -> TreeFacts:
    count, dirs = dirty_summary(root)
    mismatch = serena_root_mismatch(root)
    return TreeFacts(
        name=root.name or str(root),
        branch=git(root, "branch", "--show-current"),
        head=git(root, "rev-parse", "--short=8", "HEAD"),
        dirty_count=count,
        dirty_dirs=dirs,
        archived_tag=archived_tag(root),
        serena_mismatch=str(mismatch) if mismatch else "",
        serena_configured=serena_configured_root(root) is not None,
    )


def last_sweep(root: Path) -> tuple[str, str]:
    """(HEAD the last mnemosyne sweep ran at, commits between it and HEAD as a
    string) — from ``.claude/watchdog/docs/sweeps.log``; ("", "") if none."""
    try:
        lines = (root / SWEEPS_LOG_REL).read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", ""
    for line in reversed(lines):
        for token in line.split():
            if token.startswith("HEAD="):
                sha = token[5:]
                behind = git(root, "rev-list", "--count", f"{sha}..HEAD") if sha else ""
                return sha, behind
    return "", ""


def source_fingerprint(root: Path) -> dict[str, str]:
    """A content-exact per-file fingerprint of the working tree's source
    changes against HEAD: one ``git diff HEAD`` over the source scopes, split
    per file, each file's hunk text hashed; plus the content hash of every
    untracked source file. Two git calls, no per-file calls. An edit that
    changes bytes changes the hash (Codex round 2 caught the earlier numstat
    version missing ``x=2 -> x=3``)."""
    fp: dict[str, str] = {}
    diff = git(root, "diff", "HEAD", "--no-color", "--no-ext-diff", "--", *SOURCE_SCOPES)
    current: str | None = None
    chunks: dict[str, list[str]] = {}
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            marker = line.find(" b/")  # "diff --git a/<path> b/<path>"
            current = line[marker + 3:] if marker >= 0 else line
            chunks[current] = []
        elif current is not None:
            chunks[current].append(line)
    for path, lines in chunks.items():
        fp[path] = hashlib.sha256(NL.join(lines).encode("utf-8", errors="replace")).hexdigest()[:16]
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "--", *SOURCE_SCOPES)
    for rel in untracked.splitlines():
        try:
            fp[rel] = "new:" + hashlib.sha256((root / rel).read_bytes()).hexdigest()[:16]
        except OSError:
            continue
    return fp


def fingerprint_diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths whose fingerprint differs between two snapshots."""
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))
