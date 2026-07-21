"""churn.py — git change-frequency per file (the CodeScene health signal), plus
temporal-coupling (co-change) pairs for edges the static import graph can't see.

Rot concentrates where code is BOTH complex AND frequently changing; complexity
alone over-flags stable-but-gnarly code. ``git_churn`` returns per-file
add+delete line totals summed over history (optionally a recent window), which
``index.py`` multiplies into the complexity hotspot score.

Degrades cleanly and completely: not a git repo, git not on PATH, timeout, or
any parse hiccup -> ``{}``, and hotspots behave exactly as before (no churn
factor). Windows-safe: UTF-8 with ``errors='replace'`` and a hard timeout.

``co_change_pairs``/``temporal_misses`` (below) are a SEPARATE analysis over
the SAME log data, added alongside ``git_churn`` rather than folded into it --
``git_churn``'s return shape and degradation contract are relied on by
``index.py:511`` and must stay exactly as they are.
"""
from __future__ import annotations

import math
import re
import subprocess
from collections import defaultdict
from itertools import combinations
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


# --------------------------------------------------------------------------- #
# Temporal coupling: files that repeatedly change in the SAME commit          #
# --------------------------------------------------------------------------- #

# A commit touching more files than this is DROPPED ENTIRELY from co-change --
# not truncated, excluded -- because a mass reformat / vendor bump / squash
# merge produces C(n,2) pairs (a 200-file commit is ~19,900 pairs) that are
# pure noise, not coupling, and are expensive to even enumerate. 40 sits well
# above a normal focused commit (this repo's own history reliably stays in the
# single digits to low teens of files per commit) and well below a repo-wide
# sweep, so real multi-file features keep contributing while sweeps are
# excluded outright -- a truncated SAMPLE of a 200-file commit would still
# emit hundreds of meaningless pairs, which dropping the commit avoids.
COCHANGE_MAX_FILES_PER_COMMIT = 40


def co_change_pairs(
    repo_root, since: str | None = None, min_count: int = 2,
    max_files_per_commit: int = COCHANGE_MAX_FILES_PER_COMMIT, timeout: float = 30.0,
    rev: str | None = None,
) -> list[dict]:
    """Files that repeatedly change together -- a coupling signal the static
    import graph structurally cannot see (config<->consumer, schema<->
    migration, test<->impl: none of those necessarily `import` each other).

    Runs its OWN ``git log --numstat --format=%H`` (a separate invocation from
    ``git_churn``, which intentionally keeps its empty ``--format=`` -- see the
    module docstring). ``%H`` makes commits separable so co-occurrence can be
    computed per commit instead of over one undifferentiated numstat stream.
    Each commit's file set is capped at ``max_files_per_commit``; a commit over
    the cap is dropped entirely (see ``COCHANGE_MAX_FILES_PER_COMMIT``).

    Weighted by PMI (``ln(N * count_ab / (count_a * count_b))``) and lift
    (``exp(pmi)``), not raw co-occurrence count: two files that each change on
    nearly every commit (a changelog, a version stamp) co-occur constantly by
    sheer volume, not because they are coupled to EACH OTHER -- PMI discounts
    exactly that by normalizing against how often each file changes alone.
    ``min_count`` additionally floors out pairs seen fewer than N times, since
    a single co-occurrence is one data point, not a pattern.

    ``rev`` (default ``None`` -> full history, byte-identical to before the
    parameter existed) is passed to ``git log`` as a revision range. Its use
    case is the BACKTEST-CLEAN cut the eval's temporal-ceiling check needs:
    ``rev="<sha>^"`` counts only commits strictly before ``<sha>``, so a
    measurement about ``<sha>`` cannot be predicted by ``<sha>``'s own data.
    Caveat carried by git itself: ``<sha>^`` is the FIRST parent, so on a merge
    commit the merged-in side branch is excluded too (the ceiling check flags
    merge SHAs rather than pretending otherwise). An unresolvable ``rev`` makes
    git exit non-zero -> ``[]``, same degradation contract as everything else
    here -- callers who must distinguish "no coupling" from "no history" probe
    the rev themselves first.

    Returns ``[]`` on any git failure -- same degradation contract as
    ``git_churn``. Rows are ``{"a", "b", "count", "count_a", "count_b",
    "commits_considered", "pmi", "lift"}``, sorted by ``(-pmi, a, b)`` for
    determinism (``a < b`` lexically within each row).
    """
    root = Path(repo_root).resolve()
    cmd = ["git", "-C", str(root), "log", "--numstat", "--format=%H"]
    if since:
        cmd.append(f"--since={since}")
    if rev:
        cmd.append(rev)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return _pairs_from_log(proc.stdout, min_count, max_files_per_commit)


