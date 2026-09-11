# Ikarus runtime replay: selective delivery

Classification: ALIGNED. Gate 1 remains active. No constitutional amendment.
Base: b6903c0ba00b737612faee85afaffbfa4833920e on the existing
`g1/ikarus-runtime-invocation-binding-07d3` line.

## Claim and scope

The existing RuntimeEventProjection validates rows against callback history,
detaches caller-owned lists, rejects empty plans and decodes the existing /1
wire shape with exact field, type and digest checks. RuntimeEventProjector
replays events and binds recovery to the externally declared complete plan.
Replay performs no I/O, tool execution, automatic retry, approval or promotion.

Changed source: `daedalus/ikarus_runtime_events.py`.
Tests: `tests/test_ikarus_runtime_events.py`.
No policy, evaluator, ledger, scheduler, provider permissions or archive changes.

## Measured verification

The preceding delivery supplied these exact candidate Git blobs:
- source: `8ae9c9b8569fb33299b543675addf2311ba2a7be`
- tests: `9f7a91427ba00e4072345f0062df992805e061ae`

Re-executed in this continuation on 2026-09-11: **103 passed**.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONHASHSEED=0 python -m pytest -q -p no:cacheprovider tests/test_ikarus_runtime_events.py
```

This was an isolated Linux copy of the source and tests, not a full checkout,
package initialization, repository conftest, system CI or live provider run.
Direct Git clone in the work container failed with DNS resolution failure;
GitHub read/write operations use the connected GitHub tool. No synthetic live
success or complete system readiness is claimed.

## Retained boundaries

A self-consistent forged history can carry a recomputed unkeyed digest. The
caller must still verify canonical Mission/Attempt/revision and trusted CAS
observations. Callback success is not independent task verification. Running
entries after replay require reconciliation, not blind effect repetition.
The APIs are not yet integrated into a real provider recovery path.

`main` at 217d5edc2b5e59441051b9cb0df60a5fbca93fe2 carries the same baseline
module at `daedalus/orchestration/ikarus/runtime_events.py`. Selective migration
must translate that path and the test import; do not merge the diverged branch
wholesale, restore old top-level modules on main, or overwrite the newer master
plan. No new remote branch, force push, automatic merge or archive mutation.

Review, full-checkout/platform tests and main integration remain open. Rollback
is a selective revert of this packet, not a branch reset. There is no migration
and the valid /1 output shape is unchanged.
