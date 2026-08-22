# ADR-011: The Event Spine

## Status

Proposed

## Context

The repository carries four durable stores with no ordering relation between
them:

1. **Operational journal** — `daedalus/memory/__init__.py`, append-only JSONL at
   `memory/events.local.jsonl`. Records carry `time`, `kind`, `task_id`, free
   text, and a `payload` blob. They carry no identifier: the vector forwarder
   has to synthesize one as `f"{time}_{kind}"`. Appends are a plain `open("a")`
   with no lock and no chain.
2. **Memory ledger** — `daedalus/memstore.py`, the `dmem/1` hash-chained JSONL
   at `memory/ledger.local.jsonl`. Every line carries `body_sha` over a
   canonical body and `entry_sha = sha256(prev, body_sha, ts)`; `verify_ledger`
   walks the chain and names the offending line; `ledger_head` supplies the tail
   anchor that catches truncation the walk cannot see. A secret floor runs
   before any write.
3. **Vector projections** — `daedalus/memory/embeddings.py`, SQLite. Its own
   docstring states that the append-only journal remains authoritative and that
   vectors without a recorded model identity stay quarantined.
4. **Intent ledger** — `daedalus/spine/ledger.py`, SQLite in WAL mode, landing
   now to carry the self-improvement loop (pick task → build candidate in a
   worktree → run gates → present a patch for human promotion → mint an eval
   task → re-measure).

The journal and the memory ledger do not import each other. Nothing assigns a
sequence that spans stores, so a receipt that must join an intent to its
artifacts — worktree branch, patch, gate outcome, minted eval task — has no
defined join key and no defined order. `docs/bypasses.md` gap 3 records the
related tension: JSONL operational records are append-only by convention only,
while the memory ledger is genuinely tamper-evident. ADR-010 forbids any
successor event or receipt module from defining actor identity before the
`daedalus.<name>` / `crew.<name>` rule is honored. This ADR is the
precondition that rule demanded.

## Decision

### 1. The spine is `daedalus/spine/ledger.py`

The SQLite WAL intent ledger is the **ordering authority**. It allocates the
only global sequence in the system: an opaque `intent_id` and a monotonic `seq`
per recorded transition. No other store defines order across stores.

The rationale is capability, not seniority:

- **The memory ledger cannot sequence.** `_finalize_and_write(..., dedup=True)`
  makes an append whose `body_sha` already exists a no-op that returns the
  pre-existing id, and ids are `body_sha[:16]` — content digests, with `ts`,
  `prev`, `entry_sha`, and `id` deliberately excluded from the body hash so the
  same logical body dedupes wherever it lands. Two genuinely distinct intents
  with identical bodies would collapse into one record. That property is correct
  for memory and disqualifying for a sequencer.
- **The memory ledger has no mutable state.** Trust is derived by `fold_state`
  over the whole chain. An intent's lifecycle (proposed → built → gated →
  presented → promoted/rejected) is mutable and read far more often than it is
  written; folding the chain per read is O(n), and `_APPEND_CACHE` already
  exists to dodge that same cost on the write side.
- **The journal cannot be joined to.** Its records have no identifier, so
  nothing can point at one; its appends are unserialized, so two concurrent
  writers can interleave; and it is already declared convention-only in
  bypasses gap 3.
- **The projection store disqualifies itself** in its own module docstring and
  must not be promoted.
- **SQLite WAL supplies exactly the missing properties**: an atomic transaction
  around "allocate sequence and record the transition", crash-safe recovery for
  the resume path, and one writer with concurrent readers — which matches the
  harness shape of one loop driver against many readers (CLI, status, web_api).

### 2. What the other three become

- **`memstore.py` (dmem/1) — attestation sidecar.** Not a projection: it is
  independently written and independently verifiable, and it is the only store
  that survives being disbelieved. It holds `landed_edit`, `gate_outcome`, and
  `receipt_ref` attestations, and keeps its secret floor as the write-time gate.
  It is never rebuilt from the spine.
- **`memory/embeddings.py` — projection.** Derived, rebuildable, discardable. It
  may help *find* a record; it may never be *cited* as one.
- **`memory/__init__.py` journal — independent operational domain, not
  load-bearing.** It stays convention-only append-only and keeps its TODO
  snapshot and human-readable trace. Nothing in the loop may gate on it, and no
  receipt may cite it. This is what makes bypasses gap 3 tolerable rather than
  fixed: the weak store is no longer on a trust path.

### 2b. Attestation role fulfilled

The attestation sidecar role described in section 2 — holding `landed_edit`,
`gate_outcome`, and `receipt_ref` attestations — is now filled by the spine
itself: conversation turns became spine intents (commit 83e41fcc, 2026-08-22).
The separation between mutable order (spine) and tamper-evident proof (ledger)
remains; the attestation mechanism is now unified at the spine's write boundary.

### 3. Tamper-evidence: where it is and where it is not

- The **memory ledger carries tamper-evidence** — per-line `body_sha`,
  `entry_sha`, `prev` linkage, plus the `expected_count` / `expected_head`
  anchor for tail truncation.
