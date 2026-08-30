# WP-G1-T2-EVIDENCE-HARDENING-R2 - Tier-2 evidence truth boundary

- Status: local candidate; independent re-review and executable exact-head CI required
- Classification: `ALIGNED`
- Active gate: Gate 1 - Renovation ignition slice (supporting evaluator
  integrity; this packet neither advances nor closes Gate 1)
- Owner: repository owner (`KTY137`)
- Implementation branch: `review/pr291-evidence-hardening-fixes` (local only)
- Implementation base: `0db2e1ece81335f9f5483454c13a97ac7a34f6d3`
- PR comparison base: `e5f55840a12dcfb1a50935c6080f06306a8854a8`
- Plan revision: commit `657c8af5f9707de3882a71716bcd8ff3d9aa6146`,
  SHA-256 `7cccda0fb75ff60af846b0c7eb697f6f3fd9fdd76ca2f4ae3aa5670ee2f3c704`
- Dependencies: issues #252 and #268; prior provider-failure separation from
  #253; neutral terminal presentation boundary from #306; hosted-runner
  allocation incident #67

## Primary acceptance claim

For built-in Tier-2 tasks, generated text that retracts, replaces, corrects,
modally negates, or prohibits an expected fact cannot become semantic-success
evidence merely by containing the expected token. The same canonical guard
remains in force via the package, historical `harness`, historical `report`,
alternate import order, and `tier2` reload. Every terminal-facing metadata
field is rendered as at most 160 printable ASCII characters on one line,
without mutating the retained result dictionary.

This is a conservative deterministic refusal boundary, not a general natural-
language-entailment claim. Lexical coverage remains separately observable.

## Plan and authority boundary

This packet reinforces the plan invariant that models propose and independent
evidence verifies. It changes only the private Tier-2 evaluator and its
presentation adapter. It adds no effectful entrypoint, event or artifact store,
candidate identity, graph authority, policy path, promotion path, automatic
merge, or automatic evaluation-to-policy feedback.

`daedalus/eval/_text_integrity.py` is the sole owner of generated-text assertion
guards. Its historical `safe_ascii_field` name delegates to the neutral
presentation boundary in `daedalus/text_integrity.py`, so Loop and Eval do not
mint competing terminal policies. `daedalus/eval/tier2.py` imports the guards
directly and remains the sole owner of live-model execution, validation,
receipts, and Tier-2 rendering. Historical `harness` and `report` names are
call-time compatibility delegates only; they contain no second implementation
and perform no import-time mutation.

## Frozen scope

In scope, exact paths:

- `.github/workflows/g1-tier2-eval-integrity.yml`
- `daedalus/eval/__init__.py`
- `daedalus/eval/__main__.py`
- `daedalus/eval/_text_integrity.py`
- `daedalus/eval/harness.py`
- `daedalus/eval/report.py`
- `daedalus/eval/tier2.py`
- `tests/test_eval.py`
- `tests/test_eval_tier2_integrity.py`
- `tests/test_eval_tier2_text_evidence_nemesis.py`
- `docs/WP-G1-TIER2-EVIDENCE-HARDENING-R2.md`

Forbidden paths and changes:

- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment chain, and `AGENTS.md`;
- policy, effect-boundary, promotion, ledger, event-spine, artifact-identity,
  storage, graph, candidate-runtime, and Project Twin implementation paths;
- evaluator task sources, gold labels, provider configuration, model prompts,
  token budgets, A/B context construction, and retained answer receipts;
- dependency or lock-file changes, new workflows, workflow dispatches, branch
  consolidation, remote branch/PR mutation, pushes, merges, and promotion;
- any claim that regex guards prove general semantic correctness.

## Contract changes

1. `expected_asserted(answer, expected)` examines every occurrence and refuses
   the complete expected fact if any occurrence is negated, hedged, questioned,
   rebutted, corrected, retracted, replaced, prohibited, forbidden, disallowed,
   banned, avoided, described as unnecessary, or rejected by bounded `should`
   / `must` modal grammar within its bounded grammar.
2. Correction/retraction markers before a new positive assertion are not a
   global blacklist. Positive controls such as `Correction: it calls
   cached_index, not build_index` and `14 days, not 10 days` remain valid. A
   directly following `but actually` clause rejects the earlier assertion only
   when that bounded replacement clause does not assert the expected fact
   again.
3. The lexical fraction remains unchanged and cannot alone become semantic
   success. Unknown tasks remain unvalidated and outside the denominator.
4. Validator receipts and the scoring method advance to version 2 so changed
   evaluator semantics are not mislabeled as version 1 evidence.
5. `safe_ascii_field` delegates to the neutral `safe_terminal_text` boundary,
   which first collapses whitespace, replaces non-ASCII/control characters,
   then truncates to 160 characters with an ASCII `...` marker. It is
   presentation-only and never writes into the input result dictionary.
6. Compatibility imports delegate to the live canonical Tier-2 functions at
   call time. Reloading `tier2` cannot restore a legacy scorer or renderer.

