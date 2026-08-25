# G0-CI-02B — Full-suite baseline reconciliation

**Plan classification: ALIGNED, Gate 0.** This packet repairs the canonical CI
baseline and one fail-open attempt projection. It does not amend the master
plan, create another kernel, merge or promote a candidate, or grant release
authority.

## Why this packet exists

After G0-CI-02 removed the three moving-history Forest failures, one complete
Windows/Python 3.10 suite run was held operationally frozen for 3,783.63
seconds and ended:

- 8,802 passed;
- 10 failed;
- 136 skipped;
- 9 expected failures;
- 2,158 subtests passed.

Only the result summary and diagnosis of that red run were retained. Its raw
console transcript and a contemporaneous start/end tree manifest were not
captured, so this packet does not present it as an independently verified
frozen-run receipt. The ten failures reduced to five causes; treating the ten
assertion sites independently would have hidden one false authorization:

- `tests/test_byte_pin_eol_durability.py::test_an_ordinary_module_is_not_eol_pinned`;
- `tests/test_eval_provenance.py::AWrongTreeIsCaught::test_a_directory_with_no_daedalus_fails`;
- `tests/test_generated_inventory.py::test_the_committed_inventory_is_generated_not_typed`;
- `tests/test_generated_inventory.py::test_the_committed_snapshot_records_a_usable_revision`;
- the `working`, `absent`, and `unknown` subtests of
  `tests/test_ikarus_shells.py::HandLivenessVocabularyTest::test_working_absent_unknown`;
- `tests/test_picker_outcome.py::test_every_attempt_state_the_writer_can_produce_is_classified`;
- `tests/test_web_api_loop.py::LoopRoutesAnswerTest::test_architecture_endpoint_returns_the_generated_counts`;
- `tests/test_worktree.py::test_git_is_told_long_paths_on_windows`.

The source reconstruction available after the fact is parent revision
`c7a1a7c5f20c4b82b4f051784ada94f1f382f439` plus exactly the following
G0-CI-02 overlays. This identifies the intended source bytes, but it does not
retroactively supply the missing run-boundary receipt. The SHA-256 of this
ordered LF-terminated manifest is
`f123828d5fe1191d030230ae49b718e7da9ad3803dd0bb0d87d6fb187f90373b`.

    bf3444c5bb95f08601e23e33cab6d9830b59928bfa41c3284650a981d37c80a6  docs/work-packets/G0-CI-02_HISTORICAL_FOREST_BASELINE_BINDING.md
    0213cc13170502527513f5f1cc086b2c6a0e2d033ec65738e723ec756d5be904  experiments/forest_v2/README.md
    267d6d126a69be88deb595b3282c73c7548ebf8b96b925ea47e8916afb0d9cbf  experiments/forest_v2/_historical_tree_fixture.py
    de52bbfff516233ef764a92bf1240871197e61c67943cdb7368a24471499daff  experiments/forest_v2/test_historical_tree_fixture.py
    abb65a3571450e86189bf244ac822ef136b718fe68faa270ad35dda90364e3b2  experiments/forest_v2/s02_types/test_external_corpora.py
    89de9b4a76bd6ee3c48155841e82f53c796a8a905fd2527337b71d8b9ab929b7  experiments/forest_v2/s07_bm25/test_bm25_index.py
    3a1a8b86a053b91a4fb37b437bdf4c3d0750759d01c998438940abd3877bf9f5  experiments/forest_v2/s09_eval/gitio.py
    6a92c75171790762bad51d850c257ee6d0f3300e38772ea73cea72d674f785d3  experiments/forest_v2/s09_eval/test_gitio.py

## Causes and disposition

### Historical generated-state corruption

Merge `9831ddaeaf2536d4e0abae54464151725d7698bb` combined mechanical lists
without regenerating their counts and digests. The architecture snapshot said
520 modules while its own list contained 521, retained a deleted
`daedalus/crew_hook.py`, and carried an invalid digest. The feature inventory
likewise contained duplicate, deleted, and archived mechanical entries under
an old count and digest.

