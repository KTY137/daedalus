# G1-RUNTIME-PROVIDER-01 - Claude contract strangler

## Frozen packet metadata

- Packet ID: G1-RUNTIME-PROVIDER-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: bacd9e6e69d58de6aebde4847e6afd6101b2ca72
- Dependencies: G1-HIER-01 at 72f7e326c70e4404504e9dd04075f0dd0c150cc3; G1-RUNTIME-02 at d30136e8e351e311fb9b72db7b3d1a3222b1c6e5; G1-WP-INDEX-01 at b2e74d601ab1af274cf670c58be53645c1001114
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The tracked Python import graph no longer places
`daedalus.claude_bridge` and `daedalus.providers.claude_cli` in one strongly
connected component. Neutral Claude workspace-binding and refusal contracts
have one owner in `daedalus.runtimes.contracts.claude`; the old provider module
reexports those exact objects while all registered Effect Registry and
authenticated executable-object locators remain byte-for-byte named as before.

## Scope

The frozen base has three direct AST edges between the two legacy modules:

| Source | Target | Locator | Baseline meaning |
|---|---|---|---|
| `claude_bridge` | `providers.claude_cli` | line 27 | type-only workspace contract import |
| `claude_bridge` | `providers.claude_cli` | line 456 | compatibility delegation in `ask_claude` |
| `providers.claude_cli` | `claude_bridge` | line 23 | unused private invoker import |

The first edge moves to the neutral contract owner and the unused reverse edge
is deleted. The remaining bridge-to-provider edge is intentional: the stable
`ask_claude` compatibility API delegates to the still-registered provider
door. This creates a directed hierarchy and removes the SCC without hiding a
runtime import.

In scope:

- `daedalus/runtimes/contracts/claude.py` as the canonical owner of
  `ClaudeWorkspaceGrant`, four refusal types, and Claude runtime/entrypoint
  identity constants;
- exact legacy reexports from `daedalus.providers.claude_cli`;
- removal of its unused private Bridge import and corresponding private-only
  test expectation;
- one reviewed shim-registry row, deterministic architecture/identity tests,
  and this Work Packet.

Forbidden paths include the Effect Registry, runtime profile configuration,
broker, executable-object registry, provider admission/receipt schemas,
historical evidence, Master Plan, amendment chain, UI, and generated assets.
No live Claude process, provider call, network request, Docker call, or
promotion is permitted.

## Contracts and behavior

### Canonical contract and compatibility

`daedalus.runtimes.contracts.claude` owns the concrete class objects. These
legacy imports remain exact aliases:

- `daedalus.providers.claude_cli.ClaudeWorkspaceGrant`;
- `ClaudeProviderAuthorizationRequired`;
- `ClaudeProviderWorkspaceMismatch`;
- `ClaudeProviderScopeMismatch`;
- `ClaudeInvocationBindingMismatch`.

The canonical `ClaudeWorkspaceGrant.__module__` becomes
`daedalus.runtimes.contracts.claude`. A protocol-0 historical pickle global
for `daedalus.providers.claude_cli.ClaudeWorkspaceGrant` still resolves to that
same object through the facade, and new pickle round trips retain exact type
and value. No tracked source names a persisted Claude contract pickle; this is
compatibility evidence, not a claim that arbitrary external pickles are safe.

The private provider-module name `_invoke_claude_payload` was neither exported
nor called. It is removed instead of replaced with `importlib`, `__getattr__`,
or another global locator. The supported monkeypatch seams remain
`daedalus.claude_bridge.ask_claude` and
`daedalus.claude_bridge.subprocess.run`; the executable-object registry keeps
its captured admitted function and remains immune to later Bridge rebinding.

### Registered doors and executable identities

These locators do not migrate in this packet:

| Contract | Frozen value |
|---|---|
| Effect entrypoint | `provider.claude` |
| Effect target and anchor | `daedalus.providers.claude_cli:ClaudeCLIProvider.run` |
| Runtime profile adapter | `daedalus.providers.claude_cli` |
| Sealed invoke target | `daedalus.claude_bridge:_invoke_claude_payload` |
| Output evidence target | `daedalus.providers.claude_cli:_output_digests` |
| Wiring | `INVENTORY_ONLY` |
| Registry SHA-256 | `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec` |

Moving the subprocess function would change its function module, source path,
source digest, compiled target code and authenticated pre-admission receipt.
Moving `ClaudeCLIProvider.run` or `_output_digests` would likewise change the
registered target or output-evidence locator. Those moves therefore require a
separate target-migration packet; presenting them as a harmless reexport here
would be false evidence.

The shim registry records `daedalus.providers.claude_cli` as a partial
registered effect door with exact contract reexports. `daedalus.claude_bridge`
is not called a pure facade: it still honestly owns the sealed subprocess
source and fail-closed CLI compatibility entrypoint.

### Static-analysis boundary

