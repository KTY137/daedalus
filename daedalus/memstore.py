"""memstore.py -- the memory ledger core: memory that cannot silently lie.

The canonical store is an APPEND-ONLY, HASH-CHAINED JSONL file at
``memory/ledger.local.jsonl``. It is fail-loud, human-diffable, and tamper-
evident: every line carries the SHA of the line before it, so a flipped byte or a
deleted INTERIOR line breaks the chain and ``verify_ledger`` NAMES the offending
line. TAIL truncation (lopping the last N lines -- any prefix of a valid chain is
itself valid) is caught only against a ``ledger_head`` anchor passed back to
``verify_ledger`` as ``expected_count`` / ``expected_head``.
SQLite / vector indexes are later, rebuildable sidecars -- NOT here. The derived
fold state (``memory/state.local.json``) is likewise rebuildable from the ledger,
the same way ``memory.refresh_todo_snapshot`` rebuilds its snapshot.

WHAT IS IN A HASH, AND WHERE THE BOUNDARY IS
--------------------------------------------
Two SHAs per line, mirroring ``dctx.py``'s canonical-hash discipline (one place,
one answer to "is this field in the hash?"):

  * ``body_sha`` -- ``sha256`` over ``json.dumps(canonical_body, sort_keys=True,
    separators=(",",":"), ensure_ascii=True)`` where ``canonical_body`` is the
    record MINUS the four fields that are position/identity, not content:
    ``ts``, ``prev``, ``entry_sha``, ``id`` (and ``body_sha`` itself). It is the
    content fingerprint: same body -> same ``body_sha`` -> dedupe.
  * ``entry_sha`` -- ``sha256(prev + "\\0" + body_sha + "\\0" + ts)``. This is the
    CHAIN link: it binds this line's content to the previous line's ``entry_sha``
    and to the timestamp, so no line can be reordered, back-dated, or dropped
    without breaking the recomputation. ``prev`` is ``None`` on the genesis line
    and is folded into the hash as the empty string (a real ``prev`` is always a
    64-hex digest, so "" is unambiguously "genesis").

Excluding ``ts`` from ``body_sha`` is deliberate: it lets the SAME logical entry
minted twice dedupe by content, while ``entry_sha`` still pins WHEN and AFTER-WHAT
it landed. Timestamps are IN the chain hash (unlike dctx, which has none) because
an append-only ledger's whole value is the order it records.

SECRET FLOOR AT WRITE
---------------------
``append_entry`` runs ``sensitivity.secret_floor_rule`` over EVERY free-text
channel -- ``text``, ``proof.detail``, the six ``provenance`` strings, the three
``refs`` strings, and ``anchor.commit_sha`` -- BEFORE writing. If it fires the
entry is REFUSED and never touches the file; in its place a redacted
``kind="gate_outcome"`` entry is appended recording ONLY the rule name that fired
-- never the matched secret. That receipt re-embeds the refused entry's
provenance so the operator can see whose entry was refused, but it is re-scanned
first: a provenance-borne secret is dropped rather than smuggled into the receipt. The floor is the same
unconditional, every-lane rule the slice egress gate uses; it cannot be weakened
by project policy.

All paths are injectable (``store_path`` / ``state_path`` params with module
defaults) so tests never touch the real ``memory/`` directory.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .sensitivity import secret_floor_rule

# --------------------------------------------------------------------------- #
# constants                                                                    #
# --------------------------------------------------------------------------- #
ENTRY_VERSION = "dmem/1"
STATE_VERSION = "dmem-state/1"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER_PATH = ROOT / "memory" / "ledger.local.jsonl"
DEFAULT_STATE_PATH = ROOT / "memory" / "state.local.json"

# Promotion floor: below this many independent confirmations an entry stays
# quarantined. Deliberately mirrors ``daedalus.eval.mint.MINT_CONFIRM_THRESHOLD``
# (a single diff-derived label can be a mechanical-noise false positive; three
# independent landings are a defensible floor before a memory influences recall).
# CITED, not imported: coupling the memory ledger's promotion rule to the eval
# minting module's import graph would drag eval's dependencies into every recall.
MEM_CONFIRM_THRESHOLD = 3

LAYERS = ("episodic", "semantic", "procedural")
KINDS = ("landed_edit", "receipt_ref", "repair_recipe", "gate_outcome",
         "backfill_commit")

# Serializes the read-then-append below so parallel dispatch can't interleave two
# rows into one corrupt line, and can't compute two lines against the same `prev`
# (Windows append is not guaranteed atomic). Follows metrics.py's lock pattern.
_WRITE_LOCK = threading.Lock()

# The fields that are position/identity, NOT content -- excluded from body_sha so
# the same logical body dedupes regardless of when/where it landed in the chain.
_NON_BODY_FIELDS = frozenset({"ts", "prev", "entry_sha", "id", "body_sha"})

# The dmem/1 envelope's accepted input keys. A caller field outside these sets is
# REFUSED (loud ValueError), never silently dropped -- silent-drop lets two
# semantically distinct inputs canonicalise to the same body_sha and dedupe the
# second away while the caller holds a success id for a fact that was never
# recorded (memory that silently lies). ``trust`` is accepted-then-forced (its
# value is ignored, minted_tier is always "quarantine"), so it is a KNOWN key,
# not an unknown one.
_ALLOWED_ENTRY_KEYS = frozenset(
    {"layer", "kind", "text", "provenance", "anchor", "proof", "refs",
     "paths", "trust"})
_ALLOWED_PROV_KEYS = frozenset(
    {"source", "task_id", "agent", "provider", "persona", "project"})
_ALLOWED_ANCHOR_KEYS = frozenset({"commit_sha", "commit_status"})
_ALLOWED_PROOF_KEYS = frozenset({"type", "receipt_sha", "verify_ok", "detail"})
_ALLOWED_REFS_KEYS = frozenset({"draft_id", "run_report", "accept_ts"})

# Per-store append index: an append needs only the set of body_shas (dedup) and
# the tail entry_sha (the chain's prev link). Re-parsing the whole ledger on
# every append is O(n)-per-append / O(n^2)-overall; this caches those two facts
# keyed by resolved path, invalidated whenever the file's (size, mtime_ns) no
# longer matches what we last observed -- a cross-process append is always a size
# change, so it forces a full reload and can never bind a stale ``prev``. The
# ledger file stays the sole source of truth; this is a rebuildable index guarded
# by ``_WRITE_LOCK`` (only ever read/written while that lock is held).
_APPEND_CACHE: dict[str, dict] = {}


# --------------------------------------------------------------------------- #
# hashing -- the single source of truth for the two SHAs                       #
# --------------------------------------------------------------------------- #
def _canonical_body(record: dict) -> dict:
    """The content projection body_sha is taken over: everything EXCEPT the
    position/identity fields. Uniform across entry and control records so the
    chain walk in ``verify_ledger`` needs no per-record-type branch."""
    return {k: v for k, v in record.items() if k not in _NON_BODY_FIELDS}


def _body_sha(record: dict) -> str:
    canon = _canonical_body(record)
    return hashlib.sha256(json.dumps(
        canon, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _entry_sha(prev: str | None, body_sha: str, ts: str) -> str:
    """The chain link. ``prev`` None (genesis) folds in as "" -- unambiguous,
    since any real ``prev`` is a 64-hex digest."""
    payload = (prev or "") + "\0" + body_sha + "\0" + ts
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# secret floor scan                                                            #
# --------------------------------------------------------------------------- #
def _scan_secret(record: dict) -> str | None:
    """Run the unconditional secret floor over EVERY free-text channel of an
    entry, plus a path-marker check over its paths. Returns the rule name that
    fired (a fixed label / path fragment -- NEVER matched text), or None.

    ``secret_floor_rule(path, text)`` checks the path for secret path markers and
    the text for value-shaped credentials; we feed both channels. The content
    scan covers not just ``text`` and ``proof.detail`` but the six free-text
    provenance strings, the three ``refs`` strings, and ``anchor.commit_sha`` --
    any of which is a caller-/prompt-injection-controlled channel that would
    otherwise carry a value-shaped credential verbatim into the hash-chained
    ledger, where it can never be redacted without breaking ``verify_ledger``."""
    # Path markers (.env, id_rsa, .pem, ...) are attributable to a path alone.
    for p in record.get("paths") or []:
        hit = secret_floor_rule(p, "")
        if hit:
            return hit
    # Content channel: the recallable free text and every provenance/refs/anchor/
    # proof-detail string. A hit here is value-shaped, not keyword-shaped, so an
    # ordinary provenance string ("daedalus", a task id) never trips it.
    hint = (record.get("paths") or [""])[0]
    texts: list[str] = []
    if record.get("text"):
        texts.append(str(record["text"]))
    for d in (record.get("proof") or {}).get("detail") or []:
        texts.append(str(d))
    for v in (record.get("provenance") or {}).values():
        if v:
            texts.append(str(v))
    for v in (record.get("refs") or {}).values():
        if v:
            texts.append(str(v))
    commit_sha = (record.get("anchor") or {}).get("commit_sha")
    if commit_sha:
        texts.append(str(commit_sha))
    for t in texts:
        hit = secret_floor_rule(hint, t)
        if hit:
            return hit
    return None


# --------------------------------------------------------------------------- #
# envelope construction                                                        #
# --------------------------------------------------------------------------- #
def _normalize_paths(paths) -> list[str]:
    if not paths:
        return []
    # /-normalised, deduped, sorted -- a manifest of claims, not a rendering.
    return sorted({str(p).replace("\\", "/") for p in paths})


def _reject_unknown(sub: dict, allowed: frozenset, ctx: str) -> None:
    """Fail LOUD on any caller field outside the envelope. Silent-drop is the
    defect: a dropped field lets two distinct inputs hash identically and dedupe,
    so the caller gets a success id for a fact the ledger never kept."""
    if not isinstance(sub, dict):
        return
    extra = sorted(set(sub) - allowed)
    if extra:
        raise ValueError(
            f"unknown {ctx} field(s) {extra!r}: memstore refuses to silently "
            f"drop caller data (it would let distinct inputs dedupe as one)")


def _normalize_entry(d: dict) -> dict:
    """Fill the dmem/1 envelope from a (possibly partial) input dict, fail-closed.

    Absence is REPORTED, never guessed favourably: an unspecified git anchor is
    ``commit_status="git_unavailable"`` (we did not check), not a fabricated "ok";
    ``trust.minted_tier`` is ALWAYS forced to "quarantine" at write -- trust is
    earned through ``fold_state``, never asserted by the caller. A caller field
    OUTSIDE the envelope is refused loudly, never dropped (see ``_reject_unknown``)."""
    _reject_unknown(d, _ALLOWED_ENTRY_KEYS, "entry")
    layer = d.get("layer", "episodic")
    kind = d.get("kind", "landed_edit")
    if layer not in LAYERS:
        raise ValueError(f"layer must be one of {LAYERS!r}, got {layer!r}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS!r}, got {kind!r}")

    prov_in = d.get("provenance") or {}
    _reject_unknown(prov_in, _ALLOWED_PROV_KEYS, "provenance")
    _reject_unknown(d.get("anchor") or {}, _ALLOWED_ANCHOR_KEYS, "anchor")
    _reject_unknown(d.get("proof") or {}, _ALLOWED_PROOF_KEYS, "proof")
    _reject_unknown(d.get("refs") or {}, _ALLOWED_REFS_KEYS, "refs")
    provenance = {
        "source": prov_in.get("source", ""),
        "task_id": prov_in.get("task_id", ""),
        "agent": prov_in.get("agent", ""),
        "provider": prov_in.get("provider", ""),
        "persona": prov_in.get("persona", ""),
        "project": prov_in.get("project", ""),
    }
    anch_in = d.get("anchor") or {}
    anchor = {
        "commit_sha": anch_in.get("commit_sha"),
        "commit_status": anch_in.get("commit_status", "git_unavailable"),
    }
    proof_in = d.get("proof") or {}
    proof = {
        "type": proof_in.get("type", "none"),
        "receipt_sha": proof_in.get("receipt_sha"),
        "verify_ok": proof_in.get("verify_ok"),
        # detail carries rule/check NAMES only -- never matched text.
        "detail": sorted(str(x) for x in (proof_in.get("detail") or [])),
    }
    refs_in = d.get("refs") or {}
    refs = {
        "draft_id": refs_in.get("draft_id"),
        "run_report": refs_in.get("run_report"),
        "accept_ts": refs_in.get("accept_ts"),
    }
    return {
        "record": "entry",
        "entry_version": ENTRY_VERSION,
        "layer": layer,
        "kind": kind,
        "text": d.get("text", ""),
        "provenance": provenance,
        "anchor": anchor,
        "proof": proof,
        "trust": {"minted_tier": "quarantine"},
        "paths": _normalize_paths(d.get("paths")),
        "refs": refs,
    }


# --------------------------------------------------------------------------- #
# low-level append -- the only writer                                          #
# --------------------------------------------------------------------------- #
def _file_sig(store_path: Path):
    """(size, mtime_ns) signature, or None if the file is absent. Any append
    grows the size, so a cross-process write always changes the signature."""
    try:
        st = store_path.stat()
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _append_index(store_path: Path) -> dict:
    """The dedup body_sha set + tail entry_sha for ``store_path``, cached and
    invalidated by file signature. MUST be called under ``_WRITE_LOCK``.

    On a cache miss (first append, or the file changed underneath us -- e.g. a
    concurrent process appended, or a test rewrote it) we reload the full ledger
    once; sequential single-process appends then reuse the in-memory index, so
    the common path is O(1) amortised instead of O(n) per append."""
    key = str(store_path.resolve())
    sig = _file_sig(store_path)
    cached = _APPEND_CACHE.get(key)
    if cached is not None and cached["sig"] == sig:
        return cached
    records = load_ledger(store_path)
    idx = {
        "sig": sig,
        "body_shas": {r.get("body_sha") for r in records},
        "tail": records[-1].get("entry_sha") if records else None,
    }
    _APPEND_CACHE[key] = idx
    return idx


def _ends_without_newline(store_path: Path) -> bool:
    """True iff the file exists, is non-empty, and its last byte is not '\\n'
    (a torn tail line from a crash mid-write -- the state load_ledger tolerates)."""
    sig = _file_sig(store_path)
    if not sig or sig[0] == 0:
        return False
    with store_path.open("rb") as fh:
        fh.seek(-1, 2)
        return fh.read(1) != b"\n"


def _finalize_and_write(record: dict, store_path: Path, ts: str | None,
                        *, dedup: bool) -> str:
    """Compute the chain fields against the current tail and append one line.

    Read-then-write happens INSIDE the lock so a concurrent append can neither
    interleave a torn line nor bind two lines to the same ``prev``. ``dedup``
    (entries only) makes an append whose ``body_sha`` already exists a NO-OP that
    returns the existing id (``body_sha[:16]``, the id the existing line carries).

    A torn (newline-less) tail line is separated with a leading newline before we
    write, so this record lands as its own parseable line instead of fusing onto
    the fragment and being destroyed while we hand the caller a success id. The
    fragment remains one flagged/unparseable line for ``verify_ledger``."""
    store_path = Path(store_path)
    body_sha = _body_sha(record)
    with _WRITE_LOCK:
        idx = _append_index(store_path)
        if dedup and body_sha in idx["body_shas"]:
            return body_sha[:16]
        prev = idx["tail"]
        ts = ts or _now_iso()
        entry_sha = _entry_sha(prev, body_sha, ts)
        record["body_sha"] = body_sha
        record["id"] = body_sha[:16]
        record["prev"] = prev
        record["ts"] = ts
        record["entry_sha"] = entry_sha
        store_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        prefix = "\n" if _ends_without_newline(store_path) else ""
        with store_path.open("a", encoding="utf-8") as fh:
            fh.write(prefix + line + "\n")
        # Update the index to our just-written state (add body_sha for dedup, move
        # the tail, and re-stat so the signature matches what we wrote).
        idx["body_shas"].add(body_sha)
        idx["tail"] = entry_sha
        idx["sig"] = _file_sig(store_path)
    return record["id"]


# --------------------------------------------------------------------------- #
# public append API                                                            #
# --------------------------------------------------------------------------- #
def append_entry(entry_dict: dict, store_path: str | Path | None = None,
                 ts: str | None = None) -> str:
    """Append one memory entry, secret-floored. Returns the entry id.

    If the secret floor fires, the entry is REFUSED (never written) and a redacted
    ``gate_outcome`` entry naming only the rule is appended instead -- its id is
    returned so the caller has a receipt. A body already in the ledger is a no-op
    returning the existing id. ``ts`` may be pinned for deterministic tests."""
    store_path = Path(store_path or DEFAULT_LEDGER_PATH)
    record = _normalize_entry(entry_dict)
    fired = _scan_secret(record)
    if fired:
        # REFUSE. The rule name (a fixed label / path fragment) is safe to store;
        # the offending entry -- and its secret -- never reaches the file.
        def _mk(prov):
            return _normalize_entry({
                "layer": "episodic",
                "kind": "gate_outcome",
                "text": f"entry refused by secret floor: {fired}",
                "provenance": prov,
                "proof": {"type": "gate_outcome", "receipt_sha": None,
                          "verify_ok": False, "detail": [fired]},
            })
        redacted = _mk(entry_dict.get("provenance"))
        # The receipt re-embeds the original provenance so the operator can see
        # WHICH task's entry was refused -- but that provenance is itself a
        # caller-controlled channel. If IT carries a secret, re-scanning catches
        # it and we drop the provenance entirely: the redacted receipt records
        # only the rule name, never a provenance-borne secret. Without this a
        # refused entry still lands a credential on the very path meant to be safe.
        if _scan_secret(redacted) is not None:
            redacted = _mk(None)
        # dedup=False: a refusal is an event, and two independent refusals of the
        # same rule are two facts worth recording in order.
        return _finalize_and_write(redacted, store_path, ts, dedup=False)
    return _finalize_and_write(record, store_path, ts, dedup=True)


def append_confirm(entry_id: str, store_path: str | Path | None = None,
                   ts: str | None = None) -> str:
    """Append one independent confirmation of ``entry_id`` as a control record.

    Not deduped: N confirmations are the WHOLE point (MEM_CONFIRM_THRESHOLD of
    them promote). Returns the confirm record's own id."""
    store_path = Path(store_path or DEFAULT_LEDGER_PATH)
    record = {
        "record": "confirm",
        "entry_version": ENTRY_VERSION,
        "target_id": entry_id,
    }
    return _finalize_and_write(record, store_path, ts, dedup=False)


