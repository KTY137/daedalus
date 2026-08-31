# G1-RUNTIME-PROVIDER-05 - Packaged provider persona catalogue

## Frozen packet metadata

- Packet ID: G1-RUNTIME-PROVIDER-05
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 1db7425cfde63cd0263d61ba40df4430232e16f7
- Dependencies: G1-PKG-01, G1-RUNTIME-PROVIDER-04
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.runtimes.providers.personas` owns provider persona lookup and loads
the built-in catalogue from `daedalus.resources`. Source checkouts and
installed wheels therefore resolve the same packaged default. The historical
`daedalus.providers.personas` module remains an exact reexport facade.

## Scope

Only persona catalogue ownership, imports, and Python package data move. The
provider names, role mappings, culture strings, roster ordering, selection
policy, admission, subprocess/network behavior, registered Effect targets,
stores, and persistent formats remain unchanged.

## Contracts and behavior

- `persona_for`, `culture`, `roster`, and the cached registry keep their
  signatures, return values, ordering, and object identity through the facade.
- The packaged JSON is authoritative. When a checkout mirror also exists it
  must be byte-identical; divergence fails closed with `ResourceDriftError`.
- The legacy JSON remains a temporary fallback only when package data is
  unavailable. A wheel needs no repository-relative provider data.
- Kairos routing and concrete provider doors import the runtime owner, while
  all registered provider class/method targets remain in their old modules.
- The shim register owns the compatibility facade and records its retirement
  criteria; the Effect Registry is not changed.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Source/wheel parity | resource and isolated-wheel smokes | identical persona values without checkout files |
| Legacy compatibility | identity and value contracts | exact callable/cache identity and stable ordering |
| Divergence refusal | mismatched mirror contract | `ResourceDriftError` before use |
| Thin facade | AST contract | no function/class implementation |
| Directed imports | architecture and provider suites | runtime owner used; zero new forbidden edges |
| Registry integrity | frozen digest contract | exact semantic digest |

## Migration and rollback

There is no persistent migration. Rollback restores the lookup implementation
and imports under `daedalus.providers.personas`, removes the packaged JSON and
package-data entry, and removes the shim record. No ledger, receipt, database,
CAS locator, evidence path, historical run, provider authorization, or
registered Effect target changes.

## Evidence, expected failures, and review

- Python 3.13: 180 focused persona-resource, packaged-resource, provider,
  scheduler, hardening, and architecture tests passed.
- Python 3.10: the same 180 focused tests passed.
- `uv build` succeeded; the resulting wheel installed outside the checkout
  and resolved the packaged catalogue with the legacy path absent.
- Changed modules compile, cold imports succeed on Python 3.13 and 3.10, and
  `git diff --check` is clean.
- The Effect Registry semantic digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

Review must reject a second editable persona authority, silent fallback to a
divergent checkout file, or movement of a registered provider Effect target.
The global Work-Packet index remains deferred to central integration because
of the inherited G1-HERMES-01 section defect. This packet does not edit the
Master Plan, amendment chain, historical `runs/`, generated web distribution,
Registry targets, or promotion state.
