# G1-MUT-01 - Declarative mutation runner

## Frozen packet metadata

- Packet ID: G1-MUT-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: c2dd8d132ae7299020be4bd090d90f892256d791
- Dependencies: G1-HIER-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`tools.mutation_score` is the single executable mutation authority for the
first migrated runner family. Strict, repository-confined JSON specs own the
target, exact anchors, test selections, expected failing test, rule and
timeout. The former repository-tree runner remains at its old path as a thin
caller-compatible wrapper. It no longer rewrites production source itself.

This packet proves the runner/spec/wrapper shape on one representative runner;
it does not claim that all historical runners have already been converted.
Later packets may add specs and replace old scripts only after their callers
and retained negative evidence have been audited.

## Scope

This packet establishes the declarative mutation runner pattern: a JSON spec
owns the target paths, source anchors, test selections, and timeout; the
`tools.mutation_score` module executes the score deterministically in an
isolated snapshot; and the legacy shell script at its original path becomes a
thin compatibility wrapper that no longer modifies production source. The scope
covers the first representative runner migration; remaining runners are out of
scope and require separate packets with caller and evidence audits.

## Contracts and behavior

- Every spec path stays inside the selected repository and every explicit
  source anchor must occur exactly once before a run starts.
- Mutation happens only in a disposable snapshot. The subject checkout is
  byte-identical before and after a run.
- The baseline must be green. Missing anchors, compile failures, timeouts and
  runner failures are never counted as kills.
- A mutation can select its historical exact pytest node and name the test
  that must fail. An unrelated red test is not credited as detection.
- Pytest subprocesses disable plugin autoload and bytecode writes. This keeps
  equal-length mutations bound to the exact source bytes just written.
- Scoring continues through the existing registered `tools.mutation_score`
  effect door; no Registry target, effect, wiring or digest changes.

## Evidence, expected failures and review

The first old/new comparison exposed non-deterministic survivor sets in the
legacy in-place runner. CPython timestamp/size bytecode caching could reuse a
previous mutation's `.pyc` when several replacements had equal byte length and
ran within one Windows filesystem timestamp tick. That output is retained as
negative measurement evidence, not treated as an oracle.

After disabling bytecode writes in a cache-free sandbox, three consecutive
repository-tree shadows produced the same result: seven mutations caught and
`allow-symlink-component` survived. The surviving mutation remains visible and
the wrapper exits non-zero; this packet does not weaken or silently bless the
test gap. Budget: zero live provider or network calls; offline builder tests
only.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Strict declarative input | parser unit tests | malformed paths and ambiguous anchors refused |
| Exact test attribution | scripted classification tests | only named newly-red test catches mutant |
| Source isolation | end-to-end sandbox tests | working checkout unchanged |
| Bytecode isolation | subprocess environment test plus repeated shadow | identical survivor set |
| Caller compatibility | legacy script invocation | same path, non-zero on survivors |
| Effect stability | Registry digest | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

Rollback restores the old repository-tree script and removes its JSON spec;
the shared scorer additions are otherwise additive. No source artifact,
historical `runs/` evidence, CAS locator, database, ledger or release artifact
is migrated by this packet.
