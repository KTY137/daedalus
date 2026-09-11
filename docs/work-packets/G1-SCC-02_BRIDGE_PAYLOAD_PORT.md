# Work Packet: G1-SCC-02 Bridge payload port

Packet ID: `G1-SCC-02`
Artifact role: `primary`
Status: planned; BLOCKED on a scope decision found while starting it
Classification: `ALIGNED`
Active gate: Gate 1 - Renovation and owner-directed Genesis
Owner: `repository owner`
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 11
Master-plan SHA-256: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
Base revision: `032f2b05831ce9b969040e2fd44957237727325f`
Dependencies: `G1-SCC-RECON` (the measurement this packet acts on) — green

## Primary acceptance claim

`daedalus/file_bridge.py` no longer imports `daedalus.core`. The bridge takes
the payload processor as an injected port, and the 13-module cross-domain import
component dissolves. Both file-bridge effect doors still justify their four
declared effects through the port's annotation, and the exactly-once dispatch
behaviour is unchanged under the adversarial matrix below.

This packet changes the composition of one existing capability. It adds no
event store, no artifact identity, no promotion path, and no effect that the
registry does not already declare.

## Why this edge

Measured at `3eba2cb7` and written up in
`docs/architecture/scc-cut-reconnaissance-20260903.md`: one deferred import of
one function holds the whole component together.

```
daedalus/file_bridge.py:766:    from .core import process_bridge_payload
```

All 24 internal edges were simulated individually. Removing this one dissolves
the component; the next best cut leaves 7 members. Eight of the thirteen leave
cycles entirely, and the five that remain form two small single-domain cycles
that no longer cross the tree.

## The design, and the constraint that shapes it

Follow the house pattern that G1-SCC-CUT1 established for `OffloadPort`,
because it already solved the hard part.

1. **A Protocol, not a callable.** `daedalus/kernel/attempt_execution.py:253`
   explains why at length: the effect derivation in
   `tests/test_registry_new_doors.py` follows an injected port through its
   parameter ANNOTATION, expanding a repository-local Protocol to the classes
   that define its methods and continuing into those method bodies. A parameter
   annotated `Callable[..., Any]` yields nothing. Without the Protocol,
   `file_bridge.process` and `file_bridge.watch` lose their justification for
   `PROCESS_SPAWN`, `NETWORK_EGRESS` and `SPEND`, and the registry tests fail —
   correctly.

2. **The method name must be distinctive.** The Protocol expands to EVERY local
   class defining its whole method set, so a generic name widens the derived
   closure instead of resolving it. `process_bridge_payload` is already
   distinctive; keep it.

3. **The workload owns the capability class.** `offload_port()` returns the
   workload's own `OffloadCapability` rather than a forwarder, for two stated
   reasons that apply here unchanged: late binding survives, so
   `monkeypatch.setattr("daedalus.core.process_bridge_payload", ...)` still
   steers every caller through the port; and a forwarder defined in the supplier
   would be a SECOND implementation that widens two doors' effect set. So the
   capability class belongs in `daedalus/core.py`, calling the module-level
   function through its global name.

4. **Refuse at composition time.** `offload_runner` raises when the port is
   missing, before a worktree or a provider call exists. `process_request` must
   do the same: a caller that forgot the port learns before a request is
   claimed, not halfway through dispatch.

5. **No default import.** A default that lazily imports `core` reinstates the
   edge and makes the whole packet cosmetic. The absence of a default is the
   deliverable.

Ten modules can compose the port without reinstating the cycle, measured:
`core`, `desktop_runtime`, `doctor`, `health`, `interfaces.http.effects`,
`interfaces.http.web_api`, `kairos.orchestrate`, `orchestration.ikarus.shell`,
`progress_sources`, `status`. `core` is among them because `file_bridge -> core`
was `core`'s own way back in.

## Blocking finding, 2026-09-03: the entry point forces the edge

Found by starting the build, which is what step 2 of the chain is for.
The design above cuts the edge at `_process_request_claimed`, and that part
holds. It is not enough.

`daedalus/file_bridge.py:1068` defines `main()`, the `python -m
daedalus.file_bridge` entry, and it composes the CLI ports for `watch`,
`once`, `enqueue` and `mark-read`. Once `process_request` requires a payload
port, `main` is the module that must supply it -- so `file_bridge` imports
`core` again, in the composition instead of the dispatch, and the component
survives. Routing the supply through any intermediary does not help: `core`
reaches `file_bridge`, so `file_bridge -> X -> core` restores the cycle
transitively. The census walks every scope, so a lazy import inside `main`
or inside `if __name__ == "__main__":` counts exactly the same.

The edge is therefore cuttable only if `daedalus.file_bridge:main` stops
being a payload-dispatching entry in that module. That is a REGISTERED CLI
door (`cli.file_bridge`), so relocating it moves `registry_sha256` -- which
acceptance row 4 forbids -- and it changes a documented command that two
live documents and one test assert verbatim:

* `daedalus/interfaces/cli/enforce.py:48`
* `daedalus/interfaces/http/bootstrap_prompt.py:41`
* `tests/test_bridge_enqueue_guard.py`, which asserts the string appears in
  the message a user is shown when the watcher is not running.

### The decision this needs

**Option A -- relocate the door.** Move `main` to
`daedalus/interfaces/cli/bridge.py`, repoint the registry target and anchor,
re-pin `registry_sha256` in the 29 files that hold it, and change the
documented restart command to `python -m daedalus.interfaces.cli.bridge
watch`. Wins the cut. Costs a user-facing command that appears in an error
message people act on, and widens this packet from one edge to one door.