def _commits_from_log(text: str) -> list[set[str]]:
    """Regroup a ``--numstat --format=%H`` stream into one file-set per commit.

    A commit-hash line has zero tabs (1 field); a numstat line always has
    exactly two tabs (3 fields: added, deleted, path) -- the two never
    collide, so this needs no lookahead/blank-line bookkeeping."""
    commits: list[set[str]] = []
    current: set[str] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 1:
            current = set()
            commits.append(current)
            continue
        if len(parts) == 3 and current is not None:
            rel = _rename_target(parts[2]).replace("\\", "/")
            if rel:
                current.add(rel)
    return commits


def _pairs_from_log(text: str, min_count: int, cap: int) -> list[dict]:
    commits = [c for c in _commits_from_log(text) if 0 < len(c) <= cap]
    n = len(commits)
    if n == 0:
        return []

    file_count: dict[str, int] = defaultdict(int)
    pair_count: dict[tuple[str, str], int] = defaultdict(int)
    for files in commits:
        for f in files:
            file_count[f] += 1
        for a, b in combinations(sorted(files), 2):
            pair_count[(a, b)] += 1

    rows: list[dict] = []
    for (a, b), count_ab in pair_count.items():
        if count_ab < min_count:
            continue
        count_a, count_b = file_count[a], file_count[b]
        expected = (count_a * count_b) / n
        if expected <= 0:
            continue  # unreachable in practice (a,b both appeared >=1 time), kept as a guard
        lift = count_ab / expected
        pmi = math.log(lift) if lift > 0 else float("-inf")
        rows.append({
            "a": a, "b": b, "count": count_ab,
            "count_a": count_a, "count_b": count_b, "commits_considered": n,
            "pmi": pmi, "lift": lift,
        })
    rows.sort(key=lambda r: (-r["pmi"], r["a"], r["b"]))
    return rows


def temporal_misses(idx: dict, pairs: list[dict], min_pmi: float = 0.0) -> list[dict]:
    """Co-change pairs (from ``co_change_pairs``) with NO static import edge in
    either direction inside ``idx["import_edges"]`` -- real coupling the import
    graph cannot see, the actual payoff of this module.

    Reports each candidate on BOTH axes a temporal tier must be judged on, by
    design -- reporting only recall would read as an unqualified win and hide
    exactly the failure mode this function guards against:
      * ``recall_axis``: pmi/lift/count -- how confidently the two files move
        together (the case FOR treating this pair as an edge);
      * ``compression_cost_loc``: the combined loc of the pair -- what any
        slice that follows this edge would grow by (the case AGAINST; a
        temporal tier that adds recall by quietly bloating every slice is a
        regression, not a win).

    Pairs already linked by a static edge are excluded outright (the graph
    already has them; they are not a miss). ``idx`` is a plain index dict as
    returned by ``structcore.index.build_index`` -- NOT imported here, to
    avoid a churn<->index import cycle (index.py imports ``git_churn`` from
    this module already).
    """
    edges = idx.get("import_edges", {})
    modules = idx.get("modules", {})

    def _linked(a: str, b: str) -> bool:
        return b in edges.get(a, ()) or a in edges.get(b, ())

    out = []
    for row in pairs:
        a, b = row["a"], row["b"]
        if row["pmi"] < min_pmi or _linked(a, b):
            continue
        loc_a = modules.get(a, {}).get("loc", 0)
        loc_b = modules.get(b, {}).get("loc", 0)
        out.append({
            **row,
            "recall_axis": {"pmi": row["pmi"], "lift": row["lift"], "count": row["count"]},
            "compression_cost_loc": loc_a + loc_b,
        })
    out.sort(key=lambda r: (-r["pmi"], r["a"], r["b"]))
    return out
