# daedalus/kernel/contracts/base.py  (23 lines)

Base 54f09753. Static read-only.

## What the file is for

A one-block re-export: imports `KERNEL_CONTRACT_VERSION`, `CanonicalContract`,
`ContractProvenance`, and all eleven private validator/serialization helpers
(`_artifact_locator`, `_egress_endpoint`, `_freeze_json`, `_identifier`,
`_json_value`, `_locator_sha256`, `_non_empty`, `_record_payload`,
`_repo_path`, `_require_provenance_inputs`, `_revision`, `_sha256`,
`_sorted_strings`, `_utc_timestamp`) straight from `.canonical`, and
re-exposes them. `__all__` only names the three public symbols; the
underscore-prefixed validators are importable from this module but not
advertised by `__all__` — the docstring calls this "Base wire language and
validators," which is accurate to what the module actually hands out (the
validators, not just the three public names).

## Axis 1 — docstring truth

Grep for the target words over the one-line module docstring: 0 hits. No
claims to check.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| none | — | — | — |

Pure import statement, no effect surface.

## Axis 3 — unreleased resources

None.

## Axis 4 — validator gaps (W4 class)

This file constructs no paths itself. Its Axis-4 relevance is structural:
**it is the single choke point through which the weak `_identifier`
function (not a copy of its regex — the actual function object, so any
future fix to `_ID_RE`/`_identifier` in `canonical.py` propagates here
automatically) reaches every consumer outside the `contracts/` package.**

### Method
`grep -rl "_identifier" --include="*.py" daedalus` intersected with
`grep -l "from daedalus.kernel.contracts.base import"` (or the relative
`from ..kernel.contracts.base import` / `from .kernel.contracts.base import`
spellings), restricted to files outside `daedalus/kernel/contracts/`.

### Full enumeration: files that import `_identifier` via this re-export

34 files (all outside `daedalus/kernel/contracts/`):

```
daedalus/kernel/approvals.py
daedalus/kernel/attempt_contracts.py
daedalus/kernel/effects.py                          (OWNED-FLAG, see below)
daedalus/kernel/effect_recovery.py
daedalus/kernel/effect_replay.py
daedalus/kernel/promotion.py
daedalus/kernel/promotion_execution.py
daedalus/kernel/runtime_effects.py
daedalus/kernel/source_trees.py
daedalus/runtimes/fault_matrix.py
daedalus/runtimes/fixture_fault_collector.py
daedalus/runtimes/host_fault_runner.py
daedalus/runtimes/live_fault_collector.py
daedalus/runtimes/profiles.py
daedalus/runtimes/provider_executable_object_registry.py
daedalus/runtimes/provider_executable_pre_admission.py
daedalus/runtimes/provider_executable_structure.py
daedalus/runtimes/provider_executable_targets.py
daedalus/runtimes/provider_invocation.py
daedalus/runtimes/provider_invocation_abi.py
daedalus/runtimes/provider_invocation_authority.py
daedalus/runtimes/provider_invocation_identity.py
daedalus/runtimes/provider_invocation_payload.py
daedalus/runtimes/provider_invocation_registry.py
daedalus/runtimes/provider_invocation_resolution.py
daedalus/runtimes/provider_observation.py
daedalus/runtimes/provider_observation_store.py
daedalus/runtimes/provider_observation_store_contract.py
daedalus/runtimes/provider_runtime_executable_binding.py
daedalus/runtimes/provider_target_receipt_retention_contract.py
daedalus/runtimes/provider_target_verification.py
daedalus/runtimes/provider_target_verification_contracts.py
daedalus/runtimes/trust_store.py
daedalus/spine/receipts.py
daedalus/twin/contracts.py
daedalus/twin/reference_compiler.py
daedalus/twin/_reference_claims.py
```