- The **spine does not.** SQLite WAL gives durability and atomicity, not
  tamper-evidence: any process with write access can `UPDATE` a row and no
  digest breaks. This is the accepted cost of choosing it for ordering.
- The mitigation is asymmetric and mandatory: **every spine transition a human
  decision depends on — gate outcome, promotion, rejection — must also be
  attested into the memory ledger with `intent_id` and `seq` inside the hashed
  body.** Those fields are content, not position, so they fall inside
  `body_sha`. A spine row edited after the fact then contradicts a chained
  attestation, and the contradiction is detectable. The spine is the order of
  record; the ledger is the proof of record.
- The journal and the projection store carry no tamper-evidence and are not to
  be given any.

### 4. How a receipt joins an intent to its artifacts

- The spine allocates `intent_id` at the intent's first row. It is opaque and
  unique — never content-derived, so two identical proposals stay two intents.
- Every durable record written elsewhere while acting on an intent carries that
  `intent_id`. No envelope changes are needed: the memory ledger already accepts
  `provenance.task_id` (in `_ALLOWED_PROV_KEYS`, already secret-floored) and the
  journal already accepts `MemoryEvent.task_id`.
- The reverse pointer is written once, at receipt time. The spine's receipt row
  records the memory-ledger `id` **and** `entry_sha` of the attestation, next to
  the artifact identities the loop already produces: the worktree branch from
  `GitWorktreeManager.create_worktree`, the base commit, the disk-truth
  `wrote` set that `offload()` computes from its before/after snapshot, the
  `verify` result, and the eval task id from `mint_task_from_landed_edit`.
- That makes the join **verifiable rather than correlational**: given a spine
  receipt, an auditor re-walks the ledger to the named `entry_sha` and confirms
  it hashes. A dangling or non-hashing reference is a failed receipt, not a
  missing one.
- A projection hit is never a join. A vector result must be resolved back to a
  spine `intent_id` or a ledger `id` before it may appear in a receipt — the
  same rule `_try_vector_index` already states for paths: semantic similarity
  alone must never invent evidence.

### 5. Actor namespace enforcement (ADR-010)

Actor identity is defined **once, at the spine's write boundary**. The spine
requires an `actor` field matching `^(daedalus|crew)\.[a-z0-9_-]+$` on every
intent and every transition, and **refuses** a bare name at insert — it does not
normalize one, because a guessed namespace is exactly the ambiguity ADR-010
outlawed. The same validator runs in the spine's attestation helper, so the
`provenance.agent` of every ledger entry the loop writes is namespaced too.

`memstore.append_entry` itself is **not** changed to enforce this. It accepts
arbitrary provenance strings today and has callers that predate the spine;
tightening it would fail those callers without making any existing record more
trustworthy. The consequence is deliberate and stated plainly: a ledger entry
written outside the spine's helper may carry a bare actor, and such an entry is
not citable in a receipt. The journal is unenforced and is not citable at all.

## Consequences

Cross-store joins are now defined, and the four stores have distinct jobs:
spine orders, ledger proves, projections search, journal narrates. Receipts
become reconstructible from spine plus ledger alone.

The cost is a real one and is not hidden by this decision: the ordering
authority is the store with the weakest integrity properties. Anyone with write
access to the SQLite file can rewrite history there, and only the attestation
duty in §3 makes that rewrite detectable. If the attestation step is skipped for
a transition, that transition has no proof — the ADR is then not being followed,
and the gap is silent unless a verifier looks for missing attestations.

Writing this ADR does not create an event spine, an ordering guarantee, or a
namespace check. `daedalus/spine/ledger.py` must implement the sequence
allocation, the actor refusal, and the attestation helper before any of this is
true; ADR-010's rule remains unhonored in code until then. Nothing here upgrades
ADR-004's worktree prototype into an execution transaction or ADR-007's named
components into a root of trust.

## Revisit triggers

This decision is wrong, and must be reopened, if any of the following becomes
true:

1. **A second concurrent writer.** SQLite WAL is single-writer. If lock
   contention shows up in measurement rather than in speculation — a networked
   UI, a second daemon — the ordering authority moves.
2. **A remote auditor.** The moment a spine row must be believed by a party that
   does not trust the local host, ordering must move into a chained store: give
   the spine its own entry chain, or promote the memory ledger to spine by
   giving it non-content ids and an O(1) state index.
3. **The ledger gains sequencing.** If `memstore` acquires
   non-content-derived ids and an indexed mutable state, the two-store split is
   redundant and should collapse to one store.
4. **A receipt that spine plus ledger cannot reconstruct.** If some fact turns
   out to live only in the journal, that is a defect in this ADR, not in the
   journal: the fact must be moved into the spine, not the journal promoted.
5. **A fifth durable store.** This ADR forbids one. Any new durable state must
   be a projection of the spine or a chained attestation in the ledger; a fifth
   authoritative log reopens the problem this ADR exists to close.