## Deterministic bounds and budgets

- Terminal field: at most 160 rendered characters after sanitation.
- Correction lookahead: at most 192 characters after an expected occurrence;
  at most 64 characters may finish the occurrence's current sentence.
- `but actually` replacement inspection: at most 128 characters in the direct
  replacement clause.
- Prefix rejection scope: at most seven lexical words before an occurrence.
- Post-token modal rejection permits at most one intervening lexical subject
  suffix (for example `days` in `14 days should not be used`).
- Existing audit-answer bound remains 16,384 characters.
- Existing provider timeout, prompts, temperature, token cap, and A/B context
  budgets are unchanged.
- The same guard and validator version apply to arms A and B; no budget
  asymmetry is introduced.
- Focused local suite budget: 30 seconds without network or provider calls.
- Broad eval-suite budget: 300 seconds without network or provider calls.
- Required interpreter matrix: Python 3.10 and 3.12. Local-only evidence on one
  interpreter cannot substitute for executable exact-head matrix evidence.

## Baseline and retained negative evidence

On implementation base `0db2e1ec`, the focused suite reported `21 passed, 8
subtests passed`, yet all of the following still produced guarded lexical and
semantic success:

- `Claim: it calls cached_index. Correction: it does not.`
- `It calls cached_index. Actually, it calls build_index instead.`
- `It calls cached_index. I retract that claim.`
- `The cactus interval is 14 days. Correction: 10 days.`
- `The command says water is prohibited.`
- `The command forbids water.`

This is the motivating negative evidence; it must remain in the regression
corpus. The PR's hosted Python 3.10/3.12 jobs on that base had `steps=[]` and
`runner_id=0`. They are #67 infrastructure evidence, not executed test evidence
and not a product failure or a green result.

Independent review of local commit
`83bd0217fd399bc123d4c91c2bd86329795eb302` retained a second concrete negative
probe: `should not`, `must not`, `should never`, ASCII and typographic
`shouldn't` / `mustn't`, `14 days should not be used`, and `It uses water, but
actually it uses fertilizer` all still returned guarded success. The amended
candidate adds those exact failures and bounded positive counterexamples to the
regression corpus; this review finding is not attributed to implementation base
`0db2e1ec` without separate execution there.

## Acceptance matrix

| ID | Contract / fault injection | Deterministic acceptance |
| --- | --- | --- |
| A1 | Documented `Correction:`, `Actually`, direct `but actually` replacement, and explicit retraction after a token | Guarded lexical success and semantic success are both false; lexical fraction remains 1.0 |
| A2 | Numeric `14 days` followed by correction to `10 days` or bounded modal rejection | Both guarded and semantic success are false |
| A3 | `water is prohibited`, `forbids water`, and `water is unnecessary` | Both guarded and semantic success are false |
| A4 | Correction vocabulary before a correct assertion and unrelated negation/prohibition | Positive controls remain semantic successes |
| A5 | Contradictory second mention, question/rebuttal, direct negation, bounded `should` / `must` rejection (including ASCII and typographic contractions), and hedge | Every expected occurrence is examined and any rejected occurrence poisons success |
| A6 | Historical `harness`/`report` references captured before `importlib.reload(tier2)` | They continue to call the reloaded canonical scorer/renderer; no raw control or legacy success returns |
| A7 | C0, DEL, Unicode/bidi, CR/LF, and oversized values in provider, scored, measurement-error, unvalidated, errored, and skipped fields | Every field is one-line printable ASCII and at most 160 characters; no forged renderer line appears |
| A8 | Renderer receives a malicious result dictionary | Deep-equal input remains unchanged after rendering |
| A9 | Missing validator, provider exception/empty output, and truncated answer | Remain excluded as unvalidated or measurement errors, never ordinary model failures |
| A10 | Python 3.10/3.12 focused workflow | Compile succeeds and focused Tier-2 integrity tests execute real steps and pass on the exact candidate head |
| A11 | Affected legacy eval suites | Broad eval tests pass; any baseline/environment failure is named separately and not laundered |

## Verification commands and evidence

All local pytest commands set `PYTHONDONTWRITEBYTECODE=1`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, disable pytest's cache provider, and make no
provider/network call.

Candidate evidence recorded so far:

