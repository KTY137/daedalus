# G0-CI-01 — Canonical System-CI Consolidation

## Packet identity

- Plan classification: **ALIGNED**
- Active delivery gate: **Gate 0**
- Exact parent revision:
  `4b9dae0c4bce519f794d87474c62e1a13005cded`
- Parent packet: `G0-RPT-08D`
- Candidate branch: `codex/g0-ci-consolidation-20260825`
- Packet owner: **Codex implementation lane**; merge, promotion, release, and
  Gate decisions remain repository-owner decisions.
- Primary claim: a change to current `main` has one least-privilege,
  fresh-environment test/build definition that does not depend on the retired
  Iron Plan guard.
- Promotion, merge, release, and Gate transition: not requested.

## Reproduced baseline

At the exact parent revision:

- `.github/workflows` contained 98 workflows, 10,905 lines, and 350 jobs;
- 94 workflows called the intentionally deleted
  `tools/iron_plan_guard.py` 170 times;
- no pull-request or push branch filter named current `main`;
- 95 workflows referenced at least one missing local input;
- the fan-out contained 84 full-suite jobs and 90 wheel jobs;
- 266 existing test files were named 1,007 times;
- 66 existing mutation runners were invoked 70 times;
- full local collection found 8,893 tests in 74.52 seconds on Windows,
  Python 3.10.11.

Collection was not a green-suite claim. An exact Windows/Python 3.10/hash-seed
123456 candidate run was stopped after the following three failures had been
reproduced independently on both this candidate and the exact parent:

- s02_types/test_external_corpora.py compares the moving live kernel corpus
  with the frozen 2026-08-18 measurement (4,592 != 4,203 functions);
- s07_bm25/test_bm25_index.py still asks the live tools/ tree to rank the
  owner-retired iron_plan_guard.py first;
- the retained BM25 known miss moved from rank 3/at most 5 to rank 6 as the
  live experiment corpus grew.

These are pre-existing experiment-baseline defects, not failures introduced by
the workflow consolidation. They remain release-blocking for an automatic
full-suite CI and require a separate work packet that binds the published
measurements to their historical source trees. This packet does not rewrite
historical numbers, delete the negative result, or weaken its rank ceiling.

A later complete run of the retained fault/predecessor scope found one further
parent blocker: 899 tests passed, two skipped, and
`test_the_offload_door_lease_dominates_its_bench_write` failed because the
inventory position `(651, 10)` was absent from the calculated dominance set.
The candidate and exact parent are byte-identical across that test, offload
implementation, inventory scanner, and evidence generator, so this packet did
not introduce the defect. Its semantic classification and repair belong to a
separate effect-boundary work packet.

The four workflows without the retired guard were
`fourfold-polyglot-probe.yml`, `fourfold-v2.yml`,
`g0-canonical-fault-matrix-contract.yml`, and
`g0-promotion-receipt-authority.yml`. The polyglot probe supplies external
corpus capability not subsumed by a repository pytest run. Both the canonical
fault-matrix and promotion-receipt definitions also contained mutation runners
outside pytest. This packet deliberately retains only the canonical
fault-matrix as a manual mutation lane; the promotion-receipt runner remains
executable in the repository and its old invocation is retained in the archive,
but this packet does not claim to execute it.

The owner retirement is commit
`79825b5752de4666b2163f3a31c8a8b0fd887180` and amendment record 7. Restoring
the guard would contradict that decision and the current constitution.

## Consolidation decision

Three workflow files remain active:

1. `.github/workflows/ci.yml` is the only automatic workflow. It runs for
   pull requests into `main`, pushes to `main`, and manual dispatch.
2. `.github/workflows/g0-canonical-fault-matrix-contract.yml` remains
   manual-only because its bounded mutation campaign is not executed by
   pytest. Its redundant full-suite and packaging jobs are removed because
   the automatic CI owns those checks.
3. `.github/workflows/fourfold-polyglot-probe.yml` remains manual-only
   because it clones four external repositories and exercises optional
   polyglot/ROOT dependencies. Its weekly schedule is explicitly paused.

The other 96 packet-scoped definitions move unchanged to
`docs/archive/ci-workflows/2026-08-25/`. They remain byte-retained historical
and negative evidence, including dead guard calls and stale targets.
`BASE_WORKFLOW_MANIFEST.tsv` binds every original path to its parent-tree Git
blob and current disposition.

This is consolidation, not a claim that full pytest replaces every historical
adversarial campaign. The 66 mutation runners remain in the repository and
their old invocation definitions remain in the archive.

The fault-matrix jobs are individually bounded at 15 minutes (focused cells),
20 minutes (mutation), and 30 minutes (predecessor regression), with at most
four focused cells running concurrently. Their minimal Python tooling is
exactly pinned. The polyglot jobs retain their 10/40-minute limits and now pin
their pip/pytest tooling as well.

## Exact in-scope paths

