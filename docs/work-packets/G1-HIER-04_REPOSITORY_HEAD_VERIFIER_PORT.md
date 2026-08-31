# G1-HIER-04 — Repository-head verifier port

## Classification and frozen authority

- Classification: `ALIGNED`
- Active gate: Gate 1 — Safe Capability Expansion
- Master Plan: Revision 11
- Master Plan SHA-256:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Exact parent revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
- Branch: `packet/g1-hier-04-repo-port`
- Promotion, merge, live provider and EDA execution: not requested

This is a narrow G1-HIER-04 strangler slice. It removes the production import
edge from `daedalus.kernel.offload_lease` to
`daedalus.gates.repository_head_revision` without moving or duplicating the
repository-head verifier. The Gate remains the only implementation owner and
`daedalus.chip_design.cli` is the production composition root.

## Contract

`acquire_chip_eda_lease` requires an explicit
`RepositoryHeadRevisionVerifierPort`. There is no default and the kernel does
not discover a verifier through an import, registry, environment variable or
filesystem lookup. The production CLI injects the existing Gate verifier.

Before the first lease write, the kernel requires the returned receipt port to
bind both its object fields and retained wire fields to the requested
`source_revision`, retain `repository_head_verified=true`, and serialize as
canonical JSON. The retained wire contract must have the exact existing fields,
schema and negative authority claims. A missing, non-callable, malformed or
differently bound port therefore cannot reach `_acquire_effect_lease_impl`;
without a lease the existing CLI cannot reach `run_admitted_eda`.

For a valid Gate receipt, the existing authority-head evidence body is
unchanged: the same receipt dictionary is nested under
`repository_head_receipt`, the lease request receives the same resolved
revision, and the existing canonical record digest construction is retained.

## In-scope files

- `daedalus/kernel/offload_lease.py`
- `daedalus/chip_design/cli.py`
- `tests/kernel/test_chip_eda_effect_boundary.py`
- `tests/kernel/test_chip_repository_head_port_review.py`
- this Work Packet

The effect registry, Gate verifier, receipt schema, ledger/database formats,
CAS locators, evidence paths and EDA executor are out of scope.

## Acceptance evidence

The focused checks must prove:

1. no Python module under `daedalus.kernel` imports `daedalus.gates`;
2. the verifier is a required keyword-only port with no default;
3. production composition injects
   `verify_repository_head_revision` from the Gate;
4. verification and receipt binding occur before the lease issuer, and lease
   acquisition occurs before `run_admitted_eda`;
5. missing and unbound ports are refused before lease issuance;
6. a real Gate receipt retains the exact authority-head receipt, lease source
   revision, evidence fields and canonical record digest;
7. the effect-registry source bytes remain unchanged.

## Frozen-parent infrastructure blocker

At the exact parent, the focused behavioral suites fail during collection
because `daedalus/kernel/__init__.py` imports the absent module
`daedalus.kernel.campaigns`. This predates the packet and is not repaired here:

```text
ModuleNotFoundError: No module named 'daedalus.kernel.campaigns'
```

The import-free architecture review test remains independently executable.
Behavioral tests are retained for execution after the parent package is made
internally complete; the collection failure is not represented as passing
evidence.

## Local verification on 2026-08-31

- `py -3.13 -m pytest -q
  tests/kernel/test_chip_repository_head_port_review.py`: `3 passed`.
- Focused `compileall` for both production files and both focused test files:
  passed.
- The two behavioral suites, executed diagnostically with only the absent
  campaign exports stubbed in memory, report `49 passed`. This exercises the
  real Gate verifier, exact authority-head evidence record, lease binding and
  CLI ordering, but is not a substitute for the parent-native run.
- The parent-native invocation of those behavioral suites remains blocked at
  collection by the missing campaign module described above.

## Registry invariance

The parent SHA-256 of `daedalus/spine/effect_boundary.py` is
`fb060b3e32949a1911e920ae91aa0c883410ca5a36074db9c338f5a64de7f165`.
This packet does not edit that file. Registry ID, target, effects, wiring,
anchors and digest therefore remain outside the change surface.
