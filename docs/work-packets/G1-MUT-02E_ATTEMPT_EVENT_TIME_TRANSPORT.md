# G1-MUT-02E - Attempt event-time mutation transport repair

## Frozen packet metadata

- Packet ID: G1-MUT-02E
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: cbc73362501ad2dca30dbb8ec92ce937e9f33ad3
- Dependencies: G1-MUT-02C, G1-MUT-02D, G1-HIER-03D, G1-WP-INDEX-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The historical `run_attempt_event_time_window_mutations.py` runner now applies
its three unchanged logical anchors to either LF or CRLF source without
normalizing the target file. The repair changes transport only: mutant IDs,
anchors, replacements, order, exact five-file selection, unbounded execution,
exit behavior and byte-exact final restoration remain frozen.

This is a preparatory packet, not the declarative migration. The historical
runner remains the execution authority for this campaign. G1-MUT-02F may move
the now-measurable contract to `tools.mutation_score --spec`; this packet adds
no spec, wrapper, common-runner option or second mutation implementation.

## Scope

The only implementation change is inside
`scripts/run_attempt_event_time_window_mutations.py`:

- translate each logical LF anchor and replacement to CRLF only when the
  decoded target source contains CRLF;
- write the already-adapted text with `newline=""` so Python performs no
  second translation;
- retain the existing `finally: TARGET.write_bytes(original)` restoration.

The pre-fix runner SHA-256 is
`e2b723f2541f32338026e3e0aa779213d0f0d5c6680dbfc2545cb4690d70168a`.
Its normalized post-fix source SHA-256 is
`9ee0814654b99c984e0cf002f71087877db01cf19948c9d3db5ef7cf038ca300`.
The frozen three-mutant semantic digest remains
`9f45fb294da71fd707f08de8b559a9c64f75908e08b584d6cddef4cfa2d93211`.

No production module, declarative mutation spec, common mutation runner, plan,
amendment, global Work Packet index, historical `runs/` evidence, generated
`dist/` artifact, Effect Registry row or persistent format changes.

## Contracts and behavior

- The test selection remains, in order, time tampering, time/preflight,
  lifecycle, lifecycle adversarial and spine-wire review.
- The mutants remain, in order,
  `accept-arbitrary-historical-record-time`,
  `accept-record-time-after-event` and
  `skip-terminal-time-binding`. Their exact anchor and replacement strings are
  covered by one frozen semantic digest.
- Anchor cardinality remains fail-closed: zero or multiple logical sites raise
  the same `RuntimeError`; no fuzzy search, fallback anchor or re-anchoring is
  introduced.
- On LF input, anchors and replacements remain LF. On CRLF input, both are
  translated to CRLF before the exact one-site count and replacement.
- `_write(..., newline="")` writes the prepared string verbatim. It cannot turn
  CRLF into CRCRLF or normalize CRLF to LF.
- Baseline failure remains exit 2, the first survivor remains exit 1 and three
  killed mutants remain exit 0. The subprocess is still intentionally
  unbounded, matching the frozen legacy contract.
- The authoritative target is restored with its original bytes after every
  mutant and again in `finally`, including exceptions.
- No provider, network, EDA, production Attempt or Registry path is changed or
  executed by the transport contracts.

## Acceptance matrix

| Claim/refusal | Evidence | Result |
|---|---|---|
| Pre-fix defect retained | exact legacy runner at base | mutant 2 anchor count 0; exit 1 |
| Pre-fix restoration | target blob before/after failed run | `ac7c379b41963b731e3536f4ac42db332639f109` unchanged |
| Mutant contract unchanged | AST literal semantic digest | 3 IDs/anchors/replacements exact |
| Test selection unchanged | imported tuple contract | exact 5 files in legacy order |
| LF transport | synthetic byte contract | exact LF output |
| CRLF transport | synthetic byte contract | exact CRLF output; no CRCRLF |
| Ambiguous/absent anchor | synthetic negative contracts | count 2/count 0 refused |
| Live repaired run 1 | CPython 3.13.5 | 3 killed; exit 0 |
| Live repaired run 2 | CPython 3.10.11 | 3 killed; exit 0 |
| Source restoration | target blob before/after each live run | unchanged |
| Line-ending restoration | target byte census | 245 CRLF / 245 LF bytes before and after |
| Python compatibility | focused contracts on 3.13.5 and 3.10.11 | 19 passed, 10 subtests on each |
| Prior mutation contracts | complete canonical/spec contract selection | 71 passed, 35 subtests on each |
| Effect stability | live Registry digest | unchanged |
| External-effect budget | fake files, AST audit and local pytest | no provider, network or EDA call |

## Migration and rollback

Rollback restores the base version of the event-time runner, removes its
focused transport contract and this packet, and restores the two inherited
inventory tests to classify the runner as untouched. That rollback also
restores the known Windows failure at mutant 2 and must not be presented as a
green mutation score.

There is no data migration. No SQLite database, ledger, CAS locator, source
artifact, historical evidence, Effect Lease, Gate report, Registry row or
release artifact changes.

G1-MUT-02F must re-audit callers before replacing the historical script with a
thin declarative wrapper. It must preserve this three-mutant semantic digest,
the exact five-file selection, unbounded timeout, exit classifications and
target-byte restoration. This packet grants no authority to re-anchor a mutant.

## Evidence expected failures and review

The required negative evidence is the pre-fix live run on the exact base. Its
baseline and first mutation completed, then
`accept-record-time-after-event` refused with
`expected one mutation site, found 0` and process exit 1. The source contained
245 CRLF sequences; the frozen multiline anchor contained LF. The target blob
was `ac7c379b41963b731e3536f4ac42db332639f109` both before and after the
exception. This failure is retained here rather than relabelled as a survivor,
kill or complete campaign.

After the transport repair, independent CPython 3.13 and 3.10 live runs each
kill all three unchanged mutants and exit 0. Both leave the exact target blob
and its original line endings unchanged. There is no survivor, not-applicable
row or timeout claim.

The blocked `run_write_evidence_production_mutations.py` remains untouched. Its
HIER-04B anchor and Windows restore problems are not hidden or repaired here.
The global Work Packet index is intentionally not regenerated in this packet
branch; coordinated integration owns its single later refresh. The read-only
global check currently stops first on the inherited G1-HERMES-01 primary,
which lacks three required post-index sections; this packet does not rewrite
that unrelated artifact.

The read-only code-ontology preflight used repository label `g1-mut-02e`, no
snapshot and no workspace. It observed static evidence only, wrote no files,
executed no target code, made no direct network request and used no LLM
enrichment. It saw 1,431 Python files, excluded three directories and 29
sensitive names, and reports partial Python coverage for calls, decorators,
declarations, imports, inheritance and pipeline roles. Runtime dispatch and
runtime imports are unsupported; dynamic imports, descriptor dispatch,
generated code, monkeypatching and runtime metaprogramming remain outside
static proof. No relationship span was materialized. RDF/Turtle is portable
but store extensions require mapping; static correlation and change proximity
do not establish causation.

Independent review must confirm the exact pre-fix failure, unchanged semantic
digest and selection, LF/CRLF negative contracts, both live runs, byte-exact
restoration, unchanged Registry digest and absence of production/spec/common-
runner changes.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
