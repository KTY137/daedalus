# G1-RUNTIME-PROVIDER-03 - Directed provider helper owners

## Frozen packet metadata

- Packet ID: G1-RUNTIME-PROVIDER-03
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: af50ca183c24c02ff067539e95a11507c7ce7537
- Dependencies: G1-HIER-02B, G1-RUNTIME-PROVIDER-02
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Provider report parsing/coercion, provider spend admission, provider
execution-limit shaping, and token/prompt policy have directed implementation
owners under `daedalus.runtimes.providers`. The old `_report` and root
`token_policy` paths preserve the established objects as registered temporary
compatibility seams instead of retaining parallel implementations.

## Scope

This packet moves only pure/shared provider helpers. The legacy `_report`
module deliberately retains context-file reading and graph-brief rendering
until sensitivity and graph access have injected runtime ports. Concrete
provider classes, registered Effect targets, HTTP calls, subprocess calls,
admission, egress, receipts, stores, and report fields are unchanged.

## Contracts and behavior

- Old helper imports resolve to the exact runtime-owned function and class
  objects. Signatures, defaults, exception types/text, retry iterators, timeout
  semantics, JSON rescue, report coercion, spend refusal envelopes, token
  constants, prompt text, path deduplication, and trimming remain unchanged.
- `daedalus.token_policy` contains no function or class implementation. Direct
  provider call sites use the runtime owner; the legacy path remains loadable.
- `daedalus.providers._report` now defines only `read_provider_context` and
  `render_provider_brief`; every moved helper is an exact reexport.
- Runtime helper owners import only standard library, kernel policy/contracts,
  and sibling runtime modules. They do not import providers, lanes, Kairos,
  gates, orchestration, interfaces, or chip design.
- Both compatibility seams are recorded with source, runtime-string, wheel,
  documentation, monkeypatch, and pickle retirement criteria.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Exact old/new objects | helper identity contract | every moved function is identical |
| No duplicate owner | facade AST contracts | two context functions only; token facade has none |
| Report wire behavior | provider report and agent-env suites | identical results/errors |
| Spend behavior | budget/provider suites | reserve before call; valid blocked report on refusal |
| Limit behavior | bounded/unbounded provider tests | unchanged iterators and real `None` timeout |
| Directed imports | runtime-owner AST census | no outer-layer imports |
| Architecture/Registry | frozen checks | zero forbidden edges; 18 shims; exact digest |

## Migration and rollback

No persistent format or data moves. Rollback restores helper bodies in
`providers._report` and `token_policy`, points direct call sites back to those
modules, and removes the four runtime owners and two shim entries. Existing
reports, reservations, ledgers, receipts, CAS objects, evidence, and historical
runs remain readable and at their original paths.

## Evidence, expected failures, and review

- Python 3.13: 312 focused helper, agent-environment, provider, budget,
  hardening, rollback, and architecture tests passed.
- Python 3.10: the same 312 focused tests passed.
- A broader Python 3.13 concrete Ollama, DeepSeek, Codex, Claude, and provider
  hierarchy matrix passed 170 tests and 12 subtests.
- Changed modules compile; cold imports prove exact legacy/owner identities;
  `git diff --check` is clean.
- The Effect Registry semantic digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

Review must keep the two remaining context functions visible debt: moving them
without injected sensitivity and graph ports would create a runtime dependency
on outer product layers. The generated Work-Packet index is refreshed only
after parallel integration; its inherited G1-HERMES-01 section defect remains
separate. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry targets, or promotion
state.
