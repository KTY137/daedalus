# EXP-TOMLKIT-DOTTED-PARENT-001

Status: **frozen design; not activated; not run; non-authoritative**

Classification: **EXPERIMENT**

Active delivery gate: **Gate 0 — Canonical Kernel**

Target evidence surface: **later Gate 3 baseline lab**

Promotion: **forbidden**

Machine-readable companion:
[`exp-tomlkit-dotted-parent-001.json`](../../configs/experiments/exp-tomlkit-dotted-parent-001.json)

This packet pre-registers one bounded external-repository evolution experiment.
It does not amend the Iron Plan, close any gate, authorize an effect, create a
production path, or establish a comparative claim. The active Gate remains
Gate 0. Execution is permitted only as an isolated experiment after every
activation blocker in the companion JSON is resolved and recorded through the
canonical kernel.

The checked-in design is frozen except for fields explicitly represented as
`null` in the JSON. Activation may resolve those fields and produce a sealed
specification digest, but it may not change the hypothesis, task, arms, budgets,
seeds, writable scope, evaluator semantics, or kill criteria. A substantive
change requires a new experiment ID. No field may be changed after the first
candidate result is observed.

## Iron Plan alignment

The experiment touches these constitutional invariants:

- artifact identity: the exact source tree, submodule revision, and every
  candidate tree remain authoritative content-addressed artifacts;
- isolation: the candidate cannot modify tests, evaluator, policy, evidence,
  budgets, dependencies, or promotion;
- evidence boundary: a model or graph may propose a patch, while independent
  parsers and sealed tests decide correctness;
- atomic revisions: Code/AST, Type, Data, and Knowledge are compiled from one
  exact source revision and exact submodule revision;
- provenance: inputs, context, model, costs, commands, outputs, failures, and
  evaluator results receive traceable receipts;
- bounded effects: writes, processes, time, concurrency, spend, egress, and the
  kill switch are enforced at the runtime boundary;
- honest claims: representation arms use the same generator, task, seeds,
  context budget, output budget, wall budget, and sealed evaluator.

It probes the Fourfold Project Twin prior. A single repository task can validate
the real execution chain and produce negative evidence, but it cannot close
Gate 3 or establish general Fourfold superiority.

## Frozen external inputs

| Input | Frozen value | Evidence |
| --- | --- | --- |
| Repository | `python-poetry/tomlkit` | <https://github.com/python-poetry/tomlkit> |
| Source commit | `d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727` | <https://github.com/python-poetry/tomlkit/commit/d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727> |
| Release at that commit | `0.15.1` | the pinned commit updates the package version and changelog |
| Declared license | MIT | <https://github.com/python-poetry/tomlkit/blob/d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727/LICENSE> |
| Package license metadata | MIT | <https://github.com/python-poetry/tomlkit/blob/d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727/pyproject.toml> |
| Declared test submodule URL | `https://github.com/BurntSushi/toml-test.git` | <https://github.com/python-poetry/tomlkit/blob/d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727/.gitmodules> |
| Test submodule commit | `08ed8697864548b3cdb4b8decbf496bef47e1c82` | <https://github.com/toml-lang/toml-test/commit/08ed8697864548b3cdb4b8decbf496bef47e1c82> |
| Public defect provenance | issue `#557`, opened 2026-07-08 | <https://github.com/python-poetry/tomlkit/issues/557> |

The source repository has no populated GitHub Wiki: its `/wiki` URL redirects
to the repository and the corresponding `.wiki.git` endpoint was absent during
the 2026-08-03 read-only survey. The same-revision `docs/`, `README.md`, and
`CHANGELOG.md` are the Knowledge-plane inputs. This is preferable to a separate,
independently revised wiki for an atomic experiment.

The issue URL is retained here for provenance. This Daedalus packet, the issue
body, comments, later commits, and any external solution must never be included
in candidate-visible context.

### Frozen source receipt — 2026-08-03

The exact source and submodule commits were fetched into a dedicated local
experiment staging directory and exported twice with `git archive`. Both
independent exports were byte-identical. This resolves source preparation
fields only; the experiment remains unactivated and no candidate has run.

