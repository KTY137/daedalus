# G0-RWI-20J — Repository Write Guard Structural Replay

## Parent and purpose

This packet is stacked on exact parent
`a59e693a2fcfe54554de28ccf6747f9bf111cc0a` from
`g0/python-target-structure-linear`.

It joins the authenticated repository-write evidence chain, authenticated guard
implementation manifest, exact repository source reader, and conservative
Python target front-end. The verifier proves structural correspondence only: a
declared guard contract has one exact evidence binding per production surface,
the evidence matches the authenticated manifest, and the named Python target
exists uniquely in the exact source bytes named by its digest.

## Cross-layer replay

The verifier snapshots the caller's evidence mapping once and then:

1. re-materializes and re-authenticates the complete evidence-origin and
   source-anchor chain;
2. re-materializes the same snapshot independently;
3. authenticates the short-lived guard implementation manifest against the
   exact classification digest and revision;
4. checks the classification, materialization, source-anchor report,
   attestation, manifest report, and manifest digest chain;
5. refuses a vacuous or inventory-only/unguarded production projection;
6. requires the manifest contract set to equal the declared production
   contract set;
7. requires exactly one guard evidence binding for every surface/contract pair;
8. replays the exact canonical guard payload and binds it to the authenticated
   manifest target and source digest;
9. resolves that target structurally against the exact repository source tree;
10. emits a deterministic record set binding evidence surface, CAS locator,
    contract, implementation target, source digest/path/size, definition kind,
    and source positions.

Retired classifications may remain in the classification, but retaining guard
contract evidence on a retired row is rejected rather than silently ignored.

## Deliberate non-authority

A Python definition's structural presence does not establish its behavior. This
packet does not import or execute the implementation, prove that a guard ran,
or authenticate behavioral conformance. The report therefore asserts:

- `origin_authenticated=true`;
- `source_anchor_semantics_verified=true`;
- `guard_manifest_authenticated=true`;
- `guard_contract_structure_verified=true`;
- `guard_contract_semantics_verified=false`;
- `semantic_receipts_verified=false`;
- `evidence_authenticated=false`;
- `gate_report_bound=false`;
- `closed=false`.

A dependent packet must define and authenticate a behavioral guard conformance
contract without converting source shape or an LLM statement into hard
evidence.

## Adversarial batch

Prepared behavior tests cover deterministic subject joining, stale revisions and
classifications, wrong origin and manifest keys, manifest contract substitution,
guard target and digest substitution, changed implementation bytes, missing and
duplicate AST targets, duplicate evidence bindings, inventory-only vacuity,
cross-layer report detachment, one-shot blob mappings, and malformed mappings.

A separate AST/source counter-review checks read-only authority, verification
ordering, the complete digest chain, non-vacuous exact coverage, one-time blob
snapshotting, permanent non-semantic/Gate claims, and record binding. Ten
bounded mutants attack authority escalation and the principal bypass fences.

The current automation runtime has repository write and review access but no
executable private-repository checkout. No test result has been inferred from
source inspection or an LLM assertion. Exact-head CI requests Ubuntu and Windows
on Python 3.10 and 3.12 with two hash seeds, predecessor regressions, mutation,
Iron Plan verification, full suite, package build, and isolated-wheel import.
GitHub Actions issue #67 currently terminates hosted jobs before Step 1 with no
logs or artifacts; such runs are infrastructure observations only.

No merge, promotion, OwnerApproval, or Gate transition is requested.