```text
Environment: Python 3.10.11, Windows-10-10.0.26200-SP0

# First builder iteration (retained negative evidence)
python -m pytest -q -p no:cacheprovider \
  tests/test_eval_tier2_integrity.py \
  tests/test_eval_tier2_text_evidence_nemesis.py
1 failed, 24 passed, 8 subtests passed in 1.39s
Failure: the expected label was `14`, so `days` separated the token from the
following `Correction:` marker. The bounded grammar was repaired to finish at
most the current 64-character sentence before recognizing the correction.

# Repaired adversarial surface
python -m pytest -q -p no:cacheprovider \
  tests/test_eval_tier2_integrity.py \
  tests/test_eval_tier2_text_evidence_nemesis.py
26 passed, 8 subtests passed in 0.95s

# Workflow-equivalent focused surface
python -m pytest -q -p no:cacheprovider \
  tests/test_eval_tier2_integrity.py \
  tests/test_eval_tier2_text_evidence_nemesis.py \
  tests/test_eval.py::EvalTier1Test::test_tier2_skips_cleanly_without_provider
27 passed, 8 subtests passed in 4.09s

# Independent deterministic oracle regressions
python -m pytest -q -p no:cacheprovider tests/test_eval_oracle.py
36 passed in 6.88s

# Broad affected eval surface
python -m pytest -q -p no:cacheprovider \
  tests/test_eval.py tests/test_eval_correctness.py tests/test_eval_mint.py \
  tests/test_eval_oracle.py tests/test_eval_provenance.py \
  tests/test_eval_tier2_integrity.py \
  tests/test_eval_tier2_text_evidence_nemesis.py
201 passed, 30 subtests passed, 1 failed in 145.54s
Only failure: tests/test_eval_provenance.py:42 expected `OUTSIDE` but the isolated
interpreter reported `ModuleNotFoundError: No module named 'daedalus'`. The same
failure was present before this packet; neither provenance source nor that test
is in the implementation diff. It is named baseline/environment evidence, not
a Tier-2 pass and not a regression attributed to this packet. The all-C0/C1
property regression was added after this broad run and executed in the final
27-test focused run above; production code did not change between those runs.

# Independent-review remediation on local commit 83bd0217
python -m pytest -q -p no:cacheprovider \
  tests/test_eval_tier2_integrity.py \
  tests/test_eval_tier2_text_evidence_nemesis.py \
  tests/test_eval.py::EvalTier1Test::test_tier2_skips_cleanly_without_provider
31 passed, 8 subtests passed in 2.50s

python -m pytest -q -p no:cacheprovider tests/test_eval_oracle.py
36 passed in 12.51s

python -m pytest -q -p no:cacheprovider \
  tests/test_eval.py tests/test_eval_correctness.py tests/test_eval_mint.py \
  tests/test_eval_oracle.py tests/test_eval_provenance.py \
  tests/test_eval_tier2_integrity.py \
  tests/test_eval_tier2_text_evidence_nemesis.py
206 passed, 30 subtests passed, 1 failed in 355.31s
Only failure: the same diff-external
tests/test_eval_provenance.py:42 isolation expectation described above. The
isolated interpreter returned `ModuleNotFoundError: No module named 'daedalus'`
instead of a reason containing `OUTSIDE`; no provenance source or test is in
this candidate diff. This result is retained as a baseline/environment failure,
not counted as green evidence and not attributed to the Tier-2 change. The run
also exceeded the packet's declared 300-second broad-suite budget by 55.31
seconds, so it is retained as diagnostic coverage and does not satisfy a
within-budget A11 run.
```

Pending before owner merge decision:

- executable exact-head CI on Python 3.10 and 3.12;
- a within-budget broad affected-suite run;
- independent review of this repair candidate.

## Expected failures and residual risk

- Hosted jobs may fail before Step 1 while #67 remains active. Such a run is
  explicitly insufficient evidence and must not be relabeled as green.
- The deterministic grammar intentionally has false negatives. For example, a
  question mentioning the expected token before a later affirmative answer can
  poison the result. This is safer than false-positive fitness but must be
  measured before comparative model claims.
- Novel correction or entailment language can remain outside the bounded
  grammar. A versioned structured-answer schema or independently validated
  judge is the replacement path; further unbounded regex growth is not.
- A local Python 3.10 run cannot prove Python 3.12 behavior.

Kill criteria: stop the packet and do not merge if any A1-A9 case fails, if a
historical import/reload restores legacy semantics, if renderer output contains
raw terminal controls or a field over 160 characters, if canonical evidence is
mutated, or if the same evaluator version is reported across changed semantics.

## Rollback and evidence handoff

Rollback is one atomic revert of this packet's code, tests, and documentation to
implementation base `0db2e1ec`. There is no persisted-data, schema, provider,
or artifact migration. Preserve this Work Packet, the adversarial cases, test
logs, and failed/zero-step CI records as negative evidence even if the code is
reverted.

The handoff must name the final local/PR commit, exact commands and interpreter
versions, wall-clock results, any baseline-only failures, executable CI job
URLs, residual false-negative risk, and independent-review disposition. No
automatic merge or promotion is authorized.

## Independent review questions

1. Can any correction, replacement, retraction, prohibition, or repeated
   occurrence in A1-A5 still enter semantic-success evidence?
2. Does any import order, captured historical function, or reload restore a
   second scorer/sanitizer/renderer authority?
3. Are all renderer-owned metadata paths sanitized and bounded without changing
   canonical evidence?
4. Are A/B budgets and failure denominators unchanged and honestly versioned?
5. Did any change escape the frozen paths or touch a forbidden authority?