The three canonical generated projections were regenerated together through
the existing central mapper, never hand-repaired:

    python -m daedalus.cli map

This updates `docs/architecture-map.html`, `docs/architecture-state.json`, and
`docs/FEATURE_INVENTORY.json` from one walk. Because the default mapper first
renders the detected drift and then re-baselines the JSON projections, a second
canonical pass is required after a corrupt baseline is repaired so the final
HTML also reports the new clean baseline. The reconciled state contains 545
non-test modules; both stored digests validate and both read-only fresh scans
match it.

### Stale or host-dependent tests

- `daedalus/router.py` legitimately joined the explicit Gate-1 byte-pinned
  closure, so it was no longer an ordinary negative EOL sentinel. Three
  deliberately nonexistent Python canaries now detect broad `* -text` or
  `*.py -text` rules without later becoming production subjects themselves.
- the Windows long-path test queried Git's aggregate configuration and mistook
  the owner's global `core.longpaths=true` for a write to the temporary repo.
  It now binds the exact `git -c core.longpaths=true ...` command and compares
  the complete local repository configuration before and after.
- the wrong-tree provenance test depended on whether Daedalus happened to be
  installed editable. It now supplies an explicit external shadow package and
  deterministically exercises the `OUTSIDE` refusal; the separate import-error
  path remains a distinct fail-closed condition.
- the Hand vocabulary test mocked the network probe below admission while
  naming a deliberately unapproved remote host. It now admits the synthetic
  endpoint explicitly before testing `working`, `absent`, and `unknown`.
  Dedicated health-admission tests continue to prove refusal happens before a
  socket call and reports `degraded`.

### `lease_refused` false allow

`TaskAttempt` had added a terminal pre-effect state for a replayed, expired,
revoked, or kill-switched Effect Lease. Two consumers had not classified it:

- the Picker treated it as unknown/in-flight and sank the task to the floor;
- more seriously, `canonicalise_attempt` minted `verdict="allow"`,
  `read_only=false`, and the task's writable paths after the successful
  execution start had been refused, before any worktree or runner was reached.

The canonical attempt projection now classifies `lease_refused` with the other
pre-effect denials. It contains a RuntimeManifest and a read-only, effect-free
deny PolicyDecision; no AttemptContract, EvidencePacket, or AttemptReceipt is
minted. The real single-lease replay test proves there is no successful lease
execution start and no worktree or runner is reached; the spine intent is
terminalized as failed. The Picker gives the terminal infrastructure refusal
the same mild, compounding policy as `storage_unavailable` and the CLI exits
red.

## Boundaries retained

- Models, candidates, and tests gain no evaluator or policy authority.
- No automatic merge, promotion, release, or approval path is added.
- The generated architecture state remains a representation of the source
  tree, not candidate identity.
- Failures and the historical corrupt merge remain named; regeneration does
  not rewrite Git history.
- GitHub-hosted execution remains independently blocked by the account billing
  condition recorded in G0-CI-01.

## Verification

    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    $env:PYTHONHASHSEED = "123456"
    python -m daedalus.cli map --check
    python -m daedalus.mapping.inventory --check
    python -m pytest -q -p no:cacheprovider tests/test_generated_inventory.py tests/test_web_api_loop.py tests/test_byte_pin_eol_durability.py tests/test_eval_provenance.py tests/test_health_admission.py tests/test_ikarus_shells.py tests/test_picker_outcome.py tests/test_spine_picker.py tests/test_worktree.py tests/kernel/test_attempt_lease.py
    python -m pytest -q -ra -p pytest_asyncio.plugin -p _hypothesis_pytestplugin

The complete-suite acceptance run must start from a tree with no ignored build
or runtime output and must span no edits. A focused pass or a run over a moving
tree is not full-suite acceptance.
