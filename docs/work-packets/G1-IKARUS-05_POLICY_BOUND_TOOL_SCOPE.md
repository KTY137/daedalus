# G1-IKARUS-05 — Policy-Bound Per-Call Tool Scope

Status: bounded Gate-1 packet  
Tracks: #247  
Stacked dependency: G1-IKARUS-04 / PR #257  
Masterplan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, Revision 8

## Goal

Adapt the useful Hermes behavior of enabling and disabling toolsets per run without importing Hermes' mutable tool/plugin authority into Ikarus. The pinned Hermes source study records `run_agent.py` as providing enabled/disabled toolsets. Daedalus already has the canonical runtime declaration (`RuntimeManifest`) and policy/effect grant (`PolicyDecision.effect_scope.tools`), so Ikarus should project those authorities rather than create another registry.

## Contract

`daedalus/ikarus_tool_scope.py` is pure and non-authorizing. For one exact `OneShotRequest`, a tool is enabled only when all of the following are true:

1. the caller explicitly requests that exact tool identifier;
2. the exact runtime-evidence binding belongs to the request and exact `RuntimeManifest`;
3. that manifest declares the tool and provider-neutral tool events;
4. the canonical `PolicyDecision` is an `allow` decision bound to the exact request digest;
5. the policy effect scope grants the exact tool; and
6. the caller has not explicitly disabled that requested tool.

The immutable projection binds the request, runtime-evidence, runtime-manifest and policy-decision digests. Empty requested scope remains empty even when runtime and policy expose more tools.

## Deliberate strengthening over the upstream behavior

This packet deliberately refuses ambient/default activation and broad aliases. There is no fallback to a user config, plugin discovery, MCP discovery, process-global Ikarus registry, late-wins override or `all`/`*` wildcard. Disablement can only narrow an explicitly requested set. A runtime capability declaration is never treated as permission.

G1-IKARUS-04 is adjusted accordingly: a tool-capable runtime manifest may now be bound as runtime evidence, but `OneShotRequest.tool_scope` remains structurally empty. Capability evidence and effect authorization stay separate.

## Non-goals / authority boundary

This packet does not execute a tool, call a provider, start an effect, resolve a plugin, read ambient configuration, modify the canonical effect registry, mint policy, issue a lease, or make a source-only runtime executable. `daedalus.runtimes.broker` and the canonical effect lifecycle remain mandatory for future live execution.

The projection itself is evidence/data, not an authorization token. A future broker-bound adapter must verify and consume the exact canonical runtime/effect authority rather than trusting a caller-authored projection object.

## Adversarial coverage

Focused tests cover:

- explicit enable + explicit disable with deterministic digest binding;
- deny-by-default when requested scope is empty;
- runtime-undeclared and policy-ungranted tools;
- wildcard/all-tool refusal;
- disablement outside the requested set;
- deny-policy refusal;
- policy-subject substitution;
- runtime-evidence/manifest substitution;
- duplicate tool requests;
- absence of provider/effect/plugin-discovery authority in the projection module;
- preservation of the stateless one-shot request's empty built-in tool scope while tool-capable runtime evidence is accepted.

Requested exact-head checks:

```bash
python -m py_compile \
  daedalus/ikarus_oneshot.py \
  daedalus/ikarus_tool_scope.py \
  tests/test_ikarus_oneshot.py \
  tests/test_ikarus_tool_scope.py
python -m json.tool docs/research/hermes-agent-v2026.8.19-provenance.json
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p no:cacheprovider \
  tests/test_ikarus_oneshot.py \
  tests/test_ikarus_tool_scope.py \
  tests/test_ikarus_runtime_role.py \
  tests/kernel/test_runtime_conformance_harness.py \
  tests/runtimes/test_runtime_conformance_profiles.py
```

## Completion boundary

This closes only the interface-side enabled/disabled tool-scope projection item after exact-head evidence and integration of its dependency. It does not close live-provider statelessness, live runtime activation, effect execution, cancellation propagation, attempt receipt binding, or whole-product Hermes parity.

Automatic merge/promotion: disabled.  
OwnerApproval: none.  
Gate transition: none.
