# G0-RWI-20K — Repository Write Runtime Conformance Semantic Replay

## Parent and purpose

This packet is stacked on exact parent
`5f07c2fbd2956557f626c7d2efeb2b8c4352ff0a` from
`g0/repository-write-guard-structure-linear`.

It joins the authenticated repository-write evidence chain from the predecessor
with the existing live-runtime conformance and persisted trust authorities. The
verifier proves that every production-reachable repository-write surface is
centrally guarded and retains exactly one runtime-conformance receipt whose
complete typed subject is current, passed, exact-revision-bound, live-runtime
bound, and present as an active authenticated record in the persisted runtime
trust ledger.

## Runtime semantic replay

The verifier snapshots caller-supplied evidence, typed runtime subjects, and
runtime-ledger mappings once. It then:

1. replays the complete guard-structure predecessor against the exact evidence
   snapshot and repository source tree;
2. independently materializes the same CAS evidence and checks the predecessor
   digest chain;
3. rejects an empty production projection and any production row that is not
   `central`;
4. requires exactly one runtime-conformance binding on every production row and
   refuses retained runtime evidence on non-production rows;
5. replays the strict canonical evidence envelope and payload, including exact
   `RuntimeConformanceReceipt` schema, receipt digest, runtime identity, and
   strict `conformant=true`;
6. requires the typed runtime-subject set and trust-ledger set to exactly equal
   the retained evidence subjects;
7. binds the typed `RuntimeManifest`, `RuntimeProbeIdentity`,
   `RuntimeConformanceReceipt`, and `RuntimeConformanceEnvelope` to one exact
   revision and runtime identity;
8. reads the ledger's authenticated audit projection and requires exactly one
   active, unexpired record with exact envelope, probe, receipt, manifest, and
   revision bindings;
9. replays the live production envelope through the existing runtime trust
   verifier, which checks the complete canonical eight-check receipt and
   freshness;
10. emits deterministic records binding the repository-write surface and CAS
    locator to the persisted trust record, typed runtime subject, observation,
    expiry, and canonical check-set digest.

The packet never calls ledger admission, quarantine, `require_active`, lease
issuance, or any repository-write path. Expired trust is rejected without
mutating persisted state.

## Deliberate remaining boundary

Runtime conformance is one required evidence class, not complete Gate-0
closure. The report asserts
`runtime_conformance_semantics_verified=true`, but keeps all of the following
mechanically false:

- guard behavioral semantics;
- Effect-Lease semantic replay;
- Primary-Checkout disjointness semantic replay;
- retirement semantic replay;
- complete semantic-receipt verification;
- complete evidence authentication;
- GateReport binding and `closed`.

A structurally present guard is not treated as behavior, and no LLM statement
is accepted as hard evidence.

## Adversarial batch

Prepared tests cover exact deterministic replay, stale revisions, non-central
production rows, duplicate runtime bindings, missing/extra or mis-keyed typed
subjects, receipt and runtime-identity substitution, missing/extra ledgers,
unadmitted, quarantined, expired, and HMAC-corrupt trust rows, predecessor-report
detachment, one-shot caller mappings, malformed inputs, and detached report
record sets.

A separate AST/source counter-review checks absence of write/effect/callback
authority, one-time snapshots, predecessor-before-runtime ordering, exact
central coverage, typed and persisted authority replay, strict canonical
payload parsing, permanent incomplete-Gate claims, and deterministic replay
record binding. Ten bounded mutants attack claim escalation and the principal
coverage, trust, and predecessor-chain bypasses.

The current automation runtime has repository write and review access but no
executable private-repository checkout. No test result is inferred from source
inspection or an LLM assertion. Exact-head CI requests Ubuntu and Windows on
Python 3.10 and 3.12 with two hash seeds, predecessor regressions, mutation,
Iron Plan verification, full suite, package build, and isolated-wheel import.
GitHub Actions issue #67 currently terminates hosted jobs before Step 1 with no
logs or artifacts; such runs are infrastructure observations only.

No merge, promotion, OwnerApproval, runtime admission, or Gate transition is
requested.