| Artifact | Identity |
| --- | --- |
| TOMLKit commit | `d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727` |
| TOMLKit tree | `1af692f3944e67c7de962dc8094faf184ec3427f` |
| TOMLKit archive | 563,200 bytes; SHA-256 `9184035b8a186089bad9ad8e3f09568182dbe43827b613f01ff269e84bbe996f` |
| `toml-test` commit | `08ed8697864548b3cdb4b8decbf496bef47e1c82` |
| `toml-test` tree | `4b9ff71fa2de930104473805a662117f5b38ea87` |
| `toml-test` archive | 1,320,960 bytes; SHA-256 `0f3361e8b21f03bbf224647c2c541dc5732da42fca4a11c18fe174204be17434` |
| `LICENSE` bytes | SHA-256 `7ed726815881ce2360bbe9024b9fd1541ceefbe9b84d67bf47392181f4b6ca24` |
| `.gitmodules` bytes | SHA-256 `da0f4811c64c5b6f0ddeac28f5090449b4a9d44d3ed60b2bcafc9a75112e3af9` |

The pinned TOMLKit tree records `tests/toml-test` as mode `160000` at the exact
submodule commit above. Candidate materialization will use the exported trees
without `.git` metadata and will not expose the staging repositories.

### Fourfold coverage

- **Code / AST:** parser, item/container, document, and serializer
  implementation under `tomlkit/`.
- **Type:** typed APIs, class contracts, annotations, and `tomlkit/py.typed`.
- **Data:** TOML/JSON examples, repository fixtures, and the pinned `toml-test`
  conformance corpus.
- **Knowledge:** same-commit documentation, README, changelog, and declared
  style-preservation contract. External issue text is excluded.

Every compiled node and edge must carry the source revision and source locator.
A partial or mixed-revision graph invalidates the experiment.

## Hypothesis and task

Primary hypothesis:

> Under an equal generator and context budget, a verified, revision-atomic
> Fourfold context produces a higher rate of semantically correct,
> regression-free repairs than BM25, a Code-only graph, or four unconnected
> plane indices.

The concrete task is to preserve the fully qualified parent path when a table
is added below a container that originated from a parsed dotted key.

Public acceptance example:

```python
source = "[t]\na.b = 1\n"
document = tomlkit.loads(source)
document["t"]["a"]["c"] = {}
output = tomlkit.dumps(document)
```

The serialized output must be valid TOML with semantic value:

```python
{"t": {"a": {"b": 1, "c": {}}}}
```

It must materialize the new table beneath the qualified parent (for this
example, `[t.a.c]`), must not create a top-level `a`, and must retain unaffected
content and style according to the existing project contract. The sealed
evaluator covers deeper and quoted parent paths without exposing its exact
cases to the candidate.

## Recorded baseline reproduction

On 2026-08-03, a read-only research probe ran the real published
`tomlkit==0.15.1` package in an isolated `uv` environment:

```text
uv run --isolated --no-project --with tomlkit==0.15.1 python -
```

The probe performed the public parse/mutate/serialize chain and parsed the
result with Python's independent standard-library `tomllib` implementation.
Observed evidence:

```text
VERSION 0.15.1
ACTUAL {'t': {'a': {'b': 1}}, 'a': {'c': {}}}
EXPECTED {'t': {'a': {'b': 1, 'c': {}}}}
SEMANTIC_EQUAL False
WRONG_TOP_LEVEL_A True
EXPECTED_HEADER False
```

This is evidence that the task is real and was not satisfied by the published
baseline. It is not yet the sealed experiment baseline because the ephemeral
package artifact and toolchain were not retained with content digests. Before
activation, the harness must rebuild from the pinned source, prefetch and hash
all dependencies, deny network access, reproduce a green immutable upstream
suite, reproduce this one hidden-chain failure, and emit a canonical receipt.

## Candidate and effect scope

The candidate receives a source snapshot without `.git` history, issue or PR
content, evaluator material, prior candidates, or adaptive research memory.

| Capability | Frozen rule |
| --- | --- |
| Read | exact source snapshot, including same-commit code, tests, fixtures, and docs |
| Write | `tomlkit/**` only, inside one isolated candidate tree |
| Immutable | tests, docs, metadata, dependency files, CI, evaluator, policy, evidence, receipts, budget, and promotion |
| Network | denied during generation and evaluation |
| Secrets | none |
| External spend | denied; local compute is still measured |
| Concurrency | one candidate process per attempt |
| Promotion | forbidden; archive source artifact and evidence only |

Prompts and filesystem ACLs are not the boundary. A Gate-0 effect lease,
runtime manifest, conformance receipt, workspace isolation, and kill-switch
generation must enforce the scope. Their unresolved identities are explicit
activation blockers.

### No mocks and no test hacking

- The experiment may not use a mock, fake, canned, replay-only, or fixture model
  adapter as its generator.
- The receipt must identify the actual local provider, runtime version, model
  blob digest, request digest, response digest, token timings, and non-empty
  candidate source delta.
- Evaluation imports the materialized candidate and records
  `tomlkit.__file__`; evaluating the installed baseline by accident is a hard
  invalidation.
