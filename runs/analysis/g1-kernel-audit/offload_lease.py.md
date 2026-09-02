# daedalus/kernel/offload_lease.py  (3390 lines)

Base 54f09753. Static read-only. **OWNED by the running "chip-refusal"
write-packet** — per the shared brief, this dossier is a STRUCTURAL MAP plus
one-line flagged observations, not a full per-axis case. Findings here may
already be stale by the time they are read.

## What the file is for

The Effect-Lease **issuer**: mints, persists, and later reconciles the one
`python.offload` Effect Lease per wave (plus a stricter `cli.daedalus_chip`
issuance path), so `daedalus/offload.py` never has to trust ambient
configuration for its own authorization. It owns the lease ledger location,
the local HMAC-style issuer key file, the kill-switch-generation binding
that invalidates every lease issued under a since-changed kill-switch
permit, and a set of "write-evidence" record/replay functions that let the
Gate-0 repository-write chain reconstruct what a terminalised lease
authorized and executed.

## Structural map (top-level classes/functions, `:line`)

Ports/protocols (`:115-237`): `RepositoryHeadRevisionReceiptPort`,
`RepositoryHeadRevisionVerifierPort`, `WorktreeRootResolverPort`,
`IntentLedgerPathResolverPort`, `EgressAdmissionObservation`,
`EgressAdmissionPort`, `LaneEndpointResolverPort`,
`ChipExecutionPlanBinding`, `ChipExecutionPlanValidatorPort`,
`ChipPublicationGraphVerifierPort`, `ChipTerminalArtifactRetainerPort`,
`ChipPublicationRecorderPort` — all `Protocol`/dataclass injection points,
no effects themselves.

ID/derivation helpers: `chip_eda_lease_id` (`:262`), `_issuer_origin`
(`:380`), `_issuer_policy_version` (`:395`), `_issuer_request_id` (`:401`).

Kill-switch binding: `WaveLeaseKillSwitchEngaged(LoopHalted)` (`:416`),
`kill_switch_generation` (`:1477`).

Time helpers: `_utc_now` (`:430`), `_timestamp` (`:434`) — format only, no
parse-back (`fromisoformat` does not appear in this file).

Paths/roots: `control_root` (`:441`), `lease_ledger_path` (`:455`),
`write_evidence_root` (`:593`).

Digest/record helpers: `write_root_identity_sha256` (`:520`),
`guard_decision_sha256` (`:579`), `_record_sha256` (`:611`),
`_stable_regular_bytes` (`:616`), `_publish_exact_bytes_once` (`:634`),
`_strict_canonical_record` (`:643`).

Write-evidence record/replay functions (the "retained facts" layer,
`:669-1407`): `_chip_publication_index_path` (`:669`),
`load_chip_eda_publication` (`:686`), `_publish_evidence_record` (`:748`),
`record_primary_checkout_disjointness` (`:768`),
`record_effect_lease_subject` (`:837`),
`record_effect_lease_subject_parts` (`:863`),
`rebuild_effect_lease_authorization` (`:945`),
`record_effect_lease_execution` (`:1005`),
`emit_effect_lease_terminal_record` (`:1064`),
`_verify_chip_eda_terminal_bookkeeping` (`:1142`),
`_retain_chip_eda_terminal_artifact` (`:1192`),
`verify_chip_eda_publication_graph` (`:1229`),
`_record_chip_eda_publication` (`:1275`),
`harvest_effect_lease_terminal_records` (`:1341`).

Issuer key material: `issuer_keyring` (`:1408`), `read_issuer_keyring`
(`:1460`).

Write-policy/containment: `WritePolicySource` (`:1515`),
`resolve_write_policy` (`:1574`), `wave_containment_roots` (`:1661`),
`derive_wave_containment` (`:1696`), `lane_endpoint` (`:1793`),
`_limit_policy_evidence` (`:1809`), `_limit_policy_from_evidence` (`:1819`).

Lease result types: `WaveLeaseDenied` (`:1839`), `WaveOffloadLease`
(`:1896`, with `.granted`, `.lease_id`, `.requested_effects`,
`.execution_for`, `.issued_execution`, `.retain_terminal_record`,
`.retain_terminal_records`, `.receipt`).

Intent-ledger guard: `_intent_ledger_decision` (`:2149`) — the sqlite
read-only check, see Axis 3 note below.

Issuance predicate and core: `issuable_row` (`:2248`, replaces the old
"one constant row" refusal with a 5-conjunct predicate over
`ISSUER_CONTRACTS`/`ISSUER_EFFECTS`/`EFFECT_BOUNDS`), `_deny` (`:2329`),
`_acquire_effect_lease_impl` (`:2379`, the ~640-line core — largest single
function in the file).

