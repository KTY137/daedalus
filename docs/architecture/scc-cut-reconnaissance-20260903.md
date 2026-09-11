# The cross-domain cycle is held together by one deferred import

Status: reconnaissance, not a change
Active gate: 1
Measured: 2026-09-03 at `3eba2cb7`
Classification: `ALIGNED` — read-only measurement. No `daedalus/` source file was
modified by this packet.

## What this overturns

`docs/architecture/target-layout.md` §3 and commit `e80407e0` record a finding
that has blocked three packets:

> modules outside the cycle that reach INTO it — 20
> of those, ones the cycle does NOT import back — 0
>
> Every candidate composer … is itself reachable from inside. So injecting a
> port and composing it ANYWHERE reinstates the cycle through the composer.

That was true when it was measured. It is not true now. Between then and this
revision, 48 modules were relocated into `foundation`, `interfaces/cli`,
`interfaces/http`, `orchestration`, `orchestration/ikarus`, `runtimes/provider`
and `gates/repository`, and seven re-export facades were deleted. The graph the
finding described no longer exists.

Re-measured at `3eba2cb7`, using the same graph the census test builds
(`tests/contracts/test_import_scc_hierarchy.py::_tracked_module_graph`):

| | then | now |
| --- | --- | --- |
| modules outside the component that reach into it | 20 | 20 |
| of those, ones the component does NOT reach back | **0** | **20** |

The component reaches 180 of 434 modules transitively, and none of its twenty
callers is among them.

## The finding

One edge holds the whole component together, and it is a single deferred import
of a single function:

```
daedalus/file_bridge.py:766:    from .core import process_bridge_payload
```

Removing that one edge from the measured graph:

| | before | after |
| --- | --- | --- |
| cross-domain component | 13 members | **dissolved** |
| non-trivial components in the tree | 12 | 13 |
| largest component | 14 (`runtimes/provider`, package-internal) | 14, unchanged |

Eight of the thirteen leave cycles entirely: `build`, `build_exec`, `core`,
`doctor`, `file_bridge`, `health`, `orchestration.ikarus.supervisor`, `status`.
Five remain, in two small SINGLE-DOMAIN cycles that no longer cross the tree:

* `{kairos.gated_writes, kairos.scheduler, offload}` — the write wave and its
  workload, which the G1-SCC-CUT1 note already identified as a genuine
  workload-level cycle;
* `{progress, progress_sources}` — a pair.

Every other single-edge cut was simulated for comparison. The next best is
`doctor -> file_bridge` at 13 → 7 with two composers; `file_bridge -> core` is
13 → dissolved with ten.

## Why the port is already half-built

`daedalus/interfaces/bridge/dispatch.py:695` already calls
`ports.process_bridge_payload(...)`. The strangler split that produced
`interfaces/bridge/` made the payload processor an injected port; only its
SUPPLY is a direct import. `file_bridge._process_request_claimed` imports the
function from `core` for the sole purpose of putting it into
`ClaimedDispatchPorts`.

Ten modules can hand it down without reinstating the cycle, measured:

    core, desktop_runtime, doctor, health, interfaces.http.effects,
    interfaces.http.web_api, kairos.orchestrate, orchestration.ikarus.shell,
    progress_sources, status

`core` is among them because `file_bridge -> core` was `core`'s own way back in.

## What this does NOT claim

It does not claim the cut is safe, only that it is available and cheap in graph
terms. `daedalus.file_bridge:process_request` is a REGISTERED EFFECT TARGET with
a `begin_effect` guard anchor, and `_FILE_BRIDGE_FUNCTIONS` in the effect
registry names `enqueue`, `process_request` and `watch`. Threading a required
port through them changes the signature of a door on the request-handling path.

Under plan §10 that is a Work Packet with the full chain, and specifically with
the step-6 adversarial matrix: malformed request, stale revision, cancellation,
timeout, crash/restart mid-claim, policy bypass. A cut that dissolves a
thirteen-module cycle by changing an effect door is exactly the shape where a
green unit suite proves the least.

It also does not claim the remaining two small cycles are acceptable. It claims
they are single-domain, which is the distinction target-layout.md §3 already
draws: "a cycle among flat modules that no protected layer touches is a smell,
not a violation."

## Reproducing

```
python - <<'PY'
import sys; sys.path.insert(0, "tests/contracts")
import test_import_scc_hierarchy as t
from daedalus.structcore.cycles import nontrivial_components
g = {k: set(v) for k, v in t._tracked_module_graph().items()}
print("before:", max(len(c) for c in nontrivial_components(g)))
g["daedalus.file_bridge"].discard("daedalus.core")
print("after: ", max(len(c) for c in nontrivial_components(g)))
PY
```

Both numbers read 14 — the provider family — because the cross-domain component
was never the largest. That is the point: it was the one that crossed domains,
and it is the one that goes.

`Iron Plan: ALIGNED`
`Iron Gate: 1`
`Evidence: _tracked_module_graph at 3eba2cb7; all 24 internal edges of the
component simulated individually; transitive reach-back computed for all 20
external callers; component membership before and after enumerated.`