- Upstream tests and the hidden evaluator come from sealed read-only trees, not
  from the candidate tree. Candidate-authored test edits cannot influence the
  score.
- A generated claim, explanation, graph score, or model review is never an
  acceptance result.

## Arms, seeds, and equal budgets

The representation comparison has four arms:

| Arm | Context selector | Comparative role |
| --- | --- | --- |
| `bm25` | lexical BM25 over the frozen source corpus | simple retrieval baseline |
| `code_only_graph` | Code/AST plane only | graph-without-cross-plane baseline |
| `separate_planes` | independent Code/AST, Type, Data, and Knowledge indices with no cross-plane fusion | fusion ablation |
| `fourfold` | verified cross-plane Project Twin retrieval | experimental treatment |

Sanity arms are `no_change` and `simple_local_mutation`. They share the sealed
evaluator and candidate-count/wall constraints where applicable, but are
reported separately because they do not consume LLM context tokens.

Frozen stochastic seeds are:

```text
17, 23, 42, 71, 101
```

Each stochastic arm produces one candidate per seed. Every representation arm
uses the same task text, local generator, model blob, runtime, sampling
manifest, exactly 8,192 repository-context tokens, at most 2,048 generated
tokens, one generator call, zero evaluator-feedback rounds, a 600-second
generation limit, and a 1,200-second evaluation limit. Missing the exact
context budget or any other equality constraint invalidates that arm's
comparison; no padding with external or post-cutoff material is allowed.

