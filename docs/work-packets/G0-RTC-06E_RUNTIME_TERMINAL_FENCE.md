# G0-RTC-06E — Runtime terminal trust fence

## Objective

Close the cross-ledger time-of-check/time-of-use gap between the last runtime
trust verification and persistence of a successful Effect Lease terminal
receipt.

This packet is stacked on `G0-RTC-06D` and does not migrate a provider or claim
that runtime conformance is complete.

## Boundary

A runtime provider result may be released only after all of the following are
durable:

1. the exact runtime-bound Effect Lease grant;
2. the exact execution start receipt;
3. content-addressed output evidence; and
4. a `COMPLETED` terminal receipt written while the exact authenticated runtime
   trust row is protected from concurrent quarantine or rotation.

The trust ledger and effect ledger remain separate authorities. The fence uses
`BEGIN IMMEDIATE` on the trust ledger only to serialize the final authenticated
read through effect-terminal persistence. No trust row is modified by the
fence, and this is not represented as a distributed transaction.

## Refusals

The broker refuses or cancels completion when:

- quarantine wins the trust-ledger writer transaction before the terminal fence;
- the admitted record identity, manifest, receipt, envelope, runtime, or source
  revision changes after the prior plain verification;
- trust expires before the terminal boundary;
- the persisted trust row fails its ledger authentication;
- the runtime trust and effect ledgers point at the same SQLite file, which
  would self-deadlock when the effect terminal opens its own transaction.

If the fence refuses after the provider has already returned, the provider value
is withheld and the existing start is persisted as `CANCELLED`.

## Adversarial cases

The focused tests exercise both orderings of the race:

- completion owns the trust writer lock first: quarantine blocks until the
  `COMPLETED` receipt is durable;
- quarantine or record replacement occurs immediately after the last ordinary
  verification: the fence observes it, withholds output, and records
  `CANCELLED` rather than `COMPLETED`.

A malformed shared-ledger configuration is refused before grant, start, or
provider invocation.

## Verification contract

The dedicated workflow requests:

- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification;
- compile-all;
- focused broker, runtime admission, Effect Lease, trust-store and effect
  boundary tests; and
- an isolated wheel import smoke.

Exact-head CI evidence must be recorded separately. A workflow that fails
before runner step 1 is infrastructure evidence only and must not be reported as
a passing or failing product test.

## Deliberate remaining blockers

- Claude, Codex and Ollama public provider entrypoints remain non-central until
  their call paths consume the broker without a direct bypass.
- Live externally trusted conformance envelopes and production key distribution
  remain external runtime/infrastructure work.
- Gate 0 remains open until every effectful production entrypoint is central,
  the full fault matrix passes, and the machine-readable release report is
  `closed=true`.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
