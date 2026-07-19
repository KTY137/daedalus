"""churn.py — git change-frequency per file (the CodeScene health signal).

Rot concentrates where code is BOTH complex AND frequently changing; complexity
alone over-flags stable-but-gnarly code. ``git_churn`` returns per-file
add+delete line totals summed over history (optionally a recent window), which
``index.py`` multiplies into the complexity hotspot score.

Degrades cleanly and completely: not a git repo, git not on PATH, timeout, or
any parse hiccup -> ``{}``, and hotspots behave exactly as before (no churn
factor). Windows-safe: UTF-8 with ``errors='replace'`` and a hard timeout.
"""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path


def git_churn(repo_root, since: str | None = None, timeout: float = 30.0) -> dict[str, int]:
    """Map ``{rel_posix_path: added+deleted lines over history}``.

    Runs ``git -C <root> log --numstat --format=`` (empty format => only the
    numstat body). ``since`` (e.g. '3 months ago', '2025-01-01') narrows to a
    recent window — recent churn is the sharper decay signal. Returns ``{}`` on
    any failure so the caller can treat churn as optional."""
    root = Path(repo_root).resolve()
    cmd = ["git", "-C", str(root), "log", "--numstat", "--format="]
    if since:
        cmd.append(f"--since={since}")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return {}  # git missing / not a repo / timeout -> no churn signal
    if proc.returncode != 0:
        return {}
    return _parse_numstat(proc.stdout)


def _parse_numstat(text: str) -> dict[str, int]:
    """Parse ``git log --numstat`` body: ``<added>\\t<deleted>\\t<path>`` lines.

    ``added``/``deleted`` are ``-`` for binary files (counted as 0). Rename lines
    (``old => new`` or ``dir/{old => new}/file``) are normalized to the NEW path
    so churn follows the file across renames."""
    churn: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_s, deleted_s, path = parts
        added = int(added_s) if added_s.isdigit() else 0
        deleted = int(deleted_s) if deleted_s.isdigit() else 0
        rel = _rename_target(path).replace("\\", "/")
        if rel:
            churn[rel] += added + deleted
    return dict(churn)


def _rename_target(path: str) -> str:
    """Resolve git's rename notation to the current (new) path.

    ``a/{old => new}/f.py`` -> ``a/new/f.py``;  ``old.py => new.py`` -> ``new.py``.
    """
    if "{" in path and "=>" in path:
        path = re.sub(r"\{([^}]*)\}", lambda m: m.group(1).split("=>")[-1].strip(), path)
        return re.sub(r"//+", "/", path).strip()
    if "=>" in path:
        return path.split("=>")[-1].strip()
    return path.strip()