The read-only Code Ontology Companion preflight measured 1,393 supported
Python files, skipped three excluded-directory and 29 sensitive-name paths,
and reported partial Python adapter coverage. Direct imports are observed
syntax; dynamic imports, descriptor dispatch, generated code, monkeypatching,
runtime metaprogramming and runtime dispatch remain unsupported/runtime
unknown. No ontology workspace or snapshot was created, target code was not
executed by that analyzer, no direct network request was made, and optional
Ollama enrichment was not used.

## Acceptance matrix

| Claim | Deterministic check | Required result |
|---|---|---|
| SCC removed | tracked-only full-package AST graph and reachability | Bridge reaches provider; provider cannot reach Bridge |
| one contract authority | old/new object identity and `__module__` assertions | exact aliases; canonical module is runtime contract |
| pickle compatibility | historical GLOBAL locator plus current round trip | both resolve exact canonical type |
| no locator trick | AST audit for Bridge import, `import_module`, `__import__` | none in provider |
| registry stable | row fields, effects, anchor, wiring and digest | exact frozen values |
| executable targets stable | module/qualname/source-file assertions | old invoke/output locators unchanged |
| runtime string stable | profile JSON assertion | old adapter locator unchanged |
| broker behavior stable | Claude broker, bypass, ABI/object/source tests | pass without live provider calls |
| supported interpreters | focused suite and cold imports on Python 3.13/3.10 | pass |
| packet contract | official post-index artifact parser | primary metadata and six sections exact |

Baseline on the exact parent:

- Effect Registry digest was
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
- `ClaudeWorkspaceGrant.__module__` was
  `daedalus.providers.claude_cli`.
- the focused provider/object/source matrix produced 169 passes, eight skips,
  and one unrelated HIER-01 frozen-locator failure.
- the tracked AST graph confirmed mutual reachability through the three direct
  edges above.

## Migration and rollback

Migration is import-compatible: callers may adopt
`daedalus.runtimes.contracts.claude` immediately, while existing provider
imports receive the exact same objects. There is no JSON, SQLite, ledger, CAS,
digest, receipt, runtime-profile, Effect Registry, or in-place data migration.

Rollback restores the contract definitions and unused Bridge import to
`daedalus.providers.claude_cli`, removes the new contract module and shim row,
and returns the tests to the mutual-edge baseline. It does not rewrite any
receipt or historical artifact. Retirement of the provider facade is blocked
until a dedicated packet proves source, runtime-string, wheel, documentation,
effect-registry, executable-object/source-locator and pickle audits, then
migrates registered targets explicitly if the owner approves.

## Evidence expected failures and review

Expected green evidence:

- focused provider/broker/bypass and new architecture tests on Python 3.13;
- the same contract/architecture tests and a broker smoke on Python 3.10;
- cold imports in both orders and exact old/new identity checks;
- effect registry digest and full row contract unchanged;
- wheel build plus isolated outside-checkout import of old and new paths;
- `git diff --check` and a clean, packet-only committed worktree.

Measured builder evidence:

- Python 3.13 contract/broker/bypass focus: 78 passed;
- Python 3.13 provider/runtime/effect broad matrix: 778 passed, 10 skipped;
- Python 3.13 executable-object/source/effect supplement: 94 passed,
  eight skipped;
- Python 3.10 contract/broker/bypass focus: 78 passed;
- Python 3.13 and 3.10 cold imports: Bridge-first and provider-first passed;
- wheel/sdist build and isolated outside-checkout old/new import: passed;
- non-frozen HIER-01 architecture checks: six passed, one deselected;
- base/current AST bodies are identical for the sealed invoke
  (`4bdc3359...8e4b`), output evidence (`f77a1959...86ad`) and registered
  provider method (`49a93147...1563`);
- Registry digest: unchanged at the frozen value.

Known base-revision failures are retained separately:

- `tests/test_architecture_boundaries.py::test_frozen_repository_baseline_is_exact_and_green`
  reports 12 current relocated edges, zero allowlisted, and 23 resolved frozen
  locators after earlier hierarchy packets. This packet does not edit those
  kernel/spine imports or the HIER-01 baseline.
- `tools/index_work_packets.py --check` is already stale at the parent because
  the integrated Desktop packet postdates the last generated index. This
  packet validates its own document with the official parser and does not
  overwrite the parallel integration index.
- `tests/test_registry_new_doors.py` has three existing discovery failures for
  painted-on effects and vacuous Picker derivation. The exact same three
  failures and six passes were reproduced in a clean detached worktree at
  `bacd9e6e69d58de6aebde4847e6afd6101b2ca72`; none names Claude or a changed
  file in this packet.

Independent review should verify that no hidden reverse edge remains, the
deleted private alias had no tracked caller, no dynamic locator was introduced,
the old pickle global still imports, and the authenticated invoke/output
source locators were not disguised as migrated. Static correlation and change
proximity do not prove runtime causation; live Claude/runtime containment and
provider availability remain separate owner/release evidence.
