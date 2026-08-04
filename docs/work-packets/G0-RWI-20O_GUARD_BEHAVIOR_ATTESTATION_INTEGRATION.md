# G0-RWI-20O — Guard Behavior Attestation Controlled Integration

## Exact parent and source

This Work Packet is stacked on exact parent
`bbb0aef26b5fb6c6abc746f5f322cc0235f39e21` from
`g0/repository-write-effect-lease-replay-linear`.

It ports the already separated guard-behavior attestation work from draft PR
#179, exact source revision
`05376b15b76d49b7c032adcb60ddd0d30c13e5a6`, into the selected Gate-0
repository-write line. The implementation, schema, mutation runner, behavior
tests and source counter-review are retained as exact Git blobs recorded in the
machine-readable Work Packet. The source PR is not merged or widened into a
collection PR.

## Primary acceptance claim

The selected linear stack exposes one strict, bounded authentication contract
for externally produced repository-write guard-behavior results. The signed
subject binds the exact source revision, guard-structure report, result-set
identity, behavior-harness identity and source digest, Runtime Manifest digest,
and a canonical non-empty result set.

Every structural guard contract must be represented exactly and must contain at
least one expected `allow` vector and one expected `refuse` vector. Every
observed result must equal the expected result. Missing negative coverage,
failed results, stale subjects, key substitution, changed structure, harness or
runtime subjects, noncanonical wire data and malformed timestamps fail closed.

## Authority boundary

Authentication is not execution. This packet does not import or invoke a guard,
replay the behavior harness, prove Docker isolation, validate the Runtime
Manifest, establish RuntimeConformance, authenticate all semantic receipt
classes, bind GateReport-v2, issue OwnerApproval, merge or promote.

The report remains permanently explicit that guard execution and guard-contract
semantics are unverified and that `closed=false`.

## Adversarial batch

The retained test material covers deterministic issue/parse/verify behavior,
multiple contracts, exact positive and negative coverage, failed observations,
contract and signature substitution, unknown and wrong keys, stale revision,
changed structure/harness/runtime subjects, future/expired/overlong attestations,
duplicate identities, strict canonical JSON and malformed types.

A separate AST/source review checks absence of execution and effect authority,
signature-before-subject comparison, exact non-vacuous coverage, bounded strict
parsing, complete signed-subject binding and permanent false semantic/runtime/Gate
claims. Ten bounded mutants target trust escalation and the principal
signature, coverage and subject-binding bypasses.

The requested matrix is Ubuntu and Windows on Python 3.10 and 3.12 with two hash
seeds, focused predecessor regressions, mutation, Iron Plan verification, full
suite, package build and isolated-wheel import.

## Verification state and remaining work

The automation environment can modify and review the private repository but
cannot execute an exact private checkout. Source inspection and model statements
are not recorded as hard evidence. Exact-head CI remains mandatory.

GitHub Actions issue #67 currently terminates hosted jobs before Step 1 with no
steps, logs or artifacts. Such runs are infrastructure observations only.

A dependent packet must independently replay the exact harness under an
authenticated current Runtime Manifest and RuntimeConformanceReceipt, then join
that replay with the selected repository-write semantic chain. Primary-Checkout
disjointness, retirement semantics, live evidence population, GateReport-v2
binding, caller migration, Docker sandboxing, Primary-Checkout mutation
exclusion and the complete fault matrix remain open.

No change to `main` or `experimental`, no OwnerApproval, no automatic promotion,
no merge and no Gate transition are requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
