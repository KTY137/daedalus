"""kairos/archive.py -- what previous attempts learned, offered to the next one.

ATTRIBUTION
-----------
The sampling SHAPE in this module is adapted from OpenEvolve.

    upstream: https://github.com/codelion/openevolve
    commit:   411fb59c886c18704caaffb611e17cf9e7d824d2  (2026-07-18)
    license:  Apache-2.0  (see references/openevolve/LICENSE)
    taken:    the two-tier inspiration draw -- a few ELITE entries plus a few
              DIVERSE ones -- from ``database.py::_sample_inspirations``
              (upstream lines 1564-1640), and the 3-elite/2-diverse split from
              their ``config.py`` defaults ``num_top_programs=3`` /
              ``num_diverse_programs=2`` (upstream lines 268-269).

    changed:  substantially. This is a re-implementation against our own
              spine, not a port, and it deliberately does LESS:

      * NO MAP-Elites feature grid, NO islands, NO migration. ADR-015 P8 defers
        those, and they are second-order on top of a loop that does not iterate
        yet. Their `feature_dimensions` / `num_islands` / `migration_*`
        machinery is recorded in references/openevolve/PROVENANCE.md for when
        that changes; none of it is implemented here.
      * WE STORE A DIGEST, THEY STORE THE CODE. Upstream keeps full program
        source in the archive and pastes it into the next prompt. An archive
        that holds candidate source is an egress vector -- it is exactly how a
        secret that a candidate happened to write reaches a paid provider on
        some later iteration. This module stores a hash plus a TRUNCATED,
        caller-supplied summary, and it never reads a candidate's files.
      * DETERMINISTIC BY DEFAULT. Upstream calls the global ``random``. Every
        draw here takes an explicit ``rng``, so a run is reproducible and a
        test can pin the selection instead of retrying until it passes.
      * BOUNDED. Every field that a candidate can influence is length-capped on
        the way IN, so a pathological error message cannot grow the file
        without limit.

NOTHING HERE SPENDS, WRITES CODE, OR GATES ANYTHING
---------------------------------------------------
This module appends JSON lines to a file the caller names, and reads them
back. It calls no model, imports no provider, touches no lane, and is not
wired into any gate or promotion path. Evolution stays ADVISORY until fitness
is trustworthy; this is a notebook, not a judge.

The one safety property worth stating plainly: :func:`sample_inspirations`
returns records, and a record's ``summary`` is the ONLY free text on it. A
caller that renders these into a prompt is responsible for the egress
decision -- this module makes that easy to audit by ensuring there is exactly
one field to audit.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "MAX_SUMMARY_CHARS",
    "NUM_DIVERSE",
    "NUM_ELITE",
    "OUTCOME_RANK",
    "Attempt",
    "digest_patch",
    "load_attempts",
    "record_attempt",
    "sample_inspirations",
]

# Outcome vocabulary, ordered WORST-to-BEST. Mirrored deliberately rather than
# imported: `daedalus.eval.correctness` is a heavyweight module and this one is
# meant to stay a leaf. `tests/test_kairos_archive.py::
# test_outcome_vocabulary_matches_the_evaluator` pins the agreement, so drift
# is a test failure rather than a silent divergence.
OUTCOME_RANK: dict[str, int] = {
    "task_invalid": 0,
    "could_not_run": 1,
    "regressed": 2,
    "not_fixed": 3,
    "fixed": 4,
}

# Upstream config.py:268-269 -- num_top_programs=3, num_diverse_programs=2.
NUM_ELITE = 3
NUM_DIVERSE = 2

# A candidate-influenced string. Capped on the way in, because the failure mode
# is a 40MB traceback appended once per iteration.
MAX_SUMMARY_CHARS = 600


@dataclass(frozen=True)
class Attempt:
    """One evaluated candidate, reduced to what the next attempt can use.

    Deliberately NOT a program record. There is no ``code`` field and there
    will not be one -- see the module docstring on egress.
    """

    attempt_id: str
    outcome: str
    patch_digest: str = ""
    summary: str = ""            # truncated, candidate-influenced
    unfixed: tuple[str, ...] = ()  # test node ids still failing
    ts: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def rank(self) -> int:
        """Where this sits in the outcome ordering. Unknown outcomes sort worst."""
        return OUTCOME_RANK.get(self.outcome, -1)

    def to_dict(self) -> dict:
        return asdict(self) | {"unfixed": list(self.unfixed)}

    @classmethod
    def from_dict(cls, data: dict) -> "Attempt":
        return cls(
            attempt_id=str(data.get("attempt_id", "")),
            outcome=str(data.get("outcome", "")),
            patch_digest=str(data.get("patch_digest", "")),
            summary=str(data.get("summary", "")),
            unfixed=tuple(str(x) for x in data.get("unfixed", ())),
            ts=float(data.get("ts", 0.0) or 0.0),
            meta=dict(data.get("meta") or {}),
        )


def digest_patch(patch: bytes | str) -> str:
    """Stable short identity for a change, so duplicates are recognisable.

    A digest, not the patch. Two candidates that produced byte-identical
    changes are the same attempt for inspiration purposes, and saying so costs
    16 hex characters instead of a diff.
    """
    raw = patch.encode("utf-8", errors="replace") if isinstance(patch, str) else patch
    return hashlib.sha256(raw).hexdigest()[:16]


def _truncate(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    # Keep the TAIL: a traceback's last lines carry the actual error, and the
    # head is import noise.
    return "..." + text[-(limit - 3):]


def record_attempt(path: str | Path, attempt: Attempt) -> Attempt:
    """Append one attempt to the JSONL notebook. Returns what was stored.

    Append-only and one JSON object per line, so a crashed run leaves a
    readable prefix rather than a corrupt document, and two processes appending
    cannot interleave a half-record into another's.

    Truncation happens HERE, not at the call site, so there is a single place
    that decides how much candidate-influenced text is allowed to persist.
    """
    stored = Attempt(
        attempt_id=attempt.attempt_id,
        outcome=attempt.outcome,
        patch_digest=attempt.patch_digest,
        summary=_truncate(attempt.summary),
        unfixed=tuple(attempt.unfixed[:20]),
        ts=attempt.ts or time.time(),
        meta=attempt.meta,
    )
    target = Path(path)
    # MEASURED 2026-09-02: a buffered ``open("a")`` here lost 6 of 60 records
    # with four concurrent processes, silently -- exit code 0, no malformed
    # line, nothing for a reader to count. This archive is a PERSISTENT
    # CROSS-RUN store (``load_attempts`` feeds the next generation), so two
    # runs sharing an ``--archive`` path is a normal configuration rather than
    # an exotic one.
    #
    # The docstring above ASSERTED this property -- "two processes appending
    # cannot interleave a half-record into another's" -- while not having it.
    # That is part of why the loss went unexamined for so long: the guarantee
    # was written down, so nobody measured it. It holds now, for the reason the
    # docstring gives rather than by luck of the buffer size.
    from ..journal_io import append_lines

    append_lines(target, [json.dumps(stored.to_dict(), sort_keys=True)])
    return stored


def load_attempts(path: str | Path) -> tuple[Attempt, ...]:
    """Read the notebook. Never raises.

    A line that will not parse is SKIPPED rather than fatal: this is advisory
    data, and a torn final line from a killed process must not take down the
    run that comes after it.
    """
    target = Path(path)
    if not target.is_file():
        return ()
    out: list[Attempt] = []
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(Attempt.from_dict(json.loads(line)))
        except (ValueError, TypeError, AttributeError):
            continue
    return tuple(out)


def sample_inspirations(
    attempts: Sequence[Attempt] | Iterable[Attempt],
    *,
    n_elite: int = NUM_ELITE,
    n_diverse: int = NUM_DIVERSE,
    exclude_digest: str = "",
    rng: random.Random | None = None,
) -> tuple[Attempt, ...]:
    """Pick a few prior attempts worth showing the next one.

    Adapted from upstream ``database.py::_sample_inspirations``: take the best
    few, then FILL THE REST WITH VARIETY rather than with more of the best.
    Upstream draws its variety from neighbouring MAP-Elites cells; without a
    feature grid we approximate the same intent by preferring attempts whose
    OUTCOME class is not already represented, which is the coarsest honest
    diversity signal available from data we actually have.

    Two properties upstream does not have:

    * DEDUPLICATION BY DIGEST. Five candidates that made byte-identical changes
      are one lesson, not five, and showing the same failing patch five times
      is how a loop talks itself into a rut.
    * ``exclude_digest`` drops the attempt currently being worked on, so a
      candidate is never offered itself as inspiration.

    Failures are as instructive as successes here -- a ``regressed`` attempt
    tells the next one what not to touch -- so this does NOT filter to winners.
    Ordering is best-first and fully deterministic given ``rng``.
    """
    rng = rng or random.Random(0)
    pool: list[Attempt] = []
    seen: set[str] = {exclude_digest} if exclude_digest else set()
    for a in attempts:
        if a.patch_digest and a.patch_digest in seen:
            continue
        if a.patch_digest:
            seen.add(a.patch_digest)
        pool.append(a)

    if not pool:
        return ()

    # Best first; ties broken by recency, then by id so the order is total.
    ranked = sorted(pool, key=lambda a: (-a.rank, -a.ts, a.attempt_id))
    elite = ranked[:max(0, n_elite)]
    chosen_ids = {a.attempt_id for a in elite}

    # Variety: prefer outcome classes the elite slice did not already show.
    remaining = [a for a in ranked if a.attempt_id not in chosen_ids]
    covered = {a.outcome for a in elite}
    fresh = [a for a in remaining if a.outcome not in covered]
    stale = [a for a in remaining if a.outcome in covered]
    rng.shuffle(fresh)
    rng.shuffle(stale)
    diverse = (fresh + stale)[:max(0, n_diverse)]

    return tuple(elite) + tuple(diverse)