def append_flag(entry_id: str, failures: list[str],
                store_path: str | Path | None = None,
                ts: str | None = None) -> str:
    """Append a flag against ``entry_id`` carrying its failure list, as a control
    record. A flag is terminal in the fold. Returns the flag record's own id."""
    store_path = Path(store_path or DEFAULT_LEDGER_PATH)
    record = {
        "record": "flag",
        "entry_version": ENTRY_VERSION,
        "target_id": entry_id,
        # sorted: a set of check names, not an ordered rendering (determinism).
        "failures": sorted(str(f) for f in (failures or [])),
    }
    return _finalize_and_write(record, store_path, ts, dedup=False)


# --------------------------------------------------------------------------- #
# reading                                                                      #
# --------------------------------------------------------------------------- #
def load_ledger(store_path: str | Path | None = None) -> list[dict]:
    """Read all records, skipping any torn line (metrics._load posture): a
    half-written tail line is skipped, never fatal. A missing file is []."""
    store_path = Path(store_path or DEFAULT_LEDGER_PATH)
    if not store_path.exists():
        return []
    out: list[dict] = []
    text = store_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --------------------------------------------------------------------------- #
# tamper verification                                                          #
# --------------------------------------------------------------------------- #
def ledger_head(store_path: str | Path | None = None) -> tuple[int, str | None]:
    """The tamper-evidence tail anchor: ``(record_count, head_entry_sha)``.

    Snapshot this after a trusted write; pass it back to ``verify_ledger`` as
    ``expected_count`` / ``expected_head`` later to detect a TAIL truncation --
    which the plain chain walk (genesis-forward, backward-linkage only) cannot
    see, because any prefix of a valid chain is itself a valid chain."""
    records = load_ledger(store_path)
    return len(records), (records[-1].get("entry_sha") if records else None)