Selected generator tag: `qwen2.5-coder:7b`. The model was publicly announced
before this 2026 defect (<https://qwenlm.github.io/blog/qwen2.5-coder/>), which
reduces temporal contamination risk. A tag is not identity: the Ollama model
blob digest, tokenizer identity, runtime version, sampling-manifest digest,
hardware manifest, and prompt digest are deliberately unresolved (`null`) and
must be sealed before execution.

The task records success rate, best-so-far AUC, wall time, input/output tokens,
compute, variance, candidate diversity, regressions, cost, and human
intervention. With one repository task, all comparative results remain pilot
evidence and may not be generalized.

## Full-chain evaluator

The evaluator is one transaction over a case corpus, not a collection of tiny
scores that can be gamed independently. Per-case observations are retained for
diagnosis, but acceptance is one all-or-nothing chain.

### Identity preflight

Before any candidate runs, the harness must:

1. resolve the source commit and exact submodule commit without following a
   moving branch;
2. create one canonical source archive, compute its SHA-256, and reuse its
   exact bytes for every arm;
3. compile one revision-atomic base Forest and Fourfold snapshot and retain
   their content digests, extractor versions, node/edge provenance, and plane
   coverage;
4. seal immutable upstream-test, hidden-evaluator, toolchain, dependency-lock,
   prompt, tokenizer, retrieval-implementation, and runtime identities;
5. prove that the candidate cannot read the evaluator or write outside
   `tomlkit/**` and that egress fails closed;
6. abort while any required identity in the companion JSON remains `null`.

### Evaluation transaction

For each candidate, the independent runner must:

1. verify the base source and submodule identities and reject forbidden path
   changes;
2. materialize and content-address the complete candidate source tree;
3. import from that tree, record the loaded module path, and run a real
   import/compile smoke test;
4. build a wheel, install it in a fresh environment, and verify that the
   installed files correspond to the candidate tree;
5. run the immutable complete upstream pytest suite, including the pinned
   `toml-test` corpus;
6. run strict type checking and a warning-as-error Sphinx documentation build;
7. execute the sealed parse -> mutate -> serialize -> independent `tomllib`
   parse chain across the public example and hidden corpus;
8. compare the independent semantic value, qualified table placement,
   unaffected siblings, quoted/deeper paths, and required style preservation;
9. retain commands, environment, stdout, stderr, exit codes, timings, and all
   negative outcomes as evidence;
10. emit a terminal receipt without merging, pushing, opening a PR, or
    promoting the candidate.

Exact evaluator commands and their tree digests are activation fields, not
guesses in this packet. They remain `null` until the evaluator is implemented
and independently reviewed.

### Pass condition

A candidate passes only if every identity and scope check succeeds, the full
immutable upstream suite remains green, type/docs/package checks pass, every
hidden chain case matches the independent semantic oracle, the expected
qualified parent is preserved, and no regression or forbidden effect is
observed. A partial score may aid diagnosis but cannot nominate a pass.

## Canonical receipts and logging

The canonical Event Store and content-addressed artifact store remain the only
authorities. Human-readable logs and dashboards are projections, never a new
experiment database. Each attempt receipt must include at least:

- experiment-spec ID and SHA-256, Iron Plan revision and digest;
- arm, seed, hypothesis/task digest, base commit, submodule commit, canonical
  source archive digest, Forest digest, and Fourfold snapshot digest;
- retrieval implementation/version digest, context-capsule digest, source
  locators, per-plane token counts, and total repository-context tokens;
- provider/runtime/model/tokenizer/sampling/prompt/hardware identities;
- requested, reserved, and actual token, wall-time, compute, concurrency, and
  spend budgets;
- policy decision, effect lease, runtime conformance, kill-switch generation,
  workspace, and allowed write roots;
- complete candidate-tree digest, patch digest, changed paths, and diff stats;
- evaluator tree, hidden suite, upstream tests, dependency lock, toolchain,
  command, environment, stdout, stderr, and result digests;
- success/failure/invalid classification, regression set, human intervention,
  cost, timing, GPU observations, and retained negative-evidence locators;
- explicit `promotion_allowed=false` and terminal archival state.

Chat messages, model explanations, and semantic-memory projections may link to
these receipts but may not replace them.

## Leakage controls

- Exclude issue #557, its comments, linked work, later commits, remote branches,
  external patches, and post-pin documentation from every candidate context.
- Deny web, GitHub, package-index, and arbitrary network access during
  generation and evaluation. Dependencies are prefetched, content-addressed,
  and mounted read-only before sealing.
- Do not expose hidden tests, evaluator paths, evaluator outputs, gold patches,
  or acceptance deltas to the candidate.
- Reset research adaptive memory between arms and seeds. Do not reuse a
  candidate, reflection, failure explanation, or solution across arms.
- Bind all planes and graph edges to the exact source revision. Remove
  post-task issue edges and reject mixed base/candidate snapshots.
- Use the identical task prompt and exact repository-context budget for all
  representation arms. Record actual tokens so extra context cannot explain a
  gain.
- Blind any human inspection to the arm until verdicts are sealed. Human or LLM
  review is advisory and cannot override deterministic acceptance.

## Invalidation and kill criteria

### Invalidate a run

Do not score the run if any of the following occurs:

- a required activation field remains unresolved;
- source, submodule, archive, graph, model, prompt, tokenizer, runtime,
  retrieval, toolchain, dependency, or evaluator identity differs across arms;
- the sealed base does not have a green upstream suite or does not reproduce
  the expected hidden-chain failure;
- the defect is already fixed in the materialized base;
- the graph is partial, mixed-revision, missing source locators, or includes
  post-cutoff issue/solution content;
- the candidate reads hidden material, changes an immutable path, escapes the
  write root, obtains network access, changes a budget/evaluator, or observes
  evaluator feedback;
- a mock/fake/canned generator is used, no real source delta is produced, or
  evaluation loads a package outside the candidate tree;
- token, candidate-count, sampling, seed, wall, or evaluator budgets are not
  equal for a claimed representation comparison;
- the harness or task is changed after any result is observed.

Invalid runs and their evidence are retained; they are not silently deleted or
counted as scientific losses.

### Stop or redesign the track

A poor Fourfold result first triggers the pre-registered integrity audit:
revision atomicity, plane extraction, edge provenance, query results, source
locators, context parity, evaluator independence, and runtime identity. If that
audit fails, the experiment is invalid implementation/evaluator evidence, not
a test of the prior; retain it, repair in a separate packet, and rerun the
unchanged frozen task.

If the audit passes, the result is honest evidence. Repeated budget-equal,
held-out experiments require stopping or redesigning the affected track when
the full representation does not beat BM25 or Code-only retrieval, four
separate indices are equivalent to fusion, randomized/incorrect cross-plane
edges are equivalent, a plane has no marginal contribution, gains are explained
by extra tokens, or graph cost worsens the quality/cost frontier. Do not weaken
the evaluator or redefine the task to protect Fourfold. Retain the negative
evidence and propose an Iron Plan amendment if a plan-level prior must change.

## Lifecycle and non-promotion

The packet expires at `2026-10-31T23:59:59Z` or after 26 candidate evaluations,
whichever occurs first. Expiry stops new attempts; it does not erase evidence.

No external repository was cloned to create this packet. This packet authorizes
no clone, network call, branch, push, issue, PR, merge, nomination, or
promotion. A run requires a separately recorded owner decision and green Gate-0
effect prerequisites. Experiment candidates are archived for inspection only.

Iron Plan: EXPERIMENT

Iron Gate: 0

Evidence: frozen source/submodule/license URLs, observed real 0.15.1 failure with independent tomllib semantics, and a pre-registered non-promoting evaluation protocol.