Note `daedalus/kernel/source_trees.py` and `daedalus/kernel/attempt_contracts.py`
are both in this list — `attempt_contracts.py` is the file that interpolates
`AttemptContract.attempt_id` (weak-validated at `canonical.py:824`) into an
unguarded f-string at `attempt_contracts.py:68`, reached via this re-export
rather than a local copy of `_identifier`'s regex. **Correction (2026-09-02,
after review from `kernel-audit`, independently re-verified):** this
particular chain is NOT an exploitable path-traversal — a downstream
`AttemptStartRecord.__post_init__` re-validates the same string with the
strict `_repo_path` at `attempt_contracts.py:135` before any filesystem
write, and rejects `..`. See the `canonical.py` dossier's Axis 4 section
for the corrected trace and the retraction note; my first pass here
overstated it as CONFIRMED-exploitable. The structural point about exposure
still stands independent of that one example: these 34 re-export importers
share the identical `_identifier` function without duplicating a single
character of regex, and are invisible to a regex-text grep, so the brief's
"14 files duplicate the weak regex" framing still under-counts the real
surface — just not via this specific attempt_id example, which turned out
to be guarded.

For context, a broader (not fully verified) `contracts.base` import count:
53 files import *something* from `contracts.base` (mostly `ContractProvenance`,
`_sha256`, `_revision`); 34 of those specifically pull `_identifier` by name.
`daedalus/kernel/contracts.canonical` itself is imported directly by only 5
files (`daedalus/schemas.py` plus 4 test files) — confirming `base.py`, not
`canonical.py`, is the dominant real-world import surface for these
validators, consistent with the package docstring's "strangler split"
framing in `__init__.py`.

### What I did not verify for these 34
Whether each site's `_identifier`-validated value subsequently reaches path
construction. That is a 34-file reachability trace outside a 5-file slice;
flagging the enumerated set as the artifact for whoever owns those files,
per the brief's request that this be "the enumeration artifact other
workers will use."

## Axis 5 — dead / duplicate

- Not dead: `git`-independent grep shows 53 real importers of
  `daedalus.kernel.contracts.base` across `daedalus/kernel`, `daedalus/runtimes`,
  `daedalus/spine`, `daedalus/twin`, plus 4 test files
  (`tests/contracts/test_import_scc_hierarchy.py`,
  `tests/contracts/test_spine_outer_ports.py`,
  `tests/kernel/test_contract_hierarchy.py`,
  `tests/kernel/test_fourfold_evidence_outer_ports.py`). This is the
  opposite of dead code: it is the single busiest import surface among the
  five files in my slice.
- Not a duplicate: it re-exports the same function/class objects from
  `.canonical` (`from .canonical import (...)` — identity-preserving import,
  not a re-implementation). No divergent copy of `_identifier`, `_sha256`,
  `_repo_path`, etc. exists in this file.
- `tests/contracts/test_import_scc_hierarchy.py:67,110` (comments, read
  during the grep sweep, not opened in full) describe "Twenty-eight of the
  33 [importers] take only ``daedalus.kernel.contracts.base``" — a test
  already tracks this file's fan-in, consistent with what I found
  independently. I did not open that test file's assertions to confirm the
  28/33 figure matches my 34-file `_identifier`-specific count (the test's
  33 is presumably "all contracts.base importers in some scoped set," not
  specifically "_identifier importers," so the two numbers are not expected
  to match one-for-one).

## OWNED-FLAG

The brief lists `daedalus/kernel/effects.py` as "just received a fix" and
`daedalus/kernel/attempt_execution.py`'s string-evidence sites and
`daedalus/kernel/offload_lease.py` as owned by the "chip-refusal" packet.
`daedalus/kernel/effects.py` appears in my `_identifier`-importer list above
— noted, not deep-audited. `attempt_execution.py` and `offload_lease.py` do
not import from `contracts.base` in a way that showed up in my
`_identifier`-specific grep (they import `ContractProvenance` only, per the
Axis-4 import list in the `canonical.py` dossier), so no additional
OWNED-FLAG needed for those two beyond what the brief already states.

## What I did not cover

- Did not trace any of the 34 `_identifier` re-export importers for
  downstream path construction, except `attempt_contracts.py` (covered via
  the `canonical.py` dossier's Axis 4 trace — corrected 2026-09-02 to
  CONFIRMED-shape-but-blocked-downstream, not an exploitable chain).
- Did not open `security.py`'s import of `.canonical` directly (bypassing
  `base.py`) in more depth than the one docstring spot check noted in the
  `__init__.py` dossier.