def verify_ledger(store_path: str | Path | None = None, *,
                  expected_count: int | None = None,
                  expected_head: str | None = None) -> tuple[bool, list[str]]:
    """Walk the chain; return ``(ok, failures)`` where every failure NAMES the
    1-indexed line and what mismatched. Never a bare False.

    Three independent checks per line:
      * ``body_sha`` recomputed over the canonical body -- catches a content edit
        (the tampered text no longer hashes to the recorded body_sha).
      * ``entry_sha`` recomputed over ``(prev, stored body_sha, ts)`` -- catches a
        back-dated ts or a rewritten link where body_sha WAS updated.
      * ``prev`` equals the previous line's ``entry_sha`` -- catches a deleted or
        reordered line (the survivor points at a vanished predecessor).
    A single-line tamper that rewrites body_sha AND entry_sha still breaks the
    NEXT line's prev linkage unless the whole tail is rewritten -- which is the
    hash chain doing its job.

    TAIL truncation is the one deletion the per-line walk cannot catch on its own
    (a valid chain's prefix is a valid chain, so lopping the last N lines -- or
    the whole file -- verifies clean). To close that, pass ``expected_count`` /
    ``expected_head`` from a prior :func:`ledger_head` snapshot: a shortfall in
    either is NAMED as a failure. Omitting them keeps the byte-identical legacy
    behaviour for callers with no anchor to check against."""
    store_path = Path(store_path or DEFAULT_LEDGER_PATH)
    failures: list[str] = []
    if not store_path.exists():
        if expected_count:
            failures.append(
                f"ledger missing but {expected_count} record(s) expected "
                f"(tail truncated to nothing or file deleted)")
        if expected_head:
            failures.append(
                f"ledger head absent, expected {expected_head} "
                f"(tail truncated or file deleted)")
        return (not failures), failures
    lines = store_path.read_text(encoding="utf-8", errors="replace").splitlines()
    prev_entry_sha: str | None = None
    n_records = 0
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            failures.append(f"line {i}: unparseable JSON (torn or corrupt)")
            # Cannot advance prev to a sha we don't have; leave it so the next
            # line's linkage check also flags, rather than silently re-syncing.
            continue
        n_records += 1
        stored_body = rec.get("body_sha")
        stored_entry = rec.get("entry_sha")
        calc_body = _body_sha(rec)
        if calc_body != stored_body:
            failures.append(f"line {i}: body_sha mismatch (content tampered)")
        calc_entry = _entry_sha(rec.get("prev"), stored_body or "", rec.get("ts", ""))
        if calc_entry != stored_entry:
            failures.append(f"line {i}: entry_sha mismatch (ts/prev/link tampered)")
        if rec.get("prev") != prev_entry_sha:
            failures.append(
                f"line {i}: prev linkage broken "
                f"(expected {prev_entry_sha}, found {rec.get('prev')})")
        prev_entry_sha = stored_entry
    if expected_count is not None and n_records != expected_count:
        failures.append(
            f"ledger length {n_records} != expected {expected_count} "
            f"(tail truncated or records dropped)")
    if expected_head is not None and prev_entry_sha != expected_head:
        failures.append(
            f"ledger head {prev_entry_sha} != expected {expected_head} "
            f"(tail truncated or rewritten)")
    return (not failures), failures