- `.github/workflows/ci.yml`
- `.github/workflows/fourfold-polyglot-probe.yml`
- `.github/workflows/g0-canonical-fault-matrix-contract.yml`
- the 96 base workflows moved to
  `docs/archive/ci-workflows/2026-08-25/`
- `docs/archive/ci-workflows/2026-08-25/README.md`
- `docs/archive/ci-workflows/2026-08-25/BASE_WORKFLOW_MANIFEST.tsv`
- `docs/work-packets/G0-CI-01_CANONICAL_SYSTEM_CI_CONSOLIDATION.md`
- `pyproject.toml`
- `tests/test_ci_workflow_contract.py`

## Forbidden paths and authority

- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`
- `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`
- every runtime, policy, evaluator, ledger, admission, trust, release,
  OwnerApproval, promotion, and merge implementation
- GitHub account billing, repository visibility, and branch protection
- any replacement plan guard, hook, or advertised security guarantee

The workflow token has only `contents: read`. Checkout credentials are not
persisted. No workflow receives secrets or contains publish, deploy, push,
merge, promotion, or release commands.

## Automatic CI contract

The cost-bounded matrix is deliberately not the Cartesian product of every
supported dimension:

| OS | Python | hash seed | extra product checks |
| --- | --- | --- | --- |
| Ubuntu latest | 3.12 | 0 | sdist/wheel, isolated import, web, VS Code |
| Windows latest | 3.10 | 123456 | none |

Both cells:

- install the exact declared test dependencies;
- compile `daedalus`, `tests`, `scripts`, and `tools`;
- run the complete repository pytest suite with the asyncio and Hypothesis
  plugins explicitly loaded;
- retain JUnit output and the resolved package set for 14 days;
- refuse tracked checkout mutation.

On Ubuntu the complete suite also executes two Docker-marked container fault
integration tests when the runner Docker daemon is available. Their image is
digest-pinned and each driver has a 600-second timeout, but they still perform
an external Docker Hub pull and real container effects. Windows skips those
tests.

The Ubuntu cell additionally:

- builds an sdist and wheel and runs `twine check`;
- installs the wheel without dependencies outside the checkout;
- imports the canonical packages and reads every declared runtime resource;
- executes `daedalus --help`;
- installs locked web and VS Code dependencies;
- runs the deterministic motion test, rebuilds the web app, and refuses a
  tracked `apps/web/dist` delta while ignoring only cross-platform CR bytes
  at line endings;
- syntax-checks and packages the VS Code extension.

Action references are exact commit pins for checkout v4, setup-python v5,
setup-node v4, and upload-artifact v4. Uploaded artifacts are short-lived
diagnostics and build products. They are not a canonical EvidencePacket,
GateEvidenceIndex, Trust Bundle, Gate-close receipt, or release authorization.

## Dependency and package repair

The prior `test` extra declared only Hypothesis even though the suite imports
pytest, pytest-asyncio, jsonschema, and PyYAML-backed checks. The packet pins
those test dependencies so a fresh runner receives the environment the suite
actually requires.

The wheel smoke test also makes previously implicit runtime resources explicit:

- `daedalus.eval/*.json`;
- `daedalus.gui/probe.js`;
- `daedalus.providers/personas.json`;
- the already-declared retained Kairos source.

This changes packaging metadata only. It does not make those resources an
authority source beyond their existing runtime use.

## Acceptance and refusal matrix

- exactly three active workflow YAML files exist;
- exactly one active workflow has automatic triggers;
- that workflow targets only current `main` for pull requests and pushes,
  has no path filter, and is manually dispatchable;
- both specialized workflows are manual-only;
- no active workflow mentions `tools/iron_plan_guard.py`;
- every active external action is pinned to a 40-hex commit;
- every active workflow has read-only contents permission and no write token
  permission;
- the manifest has 98 unique original rows: 96 archived and two retained;
- every manifest base SHA is checked against the exact parent tree;
- every archived destination is checked through Git's path-aware blob
  normalization against that parent SHA, and the archive contains no
  unmanifested workflow;
- valid-looking wrong-SHA, swapped-SHA, wrong-path, and semantic-byte mutants
  are killed by the contract tests;
- all local test/script/config inputs named by the two manual workflows exist;
- the declared matrix is exactly the two cells above;
- the full suite, wheel isolation, resource checks, frontend build, extension
  build, artifact retention, and no-diff checks remain present;
- removal of one required trigger, action pin, manifest row, package resource,
  or explicit dependency kills the CI contract test.

## Budgets and honest non-claims

- Automatic budget: two full-suite cells, one Python product build, one web
  build, one extension build, and up to two digest-pinned Docker container
  integration tests on Ubuntu; timeout 180 minutes per cell.
- Manual fault budget: eight focused cells at 15 minutes with
  `max-parallel: 4`, one 20-minute mutation job, and one 30-minute predecessor
  job. There is no duplicate full-suite or packaging job in that workflow.
- No macOS, Python 3.11/3.13+, browser E2E, Rust backend, live provider,
  full 2×2×2 matrix, or all-mutation claim.
- The polyglot external clone/probe and canonical fault mutation lane require
  explicit manual dispatch.
- The archived 66 mutation campaigns remain retained but are not represented
  as executed by this packet.
- Python's declared `>=3.10` range remains broader than this measured matrix;
  changing product support is a separate owner decision.

Fresh locked frontend installs also retained the following negative evidence:

- `apps/web`: one high-severity transitive `nanoid` advisory;
- `vscode-agent-env`: four high-severity transitive advisories in
  `brace-expansion`, `fast-uri`, `js-yaml`, and `undici`.

All reported `npm audit` findings currently have an available dependency
update. This packet does not claim dependency-security acceptance and does not
silently widen into a lockfile-remediation packet.

The prior suite triage measured roughly 5,288 seconds (88 minutes) before the
current tree growth. A later local run under concurrent load reached only 62%
after roughly 72 minutes. The 180-minute job timeout is therefore a hard cost
ceiling, not a demonstrated runtime margin. Exact GitHub wall time remains
unverified until billing is unblocked; a timeout is red evidence, not a reason
to omit or silently deselect slow tests.

## Measured candidate evidence

On the frozen candidate source, before commit:

- CI workflow contract: 10 passed;
- actionlint 1.7.12: zero findings across all three active workflows;
- compileall over production, tests, scripts, and tools: passed;
- canonical focused fault tests: 24 passed;
- bounded fault campaign: self-probe passed and 19/19 exact mutants killed;
- predecessor/receipt scope: 899 passed, two skipped, and the one parent offload
  dominance defect documented above failed in 723.99 seconds;
- Python sdist/wheel build and twine 7.0.0 check: passed;
- isolated no-dependency wheel install outside the checkout: all six declared
  resources, package imports, and `daedalus --help` passed;
- web motion suite: 116/116 passed; the Vite build matched tracked output after
  ignoring only CR bytes at line endings;
- VS Code extension check and VSIX packaging: passed;
- all 96 archive moves are Git R100 moves and all 98 parent manifest bindings
  match their exact parent blobs.

The full candidate suite is not recorded as green. One run was intentionally
stopped after the first three reproducible Forest failures; the complete
specialized predecessor scope later exposed the fourth known parent defect.
These negative results are retained rather than converted into a pass.

## External System-CI blocker

GitHub Actions run `32687059768` at remote `main` revision
`0351a0bfdd4d2fc633048fd1af9b208b70fab064` failed before Step 1 in all five
jobs. The Jobs API returned `steps=[]`, `runner_id=0`, and the check
annotation:

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased.

Actions are repository-enabled and default workflow permissions are read-only.
Branch-protection and ruleset APIs return HTTP 403 for this private repository
unless the account is upgraded or the repository made public.

Therefore this packet can repair and locally validate the source definition,
but exact-head System CI remains **UNVERIFIED** until the owner resolves billing
and a pushed candidate executes real steps successfully. In addition, the
three separately documented historical experiment baselines and the separate
offload dominance defect must be repaired before the combined candidate can
claim a green full suite.
The billing failure is not a product failure, and a zero-step run is never
green evidence.

## Verification plan

Local acceptance:

    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    $env:PYTHONHASHSEED = "123456"
    python -m pytest -q -p no:cacheprovider tests/test_ci_workflow_contract.py
    python -m compileall -q daedalus tests scripts tools
    python -m pytest -q -ra -p pytest_asyncio.plugin -p _hypothesis_pytestplugin
    python -m build --sdist --wheel
    python -m twine check dist/*
    npm ci --prefix apps/web
    npm --prefix apps/web run test:motion
    npm --prefix apps/web run build
    git diff --exit-code --ignore-cr-at-eol -- apps/web/dist
    npm ci --prefix vscode-agent-env
    npm --prefix vscode-agent-env run check
    npm --prefix vscode-agent-env run package

Workflow syntax is checked independently with actionlint. The complete suite
and builds must be run from a frozen tree; any earlier run spanning a source
change is retained as invalid measurement rather than counted.

The current packet may be committed as an honest source-definition repair, but
its combined automatic CI acceptance remains red on the four known parent
defects above. Later baseline-binding and effect-boundary packets must rerun the
complete frozen suite; a partial run or a collection-only result cannot close
this condition.

System acceptance after the external unblock requires a real exact-head run of
both automatic matrix cells, non-empty steps/logs, green pytest/build results,
and retained diagnostic artifacts. Manual fault/polyglot results remain
separate evidence.

## Rollback

Before owner merge, deleting this isolated branch removes the candidate without
touching `main`. After merge, revert the consolidation commit to restore the
prior active definitions. The 96 retired definitions are byte-retained in the
archive; the two modified active definitions retain their original bytes in
Git history.
Restoring the retired guard or silently reactivating all 350 historical jobs is
not rollback.

No automatic merge, promotion, owner approval, release, or Gate transition is
authorized.