Public entrypoints: `acquire_effect_lease` (`:3021`),
`acquire_wave_offload_lease` (`:3052`, the wave's pinned door — refuses an
`entrypoint_id` kwarg by construction per module docstring `:16-18`),
`acquire_attempt_lease` (`:3083`), `acquire_chip_eda_lease` (`:3114`).

## OWNED-FLAG observations

- **OWNED-FLAG** — `_secret_bytes`/`_signature`/`_parse_utc` duplication
  question: this file is **neither** a fourth copy of `effects.py:223-253`'s
  helpers **nor** an importer of them. It defines its own, differently-scoped
  key-material loader (`issuer_keyring`/`read_issuer_keyring`, `:1408-1474`,
  a local 32-byte file under `control_root`, O_EXCL/O_BINARY-guarded create-
  on-first-use) and its own `_utc_now`/`_timestamp` (`:430-439`) which only
  *formats* timestamps — the file never calls `fromisoformat` anywhere, so
  it has no `_parse_utc`-equivalent at all, divergent or otherwise.
- **OWNED-FLAG** — `replay.pending_reconciliation` consumption at `:1106`
  and `:1184` (as another worker already established) still stands
  structurally: those lines sit inside `emit_effect_lease_terminal_record`
  (`:1064-1141`), which is the file's terminal-record replay path.
- **OWNED-FLAG** — registry coverage: `issuable_row`/`_acquire_effect_lease_impl`
  mint leases *for* the `python.offload` (`effect_boundary.py:418-443`) and
  `cli.daedalus_chip` (`effect_boundary.py:183-218`) rows, but those two
  rows' `GuardAnchor`s point at the *downstream* entrypoints
  (`daedalus.offload:offload`'s `begin_effect`, and
  `daedalus.chip_design.cli:main`'s `run_admitted_eda`) — not at
  `acquire_effect_lease`/`acquire_wave_offload_lease` themselves. The
  lease-issuance side effects that live in *this* file — the issuer key
  file write (`:1408-1457`), the lease-ledger sqlite writes (delegated to
  `EffectLeaseLedger` from `effects.py`), and every write-evidence record
  function listed above (`:669-1407`) — have no `GuardAnchor` of their own
  anywhere in `daedalus/spine/effect_boundary.py` (checked: no occurrence of
  `offload_lease` as a `GuardAnchor` target string in that file). None of
  the 4 `daedalus.kernel.*`-targeted rows (`:350,:372,:394,:2304`) cover
  this file either — they target `attempt_ledger`/`attempt_workspace`/
  `approvals`, not `offload_lease`. This is the file's instance of "an
  effectful kernel site with no covering row"; not deep-audited per the
  ownership rule.
- **OWNED-FLAG** — Axis 3 spot check (breadth only): the file's few direct
  resource acquisitions look properly guarded, in contrast to the sqlite
  leak pattern already fixed elsewhere — `sqlite3.connect` at `:2204` is
  wrapped `with contextlib.closing(sqlite3.connect(...)) as conn:` (closes
  on every exit path, read-only `mode=ro` URI, `timeout=5`); the one
  `os.open` at `:1440` is released via `try:` / `finally: os.close(fd)`
  (`:1448-1451`); the one `path.open("rb")` at `:619` is a `with` block. No
  counter-example found in this pass — not exhaustively verified given the
  ownership constraint (only ~15% of the file's ~640-line core function was
  read line-by-line).
- **OWNED-FLAG** — Axis 4 spot check: caller-facing identifiers that reach
  paths go through hashing first, not raw concatenation — e.g.
  `_chip_publication_index_path` (`:669-683`) builds its filename from
  `canonical_sha({...})`, a digest of a dict that includes `execution_id`,
  rather than from `execution_id` directly; `source_revision` is checked
  against a strict `^[0-9a-f]{40}$` (`_REVISION`, `:515`) before use. No
  weak-`_identifier`-into-path chain found in the ~20% of the file sampled
  for this axis — not exhaustive.
- **OWNED-FLAG** — no `subprocess`/network effect sites found at all in this
  file (scoped grep for `subprocess.|Popen|socket.|urllib.|requests.|httpx.|
  http.client|.bind(|.listen(`: zero matches). If the brief's premise that
  "offload plausibly spawns processes and egresses" refers to this file
  specifically, that was not observed here — the process-spawn/egress
  effects live in `daedalus/offload.py` and `daedalus/chip_design/*`
  (downstream of the lease this file issues), not in the issuer itself.

## What I did not cover

Full per-line reads of `_acquire_effect_lease_impl` (`:2379-3020`, ~640
lines, the single largest function in the kernel package) and
`resolve_write_policy`/`derive_wave_containment` (`:1574-1792`) — the
OWNED-FLAG rule caps this at a structural map plus targeted spot checks
rather than a full axis-by-axis case; a deep audit would need to re-run
after the chip-refusal packet lands.