# --------------------------------------------------------------------------- #
# fold -- the derived trust state                                              #
# --------------------------------------------------------------------------- #
def fold_state(records: list[dict], state_path: str | Path | None = None,
               *, write: bool = True) -> dict:
    """Fold the ledger into ``{entry_id: {tier, confirmations, flags[]}}``.

    Rules: an entry enters ``quarantine``; each confirmation increments the count
    and ``quarantine`` -> ``primary`` at ``MEM_CONFIRM_THRESHOLD``; ANY flag sets
    ``flagged``, which is TERMINAL -- later confirmations stop counting and cannot
    resurrect it. Flagged entries carry their failure list. Writes the derived
    ``state.local.json`` (deterministic) unless ``write=False``."""
    state: dict[str, dict] = {}
    for rec in records:
        rt = rec.get("record")
        if rt == "entry":
            eid = rec.get("id")
            state.setdefault(eid, {"tier": "quarantine", "confirmations": 0,
                                   "flags": []})
        elif rt == "flag":
            # A flag whose target entry has not appeared YET (flag-before-entry:
            # entry ids are content-derivable before the append, and the write
            # lock is per-process) must NOT be silently dropped -- that would let
            # the entry be confirmed all the way to primary, defeating flag
            # terminality. Materialise a flagged placeholder instead: fail-CLOSED.
            # If the real entry record arrives later, its ``setdefault`` is a
            # no-op and the entry stays flagged; if it never arrives, the flag is
            # still recorded rather than lost.
            tid = rec.get("target_id")
            st = state.setdefault(
                tid, {"tier": "quarantine", "confirmations": 0, "flags": []})
            st["tier"] = "flagged"  # terminal, overrides even primary
            for f in rec.get("failures") or []:
                if f not in st["flags"]:
                    st["flags"].append(f)
        elif rt == "confirm":
            st = state.get(rec.get("target_id"))
            if st is None:
                continue
            if st["tier"] in ("flagged", "primary"):
                continue  # flagged is terminal; primary needs no more
            st["confirmations"] += 1
            if st["confirmations"] >= MEM_CONFIRM_THRESHOLD:
                st["tier"] = "primary"
    for st in state.values():
        st["flags"] = sorted(st["flags"])
    if write:
        # Record the tail anchor (count + head entry_sha) alongside the derived
        # state so a later verify has an independent length/head to check the
        # ledger against -- the one thing the genesis-forward chain walk cannot
        # reconstruct from a truncated file.
        head_sha = records[-1].get("entry_sha") if records else None
        _write_state(state, state_path, count=len(records), head_sha=head_sha)
    return state


def _write_state(state: dict, state_path: str | Path | None = None, *,
                 count: int | None = None, head_sha: str | None = None) -> str:
    """Write the derived fold state deterministically (sorted keys). Rebuildable
    from the ledger at any time, so this is a cache, never a source of truth.

    ``count`` / ``head_sha`` persist the ledger tail anchor (see ``ledger_head``)
    so tail truncation is detectable independently of the chain walk."""
    state_path = Path(state_path or DEFAULT_STATE_PATH)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state_version": STATE_VERSION, "entries": state,
               "ledger_count": count, "ledger_head": head_sha}
    with state_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True, indent=2, ensure_ascii=False)
    return str(state_path)