**Option B -- accept the component.** Leave the entry where it is and record
that the cross-domain cycle is held by a composition root that lives inside
it. `target-layout.md` section 3 already says a cycle among flat modules
that no protected layer touches is a smell, not a violation. Costs nothing
and wins nothing.

**Option C -- split the entry.** Keep `python -m daedalus.file_bridge` for
the subcommands that need no payload processor (`enqueue`, `status`,
`mark-read`) and move only `watch` and `once`. Two commands where there was
one, which is the parallel-path shape plan section 13 warns about.

Acceptance row 4 is written for the design as first specified. Whichever
option is taken, that row must be rewritten first, not quietly reinterpreted
when the digest moves.

## Scope

Allowed:

- `daedalus/file_bridge.py` — the port parameter on `process_request`, `watch`
  and `_process_request_claimed`, and the Protocol if it lives here;
- `daedalus/core.py` — the capability class only; no change to
  `process_bridge_payload`'s body or signature;
- the composing call sites: `daedalus/desktop_runtime.py:428` and the
  `python -m daedalus.file_bridge watch` path;
- `tests/` for the affected doors and the adversarial matrix;
- `tests/contracts/test_import_scc_hierarchy.py` census constants;
- this Work Packet and `docs/work-packets/index.json`.

Forbidden:

- the Master Plan, the amendment chain, `AGENTS.md`;
- the effect registry's declared effects, guard contracts, wiring or anchors —
  the `target` strings do not change either, so `registry_sha256` must NOT move;
- `process_bridge_payload`'s own behaviour;
- any second dispatch path, and any silent fallback when the port is absent.

## Contracts and behavior

CHANGED: the signatures of `file_bridge.process_request`, `file_bridge.watch`
and `_process_request_claimed` gain a required payload-processor port, and
`daedalus/core.py` gains a capability class exposing
`process_bridge_payload` through its module-level global name.

UNCHANGED, and each is an acceptance row below: the request key and journal
shape; the quarantine and archive paths; exactly-once dispatch; the four
declared effects of both file-bridge doors; every `target` string, guard
contract, wiring and anchor in the effect registry, so `registry_sha256`
must not move; and `process_bridge_payload`'s own behaviour.

REFUSED: a missing port. There is no default and no lazy fallback, because
a default that imports `core` reinstates the edge and makes the packet
cosmetic. The refusal happens before a request is claimed.

## Acceptance matrix

| # | Claim | How it is verified |
| --- | --- | --- |
| 1 | The import is gone | `grep` for `from .core import` in `file_bridge.py` returns nothing |
| 2 | The component dissolves | `nontrivial_components` over the census graph: no component contains both `daedalus.core` and `daedalus.file_bridge`; the two small cycles remain |
| 3 | Effects stay justified | `tests/test_registry_new_doors.py` green, with `file_bridge.process` and `file_bridge.watch` still deriving `PROCESS_SPAWN`, `NETWORK_EGRESS`, `SPEND` |
| 4 | The registry did not move | `registry_sha256()` equals its current pin in all 29 files |
| 5 | Composition-time refusal | a new test: calling `process_request` without the port raises before any journal write, quarantine move or archive write |
| 6 | Late binding survives | an existing monkeypatch of `daedalus.core.process_bridge_payload` still steers a request through the port |
| 7 | Exactly-once is unchanged | `tests/test_bridge_restart.py` and the claim/journal suites green |
| 8 | Census re-pinned | `CENSUS_EDGES` -1 and the component digest re-derived, with the delta attributed edge by edge |

## Adversarial verification (plan §10 step 6)

Proportional to the risk: this is a door on the request-handling path, so a
green unit suite proves the least. Required, each as an executed case:

- malformed request payload while the port is present;
- stale revision between claim and dispatch;
- cancellation mid-dispatch;
- timeout inside the injected processor;
- crash and restart between claim and journal write, with the same request key;
- a caller that supplies a port whose object does not satisfy the Protocol;
- a caller that supplies no port at all — must refuse, must not fall back.

## Migration and rollback

Rollback is restoring the deferred import and dropping the parameter; no
persisted format, journal shape, request key or registry row changes, so a
revert needs no data migration. That is the reason to prefer this edge over a
cut that moves a module.

## Expected failures

The census constants and the component digest WILL move and must be re-pinned
with the delta attributed. Any test that constructs `file_bridge.process_request`
positionally will need the port; that is a signature change and is expected to
surface as a collection error rather than a silent pass.

## Evidence, expected failures and review

EVIDENCE REQUIRED: gate g1 and gate g0 exit 0; the full suite with the
inherited failures named separately; the component measurement before and
after; `registry_sha256` unchanged; the seven adversarial cases above each
executed and reported by name.

EXPECTED FAILURES, so they are not mistaken for regressions: the census
constants and the component digest move and must be re-pinned with the
delta attributed edge by edge; any test constructing `process_request`
positionally fails at collection, which is the signature change surfacing
loudly rather than passing silently.

INDEPENDENT REVIEW: a reviewer who has not seen this document must answer
the four questions below from the diff alone.

## Review questions

1. Does the derivation reach `core.process_bridge_payload` through the
   annotation, or only appear to because some other path still imports core?
   Verify by removing that other path in a scratch copy and re-running the
   derivation.
2. Is the capability class in `core` the only local class defining
   `process_bridge_payload`? A second one widens both doors.
3. Does any caller reach `_process_request_claimed` without passing through
   `process_request` or `watch`?
4. Is there a path where the port is absent and the code proceeds anyway?

`Iron Plan: ALIGNED`
`Iron Gate: 1`
`Evidence: G1-SCC-RECON at 3eba2cb7 (all 24 internal edges simulated,
transitive reach-back for all 20 external callers); OffloadPort precedent at
daedalus/kernel/attempt_execution.py:253 and
daedalus/orchestration/execution/attempts.py:180.`
