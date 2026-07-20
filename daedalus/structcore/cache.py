"""Persistent per-file analysis cache (sqlite).

The index cache in ``index.py`` is in-memory, so it dies with the process: every
server restart re-pays the full scan. Real usage is re-scanning a repo that
barely changed, so memoizing the per-file pass on disk is a bigger UX win than
raw parallelism -- an unchanged repo re-indexes with zero parsing.

INVALIDATION: the key is a hash of the file's CONTENT (plus its path, language
and ``ANALYSIS_VERSION``) -- deliberately NOT size+mtime. We read every file's
bytes anyway, so hashing is nearly free, and unlike mtime it cannot go stale:
touch-without-edit is a hit, edit-preserving-mtime is a miss. A stale cache
silently reporting wrong code health would be worse than a slow scan, so the key
is chosen so staleness is not representable.

Failure policy: this is an optimization, never a correctness dependency. Any
sqlite problem degrades to "no cache" and the build proceeds normally.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import zlib
from functools import lru_cache
from pathlib import Path

from .parse import CodeUnit
from .perfile import ANALYSIS_VERSION, FileAnalysis

_SCHEMA = 1


def cache_root() -> Path:
    """Base directory for on-disk caches. ``DAEDALUS_CACHE_DIR`` overrides it
    (tests point this at a temp dir so they never touch the real cache)."""
    env = os.environ.get("DAEDALUS_CACHE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "daedalus" / "structcore"
    return Path.home() / ".cache" / "daedalus" / "structcore"


def enabled() -> bool:
    return os.environ.get("DAEDALUS_NO_CACHE", "").strip() not in ("1", "true", "TRUE")


@lru_cache(maxsize=1)
def _parser_version() -> str:
    """Digest of the extractor's own source, folded into every key.

    ``ANALYSIS_VERSION`` is hand-maintained, so it only invalidates the cache if
    someone remembers to bump it. Changing how a unit is NAMED without bumping
    produces the worst available outcome: ``slice`` re-parses off disk and sees
    the new names while the index is served from cache with the old ones, so the
    resolver silently matches nothing and slices quietly degrade -- a silent
    failure introduced BY a fix. Hashing parse.py makes that unrepresentable.
    Unreadable source degrades to the manual constant alone (never break the
    build for an optimization).
    """
    try:
        return hashlib.sha256(Path(__file__).with_name("parse.py").read_bytes()).hexdigest()
    except Exception:
        return ""


def file_key(rel: str, spec_name: str, text: str) -> str:
    """Content-addressed key. ``rel`` is included because analysis embeds the
    module path (CodeUnit.module), so the same bytes at two paths are two
    different results."""
    h = hashlib.sha256()
    h.update(ANALYSIS_VERSION.encode())
    h.update(b"\0")
    h.update(_parser_version().encode())
    h.update(b"\0")
    h.update(rel.encode("utf-8", "replace"))
    h.update(b"\0")
    h.update(spec_name.encode())
    h.update(b"\0")
    h.update(text.encode("utf-8", "replace"))
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# (de)serialization -- JSON, not pickle: the cache file is on disk and pickle   #
# would make a tampered cache an arbitrary-code-execution vector.              #
# --------------------------------------------------------------------------- #
def _encode(a: FileAnalysis) -> bytes:
    doc = {
        "rel": a.rel, "lang": a.lang, "n_chars": a.n_chars, "loc": a.loc,
        "metrics": a.metrics,
        "units": [[u.language, u.module, u.name, u.line, u.end_line, u.loc, u.source]
                  for u in a.units],
        "runs": a.runs,
        "py_imports": a.py_imports,
        "raw_imports": a.raw_imports,
    }
    return zlib.compress(json.dumps(doc, separators=(",", ":")).encode("utf-8"), 1)


def _decode(blob: bytes) -> FileAnalysis:
    doc = json.loads(zlib.decompress(blob).decode("utf-8"))
    return FileAnalysis(
        rel=doc["rel"], lang=doc["lang"], n_chars=doc["n_chars"], loc=doc["loc"],
        metrics=doc["metrics"],
        units=[CodeUnit(*u) for u in doc["units"]],
        runs=doc["runs"],
        # JSON gives lists where extraction gave tuples; every consumer just
        # iterates/unpacks, so this is shape-compatible.
        py_imports=[tuple(r) for r in doc["py_imports"]],
        raw_imports=[tuple(r) for r in doc["raw_imports"]],
    )


_MAX_CACHE_FILES = 20


def _evict_old_caches(d: Path, keep_besides: Path) -> None:
    """Keep only the most recently used cache DBs.

    Each DB is named by a hash of the repo root, so a root that disappears
    leaves an orphan nothing will ever reopen -- and the test suite indexes
    throwaway temp repos, which would otherwise drop a new orphan in the user's
    profile on every run. The root is unrecoverable from the hash, so bound the
    directory by recency instead.
    """
    try:
        dbs = [p for p in d.glob("idx-*.sqlite") if p != keep_besides]
        if len(dbs) < _MAX_CACHE_FILES:
            return
        dbs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in dbs[_MAX_CACHE_FILES - 1:]:
            p.unlink(missing_ok=True)
    except Exception:
        pass


class FileCache:
    """Per-repo sqlite store of ``FileAnalysis`` rows, keyed by content.

    Parent-process only. Workers never touch sqlite -- they return plain data
    and the parent commits it in one transaction, which keeps the concurrency
    story trivial (no cross-process DB locking).
    """

    def __init__(self, root):
        self.conn: sqlite3.Connection | None = None
        if not enabled():
            return
        try:
            d = cache_root()
            d.mkdir(parents=True, exist_ok=True)
            tag = hashlib.sha1(str(root).encode("utf-8", "replace")).hexdigest()[:16]
            db = d / f"idx-{tag}.sqlite"
            _evict_old_caches(d, keep_besides=db)
            self.conn = sqlite3.connect(str(db))
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS files ("
                " key TEXT PRIMARY KEY, schema INTEGER, payload BLOB)")
            self.conn.execute("DELETE FROM files WHERE schema IS NOT ?", (_SCHEMA,))
            self.conn.commit()
        except Exception:
            self.conn = None  # optimization only -- never break the build

    def get_many(self, keys: list[str]) -> dict[str, FileAnalysis]:
        if self.conn is None or not keys:
            return {}
        out: dict[str, FileAnalysis] = {}
        try:
            # Chunked to stay under SQLITE_MAX_VARIABLE_NUMBER on big repos.
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                q = "SELECT key, payload FROM files WHERE key IN (%s)" % (
                    ",".join("?" * len(part)))
                for k, blob in self.conn.execute(q, part):
                    try:
                        out[k] = _decode(blob)
                    except Exception:
                        pass  # corrupt row -> treat as a miss, recompute
        except Exception:
            return out
        return out

    def put_many(self, items: list[tuple[str, FileAnalysis]]) -> None:
        if self.conn is None or not items:
            return
        try:
            self.conn.executemany(
                "INSERT OR REPLACE INTO files (key, schema, payload) VALUES (?,?,?)",
                [(k, _SCHEMA, _encode(a)) for k, a in items])
            self.conn.commit()
        except Exception:
            pass

    def prune(self, live_keys: set[str]) -> None:
        """Drop rows for content no longer present, so the DB tracks the repo's
        current state instead of growing without bound across edits."""
        if self.conn is None:
            return
        try:
            self.conn.execute("CREATE TEMP TABLE IF NOT EXISTS live (key TEXT PRIMARY KEY)")
            self.conn.execute("DELETE FROM live")
            self.conn.executemany("INSERT OR IGNORE INTO live VALUES (?)",
                                  [(k,) for k in live_keys])
            self.conn.execute("DELETE FROM files WHERE key NOT IN (SELECT key FROM live)")
            self.conn.commit()
        except Exception:
            pass

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
