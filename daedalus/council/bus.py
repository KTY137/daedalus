"""bus.py -- the council transcript: a deliberation that cannot silently lie.

An APPEND-ONLY, HASH-CHAINED JSONL file per council at
``runs/council/<council_id>.jsonl``. Fail-loud, human-diffable, tamper-evident:
every line carries the SHA of the line before it, so a flipped byte or a deleted
INTERIOR line breaks the chain and :func:`verify_chain` NAMES the offending
1-indexed line. TAIL truncation (any prefix of a valid chain is itself a valid
chain) is caught only against the head/count ANCHOR persisted beside the
transcript and re-checked on every verify.

SEPARATE STORE, ON PURPOSE
--------------------------
This is ``dcouncil/1``. It deliberately REIMPLEMENTS ``memstore.py``'s two-SHA
discipline instead of importing it, and it must never write to the memory
ledger. Reason, in one line: ``memstore.fold_state`` promotes an entry to
``primary`` after three independent confirmations, and four models discussing a
patch generate confident prose about the codebase -- three agreeing turns would
be three confirmations. A mechanism that promotes model opinion to certified
memory and then recalls it as fact is the fabrication failure this project
treats as the worst one. COUNCIL RECORDS ARE NEVER AN INPUT TO MEMORY RECALL.
Any store path under ``<repo>/memory/`` is refused loudly by :func:`_resolve_store`.

WHAT IS IN A HASH, AND WHERE THE BOUNDARY IS
--------------------------------------------
Two SHAs per line, mirroring ``memstore``/``dctx`` (one place, one answer to
"is this field in the hash?"):

  * ``body_sha`` -- ``sha256`` over ``json.dumps(canonical_body, sort_keys=True,
    separators=(",",":"), ensure_ascii=True)`` where ``canonical_body`` is the
    record MINUS the four position/identity fields ``ts``, ``prev``,
    ``entry_sha``, ``id`` (and ``body_sha`` itself).
  * ``entry_sha`` -- ``sha256(prev + "\\0" + body_sha + "\\0" + ts)``, the chain
    link. Genesis ``prev`` is ``None`` and folds in as ``""`` (unambiguous: a
    real ``prev`` is always a 64-hex digest).

Unlike ``memstore``, a turn's ``id`` is ``entry_sha[:16]``, not ``body_sha[:16]``,
and there is NO dedupe. A council transcript is a log of EVENTS: two
participants may legitimately emit byte-identical bodies, and deduping the
second away would erase a voice from the record.

DETERMINISTIC CHAINING UNDER CONCURRENT DISPATCH
------------------------------------------------
Dispatch may be concurrent; CHAINING MUST NOT BE. :func:`append_round` takes a
whole round's turns in ANY completion order, sorts them by the vendor-namespaced
actor id, assigns ``seq`` at chain time, and stamps ONE chain timestamp for the
round. The same fixture responses delivered in reversed completion order
therefore produce a byte-identical chain head, so an offline verifier proves
"this is the council that happened", not merely "nobody edited this file".
Real per-turn wall-clock lives in ``meta.latency_ms`` / ``meta.started_ts``,
which are body content, not chain position.

SECRET FLOOR AT WRITE -- PER PATH, PER TEXT, NEVER OVER A BLOB
--------------------------------------------------------------
``sensitivity.secret_floor_rule`` has two independent channels and they are fed
SEPARATELY here, because a concatenated scan kills the path tier exactly where
diffs add secrets:

  * PATH channel: every evidence path, INDIVIDUALLY.
  * CONTENT channel: the turn content, every ref, and every metadata string,
    each scanned on its own -- never over the assembled turn.

This runs on OUTBOUND turns and, critically, on INBOUND vendor responses BEFORE
they are chained: once a secret is inside a hash-chained line it can never be
redacted without breaking :func:`verify_chain`, so a tamper-evident transcript
would become a permanent, un-deletable copy of whatever the floor missed.

A hit REFUSES the turn -- no redact-and-send, no redact-and-store. In its place
a ``status="refused"`` receipt is chained naming ONLY the rule label (a fixed
string, never matched text), so the record still shows WHO was refused and in
which round. The receipt is re-scanned before it is written; if the identity
fields themselves carry the secret the receipt degrades to an anonymous one
rather than smuggling the credential onto the very path meant to be safe.

ONE CARVE-OUT, DELIBERATE: ``withheld`` (paths an egress lane declined to send)
is scanned with the CONTENT channel only, never the path channel. Withheld
paths are the paths that did NOT leave the machine; naming them is the whole
point of the field, and running the path tier over them would refuse the turn
that proves the floor worked.

EVERY REQUESTED PARTICIPANT PRODUCES EXACTLY ONE CHAINED TURN PER ROUND --
content, ``refused``, ``unavailable`` with a machine reason, or
``budget_exhausted``. Silence is never an absence: a two-vendor council must
never render identically to a four-vendor one.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..sensitivity import secret_floor_rule

# --------------------------------------------------------------------------- #
# constants                                                                    #
# --------------------------------------------------------------------------- #
ENTRY_VERSION = "dcouncil/1"
ANCHOR_VERSION = "dcouncil-anchor/1"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COUNCIL_DIR = ROOT / "runs" / "council"
# The one directory a council write may never touch: the memory ledger's home.
_FORBIDDEN_STORE_DIR = ROOT / "memory"

# A turn is one of these and nothing else. There is deliberately no "ok" here:
# a status value that reads as a verdict is one grep away from becoming one.
TURN_STATUS = ("spoke", "refused", "unavailable", "budget_exhausted", "anomaly")

# Machine reasons -- fixed vocabulary, so "why is this council degraded?" is
# answerable by a filter and not by reading prose.
UNAVAILABLE_REASONS = (
    "not_on_path", "not_authenticated", "timeout", "connect_failed",
    "transport_error", "budget_exhausted", "unavailable_unknown",
)
ANOMALY_REASONS = (
    "instruction_in_evidence", "unrequested_evidence", "malformed_response",
    "duplicate_class", "unnamed_model",
)
PARTICIPANT_OUTCOMES = (
    "requested", "seated", "responded", "refused", "unavailable",
)

# Fail-closed ceiling on a single turn. Transcript tokens grow as O(V^2 R^2),
# not O(V R); the per-council budget lives in session.py, but no single turn may
# blow the file up on its own.
MAX_CONTENT_CHARS = 200_000

# ADR-010 actor-namespace rule, pinned to the MODEL and not just the vendor:
# "claude said X" is not reproducible six months out, because the model behind a
# stable command name changes underneath it.
_ACTOR_RE = re.compile(r"^council\.[a-z0-9][a-z0-9_-]*\.[A-Za-z0-9][A-Za-z0-9._:+-]*$")
_COUNCIL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_WRITE_LOCK = threading.Lock()

# Position/identity fields, excluded from body_sha (see module docstring).
_NON_BODY_FIELDS = frozenset({"ts", "prev", "entry_sha", "id", "body_sha"})

# Accepted caller keys. A key outside this set is REFUSED loudly, never dropped:
# a silently dropped field lets two semantically distinct turns canonicalise to
# the same body and hands the caller a success id for a turn never recorded.
_ALLOWED_TURN_KEYS = frozenset({
    "actor", "vendor", "model", "independence_class", "role", "status",
    "content", "refs", "evidence", "withheld", "lane", "blind", "self_review",
    "duplicate_class", "reason", "meta",
})
_ALLOWED_META_KEYS = frozenset({
    "cli_version", "endpoint", "started_ts", "latency_ms", "prompt_tokens",
    "completion_tokens", "cost_usd", "transport",
})
_ALLOWED_PARTICIPANT_KEYS = frozenset({
    "actor", "vendor", "model", "independence_class", "lane", "outcome",
    "reason", "withheld",
})

# Per-store append index: tail entry_sha + record/turn counts, keyed by resolved
# path and invalidated by the file's (size, mtime_ns). Re-parsing the whole
# transcript per append is O(n^2) overall; a 500-turn council must not pay that.
_APPEND_CACHE: dict[str, dict] = {}


# --------------------------------------------------------------------------- #
# hashing -- the single source of truth for the two SHAs                       #
# --------------------------------------------------------------------------- #
def canonical_body(record: dict) -> dict:
    """The content projection ``body_sha`` is taken over: everything EXCEPT the
    position/identity fields. Uniform across turn and roster records so the
    chain walk needs no per-record-type branch."""
    return {k: v for k, v in record.items() if k not in _NON_BODY_FIELDS}


def canonical_body_json(record: dict) -> str:
    """The exact bytes hashed. Exposed so a test can assert determinism against
    the canonical form rather than against a digest it cannot inspect."""
    return json.dumps(canonical_body(record), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)


def _body_sha(record: dict) -> str:
    return hashlib.sha256(canonical_body_json(record).encode("utf-8")).hexdigest()


def _entry_sha(prev: str | None, body_sha: str, ts: str) -> str:
    payload = (prev or "") + "\0" + body_sha + "\0" + ts
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# identity / paths                                                             #
# --------------------------------------------------------------------------- #
def actor_id(vendor: str, model: str) -> str:
    """``council.<vendor>.<model>`` per ADR-010. An unknown model id is recorded
    as the literal ``unknown`` by the CALLER -- never omitted, never inferred."""
    return f"council.{vendor}.{model}"


def evidence_ref(path: str, data: bytes) -> dict:
    """One evidence citation: the path as given plus the sha256 of the exact
    bytes shown to the model. Two participants citing "the file" may have been
    shown different bytes; without this the transcript records a citation that
    cannot be reproduced."""
    return {"path": str(path).replace("\\", "/"),
            "sha256": hashlib.sha256(data).hexdigest()}


def council_store_path(council_id: str, base_dir: str | Path | None = None) -> Path:
    """``<base_dir>/<council_id>.jsonl``. ``council_id`` is filename-safe by
    validation, not by sanitising: a silently rewritten id would point two
    councils at one transcript."""
    _check_council_id(council_id)
    return Path(base_dir or DEFAULT_COUNCIL_DIR) / f"{council_id}.jsonl"


def anchor_path(store_path: str | Path) -> Path:
    """The head/count anchor beside the transcript. Separate file on purpose:
    the chain walk cannot detect tail truncation from a truncated file alone."""
    p = Path(store_path)
    return p.with_name(p.name + ".anchor.json")


def _check_council_id(council_id: str) -> None:
    if not isinstance(council_id, str) or not _COUNCIL_ID_RE.match(council_id):
        raise ValueError(
            f"council_id {council_id!r} must match {_COUNCIL_ID_RE.pattern} "
            f"(it becomes a filename; no separators, no traversal)")


def _resolve_store(council_id: str, store_path: str | Path | None) -> Path:
    """Resolve and REFUSE any path under ``<repo>/memory/``. Council turns must
    never reach the memory ledger (see module docstring)."""
    p = Path(store_path) if store_path else council_store_path(council_id)
    resolved = Path(p).resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
    try:
        resolved.relative_to(_FORBIDDEN_STORE_DIR.resolve())
    except ValueError:
        return p
    raise ValueError(
        f"refusing council store at {p}: council turns must never be written "
        f"under {_FORBIDDEN_STORE_DIR} (the memory ledger's home)")


# --------------------------------------------------------------------------- #
# secret floor scan                                                            #
# --------------------------------------------------------------------------- #
def _scan_paths(paths) -> str | None:
    """PATH channel, one path at a time -- so a hit is attributable to one path
    and a diff that ADDS ``.env`` cannot hide inside a blob."""
    for p in paths or ():
        hit = secret_floor_rule(str(p), "")
        if hit:
            return hit
    return None


def _scan_texts(texts) -> str | None:
    """CONTENT channel, one string at a time. ``path=""`` here is correct and is
    NOT the forbidden whole-prompt call: the path tier is run separately over
    every evidence path above, so it is never skipped."""
    for t in texts or ():
        if not t:
            continue
        hit = secret_floor_rule("", str(t))
        if hit:
            return hit
    return None


def _meta_strings(meta: dict) -> list[str]:
    return [str(v) for k, v in sorted((meta or {}).items())
            if isinstance(v, str) and v]


def _scan_turn(rec: dict) -> str | None:
    """Every free-text and every path channel of a turn. Returns the rule label
    that fired (a fixed string -- NEVER matched text), or None."""
    hit = _scan_paths([e["path"] for e in rec.get("evidence") or []])
    if hit:
        return hit
    texts = [rec.get("content"), rec.get("role"), rec.get("actor"),
             rec.get("vendor"), rec.get("model"), rec.get("lane"),
             rec.get("reason")]
    texts.extend(rec.get("refs") or [])
    # withheld: content channel ONLY (see the carve-out in the module docstring).
    texts.extend(rec.get("withheld") or [])
    texts.extend(e["path"] for e in rec.get("evidence") or [])
    texts.extend(_meta_strings(rec.get("meta")))
    ic = rec.get("independence_class") or {}
    texts.extend([ic.get("vendor"), ic.get("family")])
    return _scan_texts(texts)


def _scan_roster(rec: dict) -> str | None:
    for p in rec.get("participants") or []:
        texts = [p.get("actor"), p.get("vendor"), p.get("model"),
                 p.get("lane"), p.get("reason")]
        texts.extend(p.get("withheld") or [])
        ic = p.get("independence_class") or {}
        texts.extend([ic.get("vendor"), ic.get("family")])
        hit = _scan_texts(texts)
        if hit:
            return hit
    return None


# --------------------------------------------------------------------------- #
# envelope construction                                                        #
# --------------------------------------------------------------------------- #
def _reject_unknown(sub: dict, allowed: frozenset, ctx: str) -> None:
    extra = sorted(set(sub or ()) - allowed)
    if extra:
        raise ValueError(
            f"unknown {ctx} field(s) {extra!r}: the council bus refuses to "
            f"silently drop caller data (a dropped field is a turn the record "
            f"claims to hold and does not)")


def _norm_evidence(evidence) -> list[dict]:
    out = []
    for e in evidence or ():
        if not isinstance(e, dict) or set(e) != {"path", "sha256"}:
            raise ValueError(
                f"evidence item {e!r} must be exactly {{'path','sha256'}} -- "
                f"use evidence_ref(path, data)")
        sha = str(e["sha256"]).lower()
        if not _SHA256_RE.match(sha):
            raise ValueError(
                f"evidence sha256 {e['sha256']!r} is not a 64-hex digest: an "
                f"uncheckable citation is worse than none")
        out.append({"path": str(e["path"]).replace("\\", "/"), "sha256": sha})
    return sorted(out, key=lambda d: (d["path"], d["sha256"]))


def _norm_strs(values) -> list[str]:
    # sorted + deduped: a set of claims, not an ordered rendering (determinism).
    return sorted({str(v) for v in (values or ()) if str(v)})


def _norm_meta(meta) -> dict:
    _reject_unknown(meta, _ALLOWED_META_KEYS, "meta")
    m = meta or {}
    return {
        "cli_version": m.get("cli_version", "unknown"),
        "endpoint": m.get("endpoint", "unknown"),
        "started_ts": m.get("started_ts"),
        "latency_ms": m.get("latency_ms"),
        "prompt_tokens": m.get("prompt_tokens"),
        "completion_tokens": m.get("completion_tokens"),
        "cost_usd": m.get("cost_usd"),
        "transport": m.get("transport", "unknown"),
    }


def _norm_class(actor: str, vendor: str, ic) -> dict:
    """Independence is a property of WEIGHTS, not of endpoints: local
    ``qwen2.5-coder:7b`` and bench ``qwen2.5-coder:7b`` are one voice on two
    sockets. The class is (vendor, model family) and is mandatory."""
    if not isinstance(ic, dict) or set(ic) != {"vendor", "family"}:
        raise ValueError(
            f"{actor}: independence_class must be exactly "
            f"{{'vendor','family'}} -- (vendor, model family), never (host, "
            f"endpoint); a council of clones must be visible as one")
    return {"vendor": str(ic["vendor"]), "family": str(ic["family"])}


def _normalize_turn(council_id: str, round_no: int, d: dict) -> dict:
    """Fill the dcouncil/1 turn envelope, fail-closed. Absence is REPORTED,
    never guessed favourably."""
    _reject_unknown(d, _ALLOWED_TURN_KEYS, "turn")
    actor = str(d.get("actor", ""))
    if not _ACTOR_RE.match(actor):
        raise ValueError(
            f"actor {actor!r} must be council.<vendor>.<model> (ADR-010 "
            f"actor-namespace rule; a bare name in a durable record is a "
            f"defect, and a vendor without a model id is not reproducible)")
    status = str(d.get("status", "spoke"))
    if status not in TURN_STATUS:
        raise ValueError(f"status must be one of {TURN_STATUS!r}, got {status!r}")
    if status == "refused":
        raise ValueError(
            "status='refused' is MINTED by the secret floor, never asserted by "
            "a caller: a caller-authored refusal is an unverified claim that a "
            "scan happened")
    content = str(d.get("content", "") or "")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(
            f"turn content {len(content)} chars exceeds MAX_CONTENT_CHARS "
            f"{MAX_CONTENT_CHARS}: bound it before chaining, never after")
    reason = d.get("reason")
    if status == "spoke":
        if not content.strip():
            raise ValueError(
                f"{actor}: an empty 'spoke' turn is a silent degrade -- record "
                f"status='unavailable' with a machine reason instead")
        if reason is not None:
            raise ValueError(f"{actor}: a 'spoke' turn carries no reason")
    elif status == "unavailable":
        if reason not in UNAVAILABLE_REASONS:
            raise ValueError(
                f"{actor}: unavailable needs a machine reason from "
                f"{UNAVAILABLE_REASONS!r}, got {reason!r}")
    elif status == "budget_exhausted":
        reason = "budget_exhausted"
    elif status == "anomaly":
        if reason not in ANOMALY_REASONS:
            raise ValueError(
                f"{actor}: anomaly needs a reason from {ANOMALY_REASONS!r}, "
                f"got {reason!r}")
    vendor = str(d.get("vendor", "") or actor.split(".")[1])
    return {
        "record": "turn",
        "entry_version": ENTRY_VERSION,
        "council_id": council_id,
        "round": int(round_no),
        "seq": None,  # assigned at CHAIN time, not at dispatch time
        "actor": actor,
        "vendor": vendor,
        # "unknown" is recorded, never omitted and never inferred.
        "model": str(d.get("model", "") or "unknown"),
        "independence_class": _norm_class(actor, vendor, d.get("independence_class")),
        "role": str(d.get("role", "") or "participant"),
        "status": status,
        "content": content,
        "refs": _norm_strs(d.get("refs")),
        "evidence": _norm_evidence(d.get("evidence")),
        # Paths an egress lane declined to send. Named, not counted.
        "withheld": _norm_strs(d.get("withheld")),
        # untrusted by default: deciding a vendor is trusted with this repo's IP
        # is a policy decision, and a default argument must not make it.
        "lane": str(d.get("lane", "") or "untrusted"),
        "blind": bool(d.get("blind", False)),
        "self_review": bool(d.get("self_review", False)),
        "duplicate_class": bool(d.get("duplicate_class", False)),
        "reason": reason,
        "meta": _norm_meta(d.get("meta")),
    }


def _refusal_receipt(turn: dict, rule: str, *, anonymous: bool) -> dict:
    """A refused turn's stand-in. Carries the rule LABEL only -- never the
    matched text, never the content, never the evidence paths (the offending
    path is often the secret). ``anonymous`` drops even the identity fields, for
    when the identity itself tripped the floor."""
    ident = {
        "actor": turn["actor"] if not anonymous else "council.redacted.redacted",
        "vendor": turn["vendor"] if not anonymous else "redacted",
        "model": turn["model"] if not anonymous else "unknown",
        "independence_class": (turn["independence_class"] if not anonymous
                               else {"vendor": "redacted", "family": "redacted"}),
        "role": turn["role"] if not anonymous else "participant",
        "lane": turn["lane"] if not anonymous else "untrusted",
    }
    rec = dict(turn)
    rec.update(ident)
    rec.update({
        "status": "refused",
        "content": "",
        "refs": [],
        "evidence": [],
        "withheld": [],
        "reason": rule,
        # Numeric accounting survives a refusal (it cannot carry a credential);
        # the free-text meta strings do not.
        "meta": _norm_meta(None if anonymous else {
            "transport": turn["meta"].get("transport") or "unknown",
            "latency_ms": turn["meta"].get("latency_ms"),
        }),
    })
    return rec


# --------------------------------------------------------------------------- #
# low-level append -- the only writer                                          #
# --------------------------------------------------------------------------- #
def _file_sig(store_path: Path):
    try:
        st = store_path.stat()
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _chain_state(store_path: Path) -> dict:
    """Tail entry_sha + record/turn counts, cached and invalidated by file
    signature. MUST be called under ``_WRITE_LOCK``. Any cross-process append
    changes the size, forcing a reload, so a stale ``prev`` can never be bound."""
    key = str(store_path.resolve())
    sig = _file_sig(store_path)
    cached = _APPEND_CACHE.get(key)
    if cached is not None and cached["sig"] == sig:
        return cached
    records = load_transcript(store_path)
    state = {
        "sig": sig,
        "tail": records[-1].get("entry_sha") if records else None,
        "count": len(records),
        "turns": sum(1 for r in records if r.get("record") == "turn"),
    }
    _APPEND_CACHE[key] = state
    return state


def _ends_without_newline(store_path: Path) -> bool:
    sig = _file_sig(store_path)
    if not sig or sig[0] == 0:
        return False
    with store_path.open("rb") as fh:
        fh.seek(-1, 2)
        return fh.read(1) != b"\n"


def _write_anchor(store_path: Path, count: int, head: str | None,
                  council_id: str, ts: str) -> None:
    ap = anchor_path(store_path)
    payload = {"anchor_version": ANCHOR_VERSION, "council_id": council_id,
               "count": count, "head": head, "ts": ts}
    with ap.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True, indent=2, ensure_ascii=False)


def _chain_records(records: list[dict], store_path: Path, council_id: str,
                   ts: str | None) -> list[str]:
    """Chain a pre-ORDERED batch and append it. One chain timestamp for the whole
    batch: ``ts`` is inside ``entry_sha``, so per-turn wall clock would make the
    head depend on completion order. Read-then-write happens inside the lock so
    a concurrent append can neither tear a line nor bind two lines to one
    ``prev``. A torn (newline-less) tail is separated with a leading newline so
    this batch lands as its own parseable lines instead of fusing onto the
    fragment and being destroyed while the caller holds a success id."""
    ids: list[str] = []
    with _WRITE_LOCK:
        state = _chain_state(store_path)
        prev = state["tail"]
        ts = ts or _now_iso()
        seq = state["turns"]
        lines = []
        for rec in records:
            if rec.get("record") == "turn":
                rec["seq"] = seq
                seq += 1
            body_sha = _body_sha(rec)
            entry_sha = _entry_sha(prev, body_sha, ts)
            rec["body_sha"] = body_sha
            rec["prev"] = prev
            rec["ts"] = ts
            rec["entry_sha"] = entry_sha
            rec["id"] = entry_sha[:16]
            prev = entry_sha
            ids.append(rec["id"])
            lines.append(json.dumps(rec, sort_keys=True, ensure_ascii=False))
        store_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = "\n" if _ends_without_newline(store_path) else ""
        with store_path.open("a", encoding="utf-8") as fh:
            fh.write(prefix + "\n".join(lines) + "\n")
        state["tail"] = prev
        state["count"] += len(records)
        state["turns"] = seq
        _write_anchor(store_path, state["count"], prev, council_id, ts)
        state["sig"] = _file_sig(store_path)
    return ids


# --------------------------------------------------------------------------- #
# public append API                                                            #
# --------------------------------------------------------------------------- #
def append_round(council_id: str, round_no: int, turns: list[dict], *,
                 store_path: str | Path | None = None,
                 ts: str | None = None) -> list[str]:
    """Chain one whole round. ``turns`` may arrive in ANY completion order.

    Turns are normalised, secret-floored, then sorted by actor id and chained
    with ``seq`` assigned here -- so reversed completion order yields a
    byte-identical chain head. Returns the ids in CHAINED order.

    Exactly one turn per actor per round is allowed: a duplicate is a caller bug
    that would double a voice, and a missing participant must be recorded as an
    ``unavailable`` turn rather than skipped."""
    path = _resolve_store(council_id, store_path)
    if not turns:
        raise ValueError("a round with no turns is not a round: every requested "
                         "participant produces exactly one chained turn")
    prepared = []
    for t in turns:
        rec = _normalize_turn(council_id, round_no, t)
        rule = _scan_turn(rec)
        if rule:
            # REFUSE. The offending bytes never reach the file -- not in the
            # turn, and not in the receipt.
            receipt = _refusal_receipt(rec, rule, anonymous=False)
            if _scan_turn(receipt) is not None:
                receipt = _refusal_receipt(rec, rule, anonymous=True)
            rec = receipt
        prepared.append(rec)
    actors = [r["actor"] for r in prepared]
    dupes = sorted({a for a in actors if actors.count(a) > 1
                    and a != "council.redacted.redacted"})
    if dupes:
        raise ValueError(
            f"round {round_no}: {dupes!r} appear more than once -- exactly one "
            f"turn per participant per round")
    # Canonical body is the final tiebreak so the order is TOTAL even when two
    # anonymised refusal receipts collapse to the same actor: chaining must not
    # inherit wall-clock completion order from anywhere.
    prepared.sort(key=lambda r: (r["actor"], r["role"], r["status"],
                                 canonical_body_json(r)))
    return _chain_records(prepared, Path(path), council_id, ts)


def append_turn(council_id: str, round_no: int, turn: dict, *,
                store_path: str | Path | None = None,
                ts: str | None = None) -> str:
    """Chain a single turn (a one-participant round). Convenience over
    :func:`append_round`; prefer the round form so ordering stays deterministic."""
    return append_round(council_id, round_no, [turn],
                        store_path=store_path, ts=ts)[0]


def append_roster(council_id: str, participants: list[dict], *, phase: str = "open",
                  round_no: int | None = None,
                  store_path: str | Path | None = None,
                  ts: str | None = None) -> str:
    """Chain the roster accounting: requested / seated / responded / unavailable
    with machine reasons, plus the DISTINCT INDEPENDENCE CLASS count and a
    ``degraded`` flag whenever fewer participants responded than were requested.

    Counts are DERIVED here, never accepted from the caller: "3 of 4" and
    "2 of 2" must not be able to render as the same string, and a consumer that
    shows the participant count instead of the distinct-class count is showing
    a council of clones as a council."""
    path = _resolve_store(council_id, store_path)
    if phase not in ("open", "close"):
        raise ValueError(f"phase must be 'open' or 'close', got {phase!r}")
    norm = []
    for p in participants or ():
        _reject_unknown(p, _ALLOWED_PARTICIPANT_KEYS, "participant")
        actor = str(p.get("actor", ""))
        if not _ACTOR_RE.match(actor):
            raise ValueError(f"participant actor {actor!r} must be "
                             f"council.<vendor>.<model> (ADR-010)")
        outcome = str(p.get("outcome", "requested"))
        if outcome not in PARTICIPANT_OUTCOMES:
            raise ValueError(f"{actor}: outcome must be one of "
                             f"{PARTICIPANT_OUTCOMES!r}, got {outcome!r}")
        vendor = str(p.get("vendor", "") or actor.split(".")[1])
        norm.append({
            "actor": actor,
            "vendor": vendor,
            "model": str(p.get("model", "") or "unknown"),
            "independence_class": _norm_class(actor, vendor,
                                              p.get("independence_class")),
            "lane": str(p.get("lane", "") or "untrusted"),
            "outcome": outcome,
            "reason": p.get("reason"),
            "withheld": _norm_strs(p.get("withheld")),
        })
    norm.sort(key=lambda r: r["actor"])
    # Duplicate weights are detected over everyone SEATED (that is when the
    # clone was let in); the distinct-class count is over those who actually
    # RESPONDED, because an unavailable participant contributes no voice and a
    # class count that includes it overstates the independence on the record.
    seated_classes = [
        (p["independence_class"]["vendor"], p["independence_class"]["family"])
        for p in norm if p["outcome"] in ("seated", "responded", "refused")]
    heard_classes = [
        (p["independence_class"]["vendor"], p["independence_class"]["family"])
        for p in norm if p["outcome"] == "responded"]
    dup = sorted({f"{v}/{f}" for (v, f) in seated_classes
                  if seated_classes.count((v, f)) > 1})
    requested = len(norm)
    seated = sum(1 for p in norm if p["outcome"] in ("seated", "responded", "refused"))
    responded = sum(1 for p in norm if p["outcome"] == "responded")
    unavailable = sum(1 for p in norm if p["outcome"] == "unavailable")
    rec = {
        "record": "roster",
        "entry_version": ENTRY_VERSION,
        "council_id": council_id,
        "phase": phase,
        "round": None if round_no is None else int(round_no),
        "participants": norm,
        "requested": requested,
        "seated": seated,
        "responded": responded,
        "unavailable": unavailable,
        "distinct_classes": len(set(heard_classes)),
        "duplicate_classes": dup,
        # Availability is not correctness: a council that lost a voice says so.
        "degraded": responded < requested,
    }
    rule = _scan_roster(rec)
    if rule:
        rec = {
            "record": "roster",
            "entry_version": ENTRY_VERSION,
            "council_id": council_id,
            "phase": phase,
            "round": None if round_no is None else int(round_no),
            "participants": [],
            "requested": requested,
            "seated": seated,
            "responded": responded,
            "unavailable": unavailable,
            "distinct_classes": len(set(heard_classes)),
            "duplicate_classes": [],
            "degraded": True,
            "refused": rule,
        }
    return _chain_records([rec], Path(path), council_id, ts)[0]


# --------------------------------------------------------------------------- #
# reading                                                                      #
# --------------------------------------------------------------------------- #
def load_transcript(store_path: str | Path) -> list[dict]:
    """Read all records, skipping a torn tail line (never fatal). Missing is []."""
    store_path = Path(store_path)
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


def transcript_head(store_path: str | Path) -> tuple[int, str | None]:
    """``(record_count, head_entry_sha)`` -- the tail anchor, recomputed from the
    file. Compare against :func:`read_anchor` to catch a truncation."""
    records = load_transcript(store_path)
    return len(records), (records[-1].get("entry_sha") if records else None)


def read_anchor(store_path: str | Path) -> dict | None:
    ap = anchor_path(store_path)
    if not ap.exists():
        return None
    try:
        return json.loads(ap.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# tamper verification                                                          #
# --------------------------------------------------------------------------- #
def verify_chain(store_path: str | Path, *,
                 expected_count: int | None = None,
                 expected_head: str | None = None,
                 use_anchor: bool = True) -> tuple[bool, list[str]]:
    """Walk the chain; return ``(ok, failures)`` where every failure NAMES the
    1-indexed line and what mismatched. Never a bare False.

    Three independent checks per line:
      * ``body_sha`` recomputed over the canonical body -- catches a content edit;
      * ``entry_sha`` recomputed over ``(prev, stored body_sha, ts)`` -- catches a
        back-dated ts or a rewritten link where body_sha WAS updated;
      * ``prev`` equals the previous line's ``entry_sha`` -- catches a deleted or
        reordered line (the survivor points at a vanished predecessor).

    TAIL truncation is the one deletion a per-line walk cannot catch (a valid
    chain's prefix is a valid chain), so the persisted anchor is consulted by
    default and a shortfall in count or head is NAMED. Explicit
    ``expected_count`` / ``expected_head`` override it; ``use_anchor=False``
    verifies linkage only."""
    store_path = Path(store_path)
    if use_anchor and expected_count is None and expected_head is None:
        anchor = read_anchor(store_path)
        if anchor:
            expected_count = anchor.get("count")
            expected_head = anchor.get("head")
    failures: list[str] = []
    if not store_path.exists():
        if expected_count:
            failures.append(
                f"transcript missing but {expected_count} record(s) expected "
                f"(tail truncated to nothing or file deleted)")
        if expected_head:
            failures.append(
                f"transcript head absent, expected {expected_head} "
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
            # Cannot advance prev to a sha we do not have; leave it so the next
            # line also flags rather than silently re-syncing.
            continue
        n_records += 1
        stored_body = rec.get("body_sha")
        stored_entry = rec.get("entry_sha")
        if _body_sha(rec) != stored_body:
            failures.append(f"line {i}: body_sha mismatch (content tampered)")
        if _entry_sha(rec.get("prev"), stored_body or "",
                      rec.get("ts", "")) != stored_entry:
            failures.append(f"line {i}: entry_sha mismatch (ts/prev/link tampered)")
        if rec.get("prev") != prev_entry_sha:
            failures.append(
                f"line {i}: prev linkage broken "
                f"(expected {prev_entry_sha}, found {rec.get('prev')})")
        prev_entry_sha = stored_entry
    if expected_count is not None and n_records != expected_count:
        failures.append(
            f"transcript length {n_records} != expected {expected_count} "
            f"(tail truncated or records dropped)")
    if expected_head is not None and prev_entry_sha != expected_head:
        failures.append(
            f"transcript head {prev_entry_sha} != expected {expected_head} "
            f"(tail truncated or rewritten)")
    return (not failures), failures
