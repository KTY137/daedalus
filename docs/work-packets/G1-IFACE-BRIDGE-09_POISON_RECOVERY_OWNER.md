# G1-IFACE-BRIDGE-09 - Poison recovery owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-09
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 526e867b3a2091826adc915de46e3ab391dc959b
- Dependencies: G1-HIER-01, G1-HIER-06E, G1-IFACE-BRIDGE-01 through
  G1-IFACE-BRIDGE-08
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.bridge.watcher` owns settling classification and the
complete poison-recovery decision. `daedalus.file_bridge` remains the stable
watch/effect facade and injects the current quarantine, projection, locator,
output, and exception seams on every call.

## Scope

- `looks_unfinished` receives the settle grace and clock; it reads only the
  supplied request stat and owns no queue or persistence authority.
- `PoisonHandlingPorts` receives the inbox, settling predicate, existing
  quarantine transaction, quarantine locator, request key, canonical exception
  types, and output function.
- The watcher owner still imports no Daedalus facade, Effect Registry,
  provider, subprocess, network, database, or store implementation.

## Contracts and behavior

- Existing tests and callers that patch `_looks_unfinished`,
  `quarantine_request`, `_quarantine_dir`, `_request_key`, paths, or exception
  classes observe the same current facade objects.
- Only fresh JSON/Unicode decode failures stay in place as `SETTLING`; structural
  request defects are poison immediately.
- The exact `< 5s` boundary is preserved: age 4.9s settles and age 5.0s does
  not.
- Successful quarantine, projection pending, permanent projection failure,
  move pending, and terminal-report preservation return the same report paths
  and emit the same status labels.
- Any failure inside last-resort recovery remains contained and returns `None`;
  it cannot terminate the watch loop.
- No provider retry, report, sidecar, journal, archive, conversation event,
  JSON field, path, effect, Registry target, or persistent format changes.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Settle boundary | injected-clock owner test | strict age `< grace` |
| Single owner | facade AST contract | one delegation for each recovery helper |
| Recovery containment | restart/poison suite | no exception escapes last-resort recovery |
| No second spend | restart and dispatch suites | poison path never redispatches provider work |
| Directed owner | watcher import contract | no reverse facade/effect authority |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

There is no persistent migration. Rollback restores the settling and recovery
bodies inside `file_bridge.py`; all existing retained artifacts stay in place.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry target, provider
admission, or promotion state.

## Evidence, expected failures and review

- Python 3.13: 301 focused bridge, poison, quarantine, conversation, crash,
  Effect, envelope, hardening, and HTTP-loop tests passed; 16 subtests passed.
- Python 3.10: the same 301 tests and 16 subtests passed.
- Changed modules compile and `git diff --check` reports no whitespace defect.
- G1-HIER-06E's zero forbidden-edge architecture contract is unchanged.
- The semantic Effect Registry digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
