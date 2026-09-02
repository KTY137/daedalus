# daedalus/kernel/contracts/canonical.py  (2952 lines)

Base 54f09753. Static read-only.

## What the file is for

Defines the one wire language for every canonical Gate-0 kernel record:
`ContractProvenance`, `MissionContract`, `AttemptContract`, `EvidenceItem`/
`EvidencePacket`, `ExperimentSpec`/`CampaignContract`/`CampaignTrialReceipt`/
`CampaignReceipt`, `PolicyDecision`, `RuntimeManifest`, `AttemptReceipt`,
`NominationReceipt`/`PromotionReceipt`, `ConformanceCheck`/
`RuntimeConformanceReceipt`, plus the shared validators (`_identifier`,
`_repo_path`, `_sha256`, `_revision`, `_artifact_locator`, `_egress_endpoint`,
`_utc_timestamp`) and the canonical-JSON/digest plumbing (`_json_value`,
`_freeze_json`, `CanonicalContract.to_dict/to_json/digest`). It is a pure
schema/validation module: no subprocess, network, filesystem write, or
`os.environ` access anywhere in the file (verified, see Axis 2).

## Axis 1 — docstring truth

Method: AST-based extraction of every module/class/function docstring (not a
raw grep over code, which also matches enum-value strings like
`"not-applicable" | "authenticated"` inside validation bodies — those are
data, not claims). Script:
`runs/analysis/g1-kernel-audit/w1-scratch/extract_docstrings.py`. It found 13
docstring lines containing an Axis-1 keyword.

### CONFIRMED
- none. No docstring line makes a claim the code visibly fails to implement.

### PLAUSIBLE
- **`ContractProvenance` "shared by every canonical kernel contract"**
  (`canonical.py:272-273`). Mechanically true for the 12 `CanonicalContract`
  subclasses (`MissionContract`, `AttemptContract`, `EvidencePacket`,
  `ExperimentSpec`, `CampaignContract`, `CampaignReceipt`, `PolicyDecision`,
  `RuntimeManifest`, `AttemptReceipt`, `NominationReceipt`,
  `PromotionReceipt`, `RuntimeConformanceReceipt`) — an AST walk over every
  `ClassDef` whose bases include `CanonicalContract` confirms all 12 declare
  a `provenance: ContractProvenance` field (12/12, no exceptions). However
  `CampaignTrialReceipt` (`canonical.py:1825`, a plain `@dataclass`, not a
  `CanonicalContract` subclass) has **no** `provenance` field at all — it is
  embedded inside `CampaignReceipt.trials` and inherits only the parent
  receipt's provenance. It reads as a "canonical kernel contract" in every
  informal sense (typed record, own `campaign_id`, own digests/locators,
  validated `__post_init__`) without carrying the property the docstring
  says every one of them shares. Marked PLAUSIBLE, not CONFIRMED, because the
  literal noun phrase is "canonical kernel contract" and the codebase's own
  vocabulary (`CanonicalContract` the mixin) scopes that to the 12 subclasses,
  where the claim holds without exception.

### Checked and honest
- **`ResourceBudget` "Money is integer micro-USD, never a float."**
  (`canonical.py:364-365`). `__post_init__` (`canonical.py:372-381`) rejects
  any value where `isinstance(value, bool) or not isinstance(value, int)`,
  so a float `max_cost_microusd` raises `ValueError`. True.
- **`RuntimeCapabilities` "this never grants mission authorization."**
  (`canonical.py:618-619`). The class is eight booleans plus a type check
  (`canonical.py:630-633`); nothing in the file (or reachable from it) reads
  `RuntimeCapabilities` to authorize anything. Consistent with the module
  docstring's own claim that this file "deliberately does not... enforce
  effects."
- **`derive_work_item_id`/`work_item_identity_sha256` "producer and
  validator cannot drift" / "cannot drift into two different bodies"**
  (`canonical.py:725, 767`). Single source of truth: `derive_work_item_id`
  (`:750-764`) calls `work_item_identity_sha256` for the digest it truncates;
  there is exactly one function that computes the identity body.
- **`CampaignReceipt` "A nomination is never promotion authority."**
  (`canonical.py:2028-2029`). This file defines `NominationReceipt` and
  `PromotionReceipt` as distinct contracts; nothing reads a
  `NominationReceipt` as authorization for promotion. `PromotionReceipt`
  independently requires `owner_approval_ref` and
  `approval_assurance == "authenticated"` for `promotion_status == "approved"`
  (`canonical.py:2763-2774`).
- **`PromotionReceipt` "Claimed owner-controlled decision; it never applies
  the candidate." / "Even an approved receipt is only an authorization
  claim."** (`canonical.py:2697-2701`). The class has no method that writes,
  merges, or otherwise applies a candidate; it is a passive record. Grep
  confirms no filesystem/git mutation anywhere in the file (Axis 2).
- **`from_task_spec` "it may still run through the old harness, but it
  cannot masquerade as a bounded Gate-0 contract."** (`canonical.py:895,
  914-915`). Confirmed at `canonical.py:936-939`: a non-`read_only` legacy
  `TaskSpec` with empty `target_paths` raises `ValueError` before
  construction — the object is never produced. True.
- **`attempt_provenance` "Every digest this packet and its single evidence
  item reference has to appear in provenance.input_digests or construction
  fails closed."** (`canonical.py:1237, 1250-1251`). Verified: the
  `EvidencePacket.__post_init__` `required_inputs` list
  (`canonical.py:1220-1231`) collects exactly `attempt_contract_sha256`,
  `subject_sha256`, `policy_decision_sha256`, each item's `output_sha256`,
  and the candidate digest/locator when present, then calls
  `_require_provenance_inputs` (`:1232-1234`), which raises on any missing
  digest (`canonical.py:311-320`). `from_attempt_result`
  (`canonical.py:1344-1367`) always builds exactly one `EvidenceItem`
  (`items=(item,)` at `:1367`), matching "its single evidence item."
- **`__init__.py` "every legacy and new import resolves to one class
  object"** (see the `__init__.py` dossier — verified there, not repeated
  here since it is a different file's docstring).

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| none found | — | — | — |

Grep for `subprocess.`, `os.system`, `Popen`, `socket.`, `urllib.request`,
`requests.`, `httpx.`, `http.client`, `.bind(`, `.listen(`,
`open(..., "w"/"a"/"x"/"wb")`, `write_text`, `write_bytes`, `.mkdir(`,
`.touch(`, `os.replace/rename/remove/unlink`, `shutil.copy/move/rmtree`,
`sqlite3.connect`, `tempfile.`, `os.environ`, `os.getenv` over the file:
zero matches. The only filesystem-adjacent import is `pathlib.PurePosixPath`
(`:14`), used purely for string-shape validation in `_repo_path`
(`:124-136`) — never resolved, never opened.

### Notes
Consistent with the module docstring's claim that this is "a schema and
digest boundary, not an effect boundary" (`canonical.py:220-224`). No finding.

## Axis 3 — unreleased resources

No sqlite connections, file handles, `tempfile` objects, locks, sockets, or
subprocess handles are acquired anywhere in this file. No finding.

## Axis 4 — validator gaps (W4 class)

### Method
Mechanical AST walk of every `Call` node in the file matching the validator
functions (`_identifier`, `_repo_path`, `_sha256`, `_revision`,
`_artifact_locator`, `_egress_endpoint`, `_utc_timestamp`, `_non_empty`) or
`_sorted_strings(..., identifiers=True/paths=True/digests=True)`, recording
enclosing class, enclosing function, first argument, and line. Script:
`runs/analysis/g1-kernel-audit/w1-scratch/enumerate_validators.py`. Loop
bodies (`for name in (...): _identifier(getattr(self, name), name)`) were
expanded by hand-reading the loop's tuple literal to recover the real field
names (the AST only sees `getattr(self, name)` at the call site).

### Full enumeration: every field validated by `_identifier` (weak `_ID_RE`)

Direct `_identifier(...)` calls, 33 call sites total; excluding two
module-level helper-argument validations (`derive_work_item_id:764`,
`work_item_identity_sha256:783`, which validate a parameter, not a dataclass
field) and three dict-key-only validations (`ExperimentSpec.metric_acceptance`
key at `:1500`, `ExperimentSpec.frozen_components` key at `:1517`,
`CampaignContract.metric_acceptance` key at `:1724`,
`CampaignContract.frozen_components` key at `:1741`,
`CampaignTrialReceipt.metrics` key at `:1970` — five in total, all dict keys
never used to build a path, per the brief's own exclusion rule), the
remaining **dataclass fields** validated by `_identifier` are:

| # | class.field | line |
| - | --- | --- |
| 1 | `ContractProvenance.origin` | 282 |
| 2 | `ContractProvenance.trace_id` (optional) | 300 |
| 3 | `EffectScope.kill_switch_ref` | 594 |
| 4 | `MissionContract.mission_id` | 660 |
| 5 | `AttemptContract.attempt_id` | 824 (loop) |
| 6 | `AttemptContract.mission_id` | 824 (loop) |
| 7 | `AttemptContract.task_id` | 824 (loop) |
| 8 | `AttemptContract.campaign_id` (optional) | 827 |
| 9 | `EvidenceItem.evidence_id` | 992 |
| 10 | `EvidenceItem.evaluator` | 994 |
| 11 | `EvidencePacket.packet_id` | 1131 (loop) |
| 12 | `EvidencePacket.mission_id` | 1131 (loop) |
| 13 | `EvidencePacket.attempt_id` | 1131 (loop) |
| 14 | `ExperimentSpec.campaign_id` | 1426 |
| 15 | `ExperimentSpec.operator_axis` | 1474 |
| 16 | `ExperimentSpec.selection_policy` | 1484 |
| 17 | `CampaignContract.campaign_id` | 1638 |
| 18 | `CampaignContract.operator_axis` | 1672 |
| 19 | `CampaignContract.selection_policy` | 1707 |
| 20 | `CampaignTrialReceipt.campaign_id` | 1861 |
| 21 | `CampaignTrialReceipt.attempt_ids[*]` (each element) | 1911 |
| 22 | `CampaignReceipt.campaign_id` | 2059 |
| 23 | `PolicyDecision.decision_id` | 2293 (loop) |
| 24 | `PolicyDecision.subject_id` | 2293 (loop) |
| 25 | `RuntimeManifest.runtime_id` | 2352 (loop) |
| 26 | `RuntimeManifest.adapter_id` | 2352 (loop) |
| 27 | `AttemptReceipt.receipt_id` | 2487 (loop) |
| 28 | `AttemptReceipt.mission_id` | 2487 (loop) |
| 29 | `AttemptReceipt.attempt_id` | 2487 (loop) |
| 30 | `NominationReceipt.nomination_id` | 2644 (loop) |
| 31 | `NominationReceipt.mission_id` | 2644 (loop) |
| 32 | `NominationReceipt.attempt_id` | 2644 (loop) |
| 33 | `PromotionReceipt.promotion_id` | 2724 |
| 34 | `ConformanceCheck.name` | 2820 |
| 35 | `RuntimeConformanceReceipt.receipt_id` | 2862 |

Plus `_sorted_strings(..., identifiers=True)` (each element separately
weak-validated), 10 call sites → fields:

| # | class.field | line |
| - | --- | --- |
| 36 | `EffectScope.tools[*]` | 554 |
| 37 | `EffectScope.secret_refs[*]` | 559 |
| 38 | `MissionContract.work_item_ids[*]` | 672 |
| 39 | `AttemptContract.gate_names[*]` | 851 |
| 40 | `ExperimentSpec.metrics[*]` | 1469 |
| 41 | `CampaignContract.metrics[*]` | 1667 |
| 42 | `CampaignReceipt.metric_names[*]` | 2073 |
| 43 | `RuntimeManifest.declared_tools[*]` | 2368 |
| 44 | `RuntimeManifest.egress_transports[*]` | 2373 |
| 45 | `RuntimeManifest.workspace_modes[*]` | 2381 |

**Count: 35 distinct dataclass fields (some multi-occurrence across a
3-field loop counted once each) + 10 `_sorted_strings(identifiers=True)`
sequence fields = 45 total field-level weak-regex validations** across 12
`CanonicalContract` subclasses plus `EffectScope`/`ContractProvenance`.
(Script's raw call-site count is 33 `_identifier` + 10
`_sorted_strings(identifiers=True)` = 43; the +2 above is `attempt_ids[*]`
element-wise validation at `:1911`, which the AST script correctly attributed
to `_identifier` but is a per-element loop, not a single field — already
included in row 21 above, so the field-level total is **45** distinct named
targets, all sharing the same `_ID_RE` weakness.)

Fields that reach `_repo_path` instead (strict, rejects `..` and absolute/
drive-qualified paths): `AttemptContract.writable_paths` (`:846`, via
`_sorted_strings(..., paths=True)`) is the only path-typed field in the
whole file. Every field named `*_id`/`*_locator`/`*_sha256` uses
`_identifier`/`_artifact_locator`/`_sha256`, never `_repo_path`.

### Reachability: does any of these 45 fields reach path construction?

`canonical.py` itself never constructs a `Path`, calls `os.path.join`, or
opens a file (Axis 2/3, confirmed clean) — it is pure validation. The
question is which *downstream* consumer turns one of these weak-validated
`*_id` strings into a path segment.

#### CONFIRMED weak-validator/interpolation shape, traversal BLOCKED downstream (corrected 2026-09-02 after review from `kernel-audit`)

**Original text of this section claimed a CONFIRMED exploit chain reaching
`Path.joinpath` unguarded. That claim was wrong and has been corrected below
after independent re-verification — see the retraction note at the end of
this subsection for what changed and why.**

`AttemptContract.attempt_id` (`canonical.py:824`, validated only by
`_identifier` — proved live below) →
`daedalus/kernel/attempt_contracts.py:68`
(`_workspace_relative_path(attempt) -> f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}"`,
a raw f-string with **no** `_repo_path`/containment check applied to
`attempt_id` at this exact point) →
`daedalus/kernel/attempt_workspace.py:236-237`
(`relative = _workspace_relative_path(attempt)`;
`begin = self.ledger.begin(attempt, input_tree, ..., workspace_relative_path=relative, ...)`).

**The chain stops here, not at `joinpath`.** `AttemptLedger.begin`
(`daedalus/kernel/attempt_ledger.py:257-281`) constructs an
`AttemptStartRecord(..., workspace_relative_path=workspace_relative_path, ...)`
synchronously, and `AttemptStartRecord.__post_init__`
(`daedalus/kernel/attempt_contracts.py:135-137`) immediately re-validates
that exact string with the **strict** validator:
```python
relative = _repo_path(self.workspace_relative_path, "workspace_relative_path")
if relative == "." or not relative.startswith("attempts/"):
    raise ValueError("workspace_relative_path must be below attempts/")
```
`_repo_path` rejects any `..` part (proved live below), so a traversal-bearing
`attempt_id` makes `AttemptStartRecord(...)` construction raise inside
`begin()` at `attempt_workspace.py:237`. That call is **not** inside the
file's only `try` block (the `try` starts at `attempt_workspace.py:248`,
after `begin()` has already returned), so the `ValueError` propagates
uncaught out of `prepare()` — fail-closed, before `_workspace_relative_path`'s
one-and-only other consumer, the `joinpath` at `attempt_workspace.py:247`,
ever runs. `_workspace_relative_path` has exactly one call site (`:236`) and
`joinpath` has exactly one call site (`:247`) in this file (verified by grep
across `daedalus/kernel/*.py` and within the file); there is no alternate
path from `attempt_id` to a filesystem write that skips `begin()`.

Live proof, both halves (`.venv/Scripts/python.exe`, against `canonical.py`'s
own `_identifier`/`_repo_path`):
```
_identifier('x/../../../../tmp/evil', 'p') -> 'x/../../../../tmp/evil'   (ACCEPTED — weak validator at construction)
_repo_path('x/../../../../tmp/evil', 'p')  -> ValueError: must stay inside the declared workspace  (REJECTED — strict validator downstream)
```

**Verdict: CONFIRMED as a weak-validator/bad-interpolation *shape* — the
`_identifier`-validated `attempt_id` is genuinely interpolated into a raw
f-string with no local defensive check at `attempt_contracts.py:68` — but
NOT confirmed as an exploitable path-traversal chain, because
`AttemptStartRecord.__post_init__`'s `_repo_path` re-validation
(`attempt_contracts.py:135`) sits unconditionally between that interpolation
and the only `joinpath`/write path, and rejects the traversal before any
directory is created or any file is touched.** A fix aimed at
`attempt_workspace.py:247` (the join site) would be aimed at the wrong line;
the actual defect, if one is worth fixing at all, is that
`AttemptContract.attempt_id` accepts values that later constructions must
re-reject — a robustness/redundant-validation gap, not a live traversal.

**Retraction:** my first pass through this chain stopped at the data-flow
level (field → f-string → split → joinpath) and did not read
`AttemptLedger.begin`'s body or `AttemptStartRecord.__post_init__`, so it
missed the `_repo_path` gate sitting between `attempt_workspace.py:237` and
`:247`. Teammate `kernel-audit` traced the same chain further and caught
this; I independently re-read `attempt_contracts.py:100-154` and
`attempt_ledger.py:240-281` myself and confirm their correction exactly —
same line numbers, same control-flow reasoning, same live-tested primitive
(`_repo_path` rejects `..`). The `attempt_workspace.py` / `source_trees.py`
half of the chain past `:247` is unreachable for a `..`-bearing `attempt_id`
and I did not need to open `source_trees.py::materialize_tree` to establish
that — the block happens one call earlier, inside this file's own
`AttemptStartRecord`.

(The brief's framing that `_repo_path` is "the correct validator" is
accurate — confirmed twice above, once against a synthetic string and once
against the real `AttemptStartRecord.workspace_relative_path` gate. It is
`_identifier`/`_ID_RE` that is weak, not `_repo_path`.)

#### PLAUSIBLE / not traced further
The other 44 weak-validated fields (`mission_id`, `campaign_id`,
`task_id`, `packet_id`, `receipt_id`, `nomination_id`, `promotion_id`,
`decision_id`, `subject_id`, `runtime_id`, `adapter_id`, `evidence_id`,
`evaluator`, `kill_switch_ref`, and the nine `[*]`-validated sequences) were
swept (not exhaustively) for a `<field>}` f-string next to `Path`/
`joinpath`/`mkdir`/`open(` inside `daedalus/kernel`, `daedalus/runtimes`,
`daedalus/spine` — zero additional hits. That is a shallow, non-exhaustive
sweep (grep on the literal field name inside an f-string, scoped to three
directories); it is evidence of absence within that scope only, not proof
that no other consumer anywhere in the tree builds a path from one of these
fields. Flagged PLAUSIBLE-unconfirmed rather than asserted clean.

### New Axis-4 gap found in this file, not in the brief: `_repo_path`'s colon check is first-segment-only

`_repo_path` (`canonical.py:124-136`) rejects `..` parts and absolute paths
correctly, but its drive-letter guard only inspects the **first** path part:
`if path.parts and ":" in path.parts[0]:` (`:131`). A later segment
containing `:` passes untouched:
```
_repo_path('a/b:c/d', 'p') -> 'a/b:c/d'   (ACCEPTED, no ValueError)
```
`_ID_RE`/`_identifier` explicitly permits `:` anywhere (`_ID_RE` character
class includes `:`), so this is an intentional asymmetry between the two
validators for the same character, not just between them and path
construction. Impact is bounded on Windows (`:` inside a non-drive segment
makes `mkdir`/file creation fail with `WinError 3`, i.e. it refuses rather
than escapes — verified by `kernel-audit`, not independently re-run by me),
but `:` is a legal filename byte on POSIX, so a POSIX host materializing a
`_repo_path`-validated multi-segment value with an embedded `:` in a
non-first segment is not rejected by this validator. PLAUSIBLE (shape
confirmed here; whether any consumer actually passes an attacker-influenced
non-first-segment `:` through `_repo_path` was not traced — `writable_paths`
is the only field using it in this file, and I did not chase its downstream
consumers).

### Repo-wide duplication count: NOT 14

**Method:** `grep -rn` restricted to non-generated source directories
(`daedalus/`, `tools/`, `tests/`, `apps/`, `docs/`, `gates/`, `experiments/`,
`runs/`, `scripts/`), explicitly excluding the known stale full-copy
directories confirmed present in this tree
(`.claude/worktrees/agent-*/`, `.daedalus_worktrees/*/`, `build/lib/`,
`build/desktop-sidecar/dist/daedalus-web-api/_internal/`,
`apps/web/src-tauri/backend/_internal/`,
`apps/web/src-tauri/target/{debug,release}/backend/_internal/`) — a
teammate (`kernel-audit`) independently flagged the same trap before I
finished my own sweep; my grep already excluded these directories.

Exact literal match for `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$` (byte-identical
to `_ID_RE`) across the whole non-generated tree, canonical.py included:

```
daedalus/chip_design/cli.py:113
daedalus/gates/repository_write_classification.py:466
daedalus/gates/repository_write_effect_lease.py:68
daedalus/gates/repository_write_runtime_conformance.py:75
daedalus/ikarus_oneshot.py:32
daedalus/ikarus_runtime_events.py:26
daedalus/ikarus_runtime_role.py:35
daedalus/ikarus_tool_scope.py:30
daedalus/kernel/contracts/canonical.py:27   <- the original
daedalus/storage.py:39
```

**True count: 9 duplicate files (10 total occurrences including the
original), not 14.** Two more files share the same *vulnerability shape*
(admit `.` and `/` in the body character class with no `..`-segment check)
without being byte-identical: `daedalus/gates/fault_matrix_binding.py:50`
(`{0,255}`, no `:`) and `daedalus/gui_catalogue.py:236` (`{0,127}`, `_./-`
order). Including those, 11 files besides canonical.py (12 total) share the
defect *shape*; still not 14. Several other files matched a *looser* initial
grep (`council/bus.py`, `gates/baseline.py`, `spine/picker.py`,
`tools/vet.py`, `experiments/opus_fleet_watchdog/{core,session_probe}.py`,
`runs/council/room.py`, `interfaces/desktop/configuration.py`,
`wiki/links.py`) but their character classes **exclude `/`**, so they cannot
admit a multi-segment traversal string at all and are not part of this
defect family. I could not reconstruct a set of 14 from any grouping I
tried; report the discrepancy to whoever owns the "14" figure rather than
silently reconciling it.

**Separately, and arguably more important than the local-copy count:** the
weak `_identifier` function itself (not a copy of its regex, the actual
function object) is re-exported through `contracts/base.py`
(`base.py:10` — see that file's dossier) and imported by name into **34**
files outside `daedalus/kernel/contracts/` (listed in the `base.py`
dossier's Axis 5 section). Any of those 34 call sites that feeds an
`_identifier`-validated value into a path is an equally live instance of the
same defect family without duplicating a single character of regex — that
set is not covered by a "duplicate regex" count at all and was not traced
site-by-site here (out of my 5-file slice; flagged for whoever owns those
files).

### Other validators in this file: strict/lax asymmetry check

- `_SHA256_RE` (`:25`) / `_sha256()` (`:65-71`): single validator, no lax
  counterpart in this file.
- `_REVISION_RE` (`:26`) / `_revision()` (`:74-82`): single validator, no lax
  counterpart.
- `_ARTIFACT_LOCATOR_RE` (`:28`) / `_artifact_locator()` (`:85-91`): single
  validator; every caller I found routes through it, no bypass in this file.
- `_egress_endpoint()` (`:101-110`, uses `urlsplit`): rejects `*`, requires
  `http`/`https` scheme and a hostname, rejects embedded credentials. No
  second, lax URL validator exists in this file to diverge from it. (Note:
  this function is defined but I found no call site for it *inside*
  `canonical.py` itself — it validates a shape used by a consumer outside
  this file; not traced further, out of slice.)
- `_utc_timestamp()` (`:113-121`): single timestamp validator, 13 call
  sites, no lax counterpart.
- **Conclusion:** the `_identifier`/`_repo_path` pair is the only
  strict/lax asymmetry in this file for a value class that also gets used in
  path-like contexts. The `_repo_path` colon gap above is a second, smaller
  asymmetry within the "correct" validator itself.

### Canonical serialization: is it truly canonical? NaN/Infinity handling

`math` (`:10`) is used at exactly 4 sites, all `math.isfinite` checks, all
honest (reject rather than silently coerce):
- `_freeze_json` (`:176`) — the one function that freezes an arbitrary JSON
  blob (`EvidenceItem.details`, its only call site at `:1012`) rejects any
  non-finite float recursively.
- `ExperimentSpec.metric_acceptance` values (`:1503-1504`).
- `CampaignContract.metric_acceptance` values (`:1727`).
- `CampaignTrialReceipt.metrics` values (`:1973`).

These are the only three `int | float`-typed dict-value fields in the file
(confirmed by grepping every `int | float` type annotation); all three are
guarded. No `: float`-only field exists anywhere in the file. No gap found:
every float-bearing field in this file is checked for `isfinite` before it
can reach a digest.

Determinism of dict ordering: every `MappingProxyType(...)` construction in
the file (`:185, 1513, 1527, 1737, 1757, 1979, 2922`) sorts its keys first
(`dict(sorted(...))`) or is built from an already-sorted iteration — 7/7
sites checked. Independently, `CanonicalContract.to_dict()`
(`:229-242`) routes every field through `_json_value` (`:191-198`), which
sorts `Mapping` keys again (`sorted(value)` at `:193`) regardless of the
input's insertion order. `canonical_json`
(`daedalus/kernel/events/envelope.py:245-259`, re-exported through
`daedalus/spine/envelope.py` — a `sys.modules` alias shim, not a copy) also
passes `sort_keys=True` to `json.dumps`. Ordering is therefore
double-guarded (once in `canonical.py`, once in the shared JSON
serializer) — no finding.

One residual gap, outside this file: `json.dumps` in
`daedalus/kernel/events/envelope.py:255-256` does not pass
`allow_nan=False`, so if a non-finite float ever reached `canonical_json`
through a path that bypasses this file's `isfinite` guards (e.g. a
`CanonicalContract` subclass added later without routing a numeric field
through one of the three checked patterns above), `json.dumps` would
silently emit the non-standard tokens `NaN`/`Infinity` rather than raising.
Today, every reachable float-bearing field in `canonical.py` is guarded, so
this is PLAUSIBLE-latent, not a live gap in the current file.

## Axis 5 — dead / duplicate

- `_egress_endpoint` (`:101-110`) has no call site inside `canonical.py`.
  `grep -rn "_egress_endpoint" daedalus/` (excluding this file) → 0 hits in
  the non-generated tree. Zero callers confirmed by grep, count 0. No
  docstring promises a specific reader. This reads as either genuinely dead
  validation code or a function whose only consumer was deleted; flagged as
  a FINDING per the brief's rule ("zero callers is a finding, not a
  verdict"), not asserted dead.
- `KERNEL_CONTRACT_TYPES`/`parse_kernel_contract` (`:2922-2952`) are
  re-exported by `contracts/registry.py` (not in my slice) rather than
  duplicated — consistent with the `base.py`-style facade pattern used
  throughout `contracts/__init__.py`. Not a duplicate implementation.
- No duplicate regex, validator, or digest helper found *within* this file
  itself (single `_sha256`, single `_revision`, single `_identifier`, single
  `canonical_sha` import). The duplication is entirely cross-file (Axis 4
  above).

## OWNED-FLAG

Not applicable — this file is not listed among the owned/in-flight packets
in the brief (`offload_lease.py`, `attempt_execution.py` string-evidence
sites, `effects.py`).

## What I did not cover

- Did not open `daedalus/kernel/source_trees.py:621-679` or
  `daedalus/kernel/attempt_workspace.py` in full — only the two functions
  needed to confirm the `attempt_id` → path chain. The brief already treats
  that pair as a confirmed W4 finding from a prior sweep; I did not
  re-derive `materialize_tree`'s internal containment behavior myself.
- Did not trace the 34 downstream `_identifier` importers (listed in the
  `base.py` dossier) for path-construction reachability — that is a
  multi-file task outside this slice.
- Did not verify every one of the 45 enumerated weak-validated fields for a
  downstream path use beyond the shallow 3-directory f-string grep described
  above.
- Did not read `daedalus/kernel/contracts/registry.py`, `security.py`, or
  the other domain-facade files (`attempts.py`, `campaigns.py`, `evidence.py`,
  `missions.py`, `policy.py`, `promotion.py`, `resources.py`, `runtime.py`) —
  not in my assigned slice.
