# Census shard 6/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/progress.py|class|UnitProgress|Dataclass representing current knowledge about one work unit.
daedalus/progress.py|class|BatchProgress|(Not fully defined in excerpt) probably dataclass for batch status.
daedalus/progress.py|function|snapshot|Builds a fresh UnitProgress for a unit.
daedalus/progress.py|function|batch_snapshot|Builds a BatchProgress for a batch of units.
daedalus/progress.py|function|render|Returns a human-readable string for a UnitProgress.
daedalus/progress.py|function|render_batch|Returns a human-readable string for a BatchProgress.
daedalus/progress.py|function|to_payload|Converts a UnitProgress to a dict payload.
daedalus/progress.py|function|now_iso|Returns current UTC ISO timestamp string.
daedalus/progress.py|function|parse_iso|Parses ISO timestamp to epoch seconds.
daedalus/progress.py|function|format_age|Formats age in seconds to human string.
daedalus/progress.py|function|main|CLI entry point for querying progress.
daedalus/memory/projection_worker.py|constant|JOURNAL_ID|Stable identity of the journal this index is derived from.
daedalus/memory/projection_worker.py|constant|DEFAULT_DIMENSION|Output width of nomic-embed-text, used when no index exists and caller declared nothing.
daedalus/memory/projection_worker.py|constant|DEFAULT_BATCH_SIZE|Default batch size for embedding requests.
daedalus/memory/projection_worker.py|class|ProjectionWorkerError|Base class for refusals raised before any vector is written.
daedalus/memory/projection_worker.py|class|SpecConflictError|Declared spec disagrees with an index already in database.
daedalus/memory/projection_worker.py|class|JournalEntry|Represents one journal entry with line number, offsets, raw bytes, parsed record, and optional error.
daedalus/memory/projection_worker.py|class|WorkerReport|Report containing status, counts, and metadata after a projection run.
daedalus/memory/projection_worker.py|class|ProjectionWorker|Main worker class that moves the derived vector index forward to match the authoritative journal.
daedalus/memory/projection_worker.py|function|complete_prefix_end|Returns byte offset just past the last newline-terminated line in a journal file.
daedalus/memory/projection_worker.py|function|journal_position|Returns the journal's current position as a JournalPosition object, including content hash.
daedalus/memory/projection_worker.py|function|scan_journal|Reads complete lines from a journal start offset, returning a list of JournalEntry objects.
daedalus/memory/projection_worker.py|function|resolve_spec|Resolves embedding spec by picking index to write to without calling backend, handling conflicts.
Route this task to Claude or local Ollama.
daedalus/eval/mint.py|constant|MINT_CONFIRM_THRESHOLD|Number of independent confirmations before a minted task is taken out of quarantine
daedalus/eval/mint.py|constant|DEFAULT_MINT_STORE_PATH|Path to the persisted store for minted tasks
daedalus/eval/mint.py|constant|MUST_INCLUDE_CAP|Maximum number of must_include labels per task
daedalus/structcore/dss.py|constant|DSS_SCHEMA_VERSION|Defines schema version string for DSS.
daedalus/structcore/dss.py|constant|HIERARCHY_SCHEMA_VERSION|Defines schema version string for hierarchy.
daedalus/structcore/dss.py|constant|RECEIPT_SCHEMA_VERSION|Defines schema version string for receipt.
daedalus/structcore/dss.py|constant|REPOSITORY_NODE_ID|Identifies the root repository node in the hierarchy.
daedalus/structcore/dss.py|constant|FILE_NODE_KINDS|Set of forest node kinds that are considered files for selection and hierarchy.
daedalus/structcore/dss.py|class|HierarchyNode|Represents a node (repository, directory, file) in the DSS hierarchy.
daedalus/structcore/dss.py|class|ForestHierarchy|Represents the complete deterministic hierarchy of file paths.
daedalus/structcore/dss.py|function|build_forest_hierarchy|Builds a ForestHierarchy from a KnowledgeForest for file-kind nodes.
daedalus/structcore/dss.py|function|restrict_scores|Restricts file-level scores to all ancestor hierarchy nodes by summation.
daedalus/structcore/dss.py|class|Prolongation|Holds the result of score prolongation: selected and pruned nodes.
daedalus/structcore/dss.py|function|prolongate_scores|Projects restricted relevance down through at most branch_limit children per node.
daedalus/structcore/dss.py|class|TemporalEvidence|Represents a single piece of evidence for carrying a score across IDs.
daedalus/structcore/dss.py|class|TemporalCarry|Holds carried scores and evidence from previous forest state.
daedalus/structcore/dss.py|function|carry_temporal_scores|Carries previous scores via exact IDs or explicit rename mappings.
daedalus/structcore/dss.py|class|RelationChannel|Holds scores propagated through a single relation channel.
daedalus/structcore/dss.py|function|diffuse_relation_scores|Diffuses source scores along forest edges and hyperedges with decay.
daedalus/structcore/dss.py|constant|DEFAULT_RELATION_WEIGHTS|Default tuple of (relation, weight) pairs for score fusion.
daedalus/structcore/dss.py|class|DSSConfig|Configuration dataclass for DSS parameters (branch_limit, diffusion, weights).
tests/test_typegraph_forest.py|constant|REPO_ROOT|Root path of the repository.
tests/test_typegraph_forest.py|constant|FIXTURE|Path to typegraph test fixtures.
tests/test_typegraph_forest.py|constant|FILE_NODES|Count of file nodes in the fixture.
tests/test_typegraph_forest.py|constant|TYPE_NODES|Count of type nodes.
tests/test_typegraph_forest.py|constant|FIELD_NODES|Count of field nodes.
tests/test_typegraph_forest.py|constant|LAYER_COUNTS|Expected relation layer counts.
tests/test_typegraph_forest.py|constant|EMPTY_RELATIONS|Relations published empty.
tests/test_typegraph_forest.py|constant|FUNCTION_SOURCED|Relations sourced from functions.
tests/test_typegraph_forest.py|function|setUpModule|Set up test environment and temporary cache.
tests/test_typegraph_forest.py|function|tearDownModule|Restore environment and clean up cache.
tests/test_typegraph_forest.py|class|TheForestCarriesTheLayer|Tests that the type layer nodes and edges appear correctly.
tests/test_typegraph_forest.py|class|TheFileHalfDoesNotMove|Tests that file nodes, imports, and hyperedges remain unchanged.
tests/test_typegraph_forest.py|class|TheHierarchyIgnoresTypeNodes|Tests that hierarchy generation ignores type nodes.
tests/test_typegraph_forest.py|class|ATypeNodeCannotBePacked|Tests that type nodes cannot be used as context seeds.
tests/test_typegraph_forest.py|class|TheLensIsNotAChannel|Tests that type relations do not contribute to diffusion channels.
tests/test_typegraph_forest.py|class|TheBuildIsDeterministic|Tests that forest builds are deterministic and hash changes with type layer.
daedalus/offload.py|function|offload|Guarantees offloading work to free bench with policy enforcement and verification gate
tests/test_eval_mint.py|constant|GIT|Path to git binary used for tests
tests/test_eval_mint.py|class|MintFromCommitTest|Tests cross-file commit minting with mod.py and other.py
tests/test_eval_mint.py|class|MintFromLandedEditTest|Tests minting from uncommitted edits via offload.py seam
tests/test_eval_mint.py|class|MintFromDiffsScopeAndLabelTest|Tests pure-function _mint_from_diffs for scope and label rules
tests/test_eval_mint.py|class|ConfirmationCounterTest|Tests task tier promotion based on confirmation threshold
tests/test_eval_mint.py|class|MintStorePersistenceTest|Tests persistence of minted tasks to JSON store
tests/test_eval_mint.py|class|HarnessAllTasksLoadPathTest|Tests that minted tasks are loaded into all_tasks()
tests/test_killswitch.py|constant|LATCH_SLACK_S|Slack for latency measurement bound (0.5 s).
tests/test_killswitch.py|constant|GATE_STOP_BUDGET_S|Budget for gate stop latency (3.0 s).
tests/test_killswitch.py|function|test_allow_armed_switch_permits_work|Verifies that an armed switch allows work.
tests/test_killswitch.py|function|test_allow_watcher_does_not_trip_a_healthy_switch|Verifies watcher does not latch a healthy switch.
tests/test_killswitch.py|function|test_allow_gate_runs_to_completion_under_an_armed_switch|Verifies pytest runs to completion with an armed switch.
tests/test_killswitch.py|function|test_allow_arm_after_clear_works|Verifies re-arming after clear works.
tests/test_killswitch.py|function|test_stop_missing_permit|Verifies missing permit stops.
tests/test_killswitch.py|function|test_stop_empty_permit|Verifies empty permit stops.
tests/test_killswitch.py|function|test_stop_whitespace_only_permit|Verifies whitespace-only permit stops.
tests/test_killswitch.py|function|test_stop_any_token_that_is_not_exactly_RUN|Verifies any token other than RUN stops.
tests/test_killswitch.py|function|test_stop_permit_that_is_not_utf8|Verifies non-UTF-8 permit stops.
tests/test_killswitch.py|function|test_stop_permit_that_is_a_directory|Verifies directory permit stops.
tests/test_killswitch.py|function|test_stop_implausibly_large_permit|Verifies implausibly large permit stops.
tests/test_killswitch.py|function|test_stop_when_the_permit_cannot_be_read|Verifies unreadable permit stops.
tests/test_killswitch.py|function|test_stop_when_the_permit_cannot_be_stat_ed|Verifies unstatable permit stops.
tests/test_killswitch.py|function|test_stop_when_the_marker_cannot_be_examined|Verifies unexaminable marker stops.
tests/test_killswitch.py|function|test_stop_marker_alone_halts_even_with_a_valid_permit|Verifies marker stops even with valid permit.
tests/test_killswitch.py|function|test_stop_should_stop_never_raises|Verifies should_stop never raises.
tests/test_killswitch.py|function|test_stop_predicate_shapes_agree|Verifies predicate shapes agree.
tests/test_killswitch.py|function|test_stop_checkpoint_raises_loop_halted|Verifies checkpoint raises LoopHalted.
tests/test_killswitch.py|function|test_stop_does_not_lose_a_race_with_its_own_watcher|Verifies stop does not lose race with watcher.
tests/test_killswitch.py|function|test_stop_wins_against_a_reader_holding_the_permit_open|Verifies stop wins against open reader.
tests/test_killswitch.py|function|test_stop_is_loud_when_it_takes_no_effect|Verifies loud failure when stop has no effect.
tests/test_killswitch.py|function|test_stop_latch_survives_the_permit_being_restored|Verifies latch survives permit restoration.
tests/test_killswitch.py|function|test_stop_arm_refuses_to_undo_a_human_stop|Verifies arm fails after human stop.
tests/test_killswitch.py|function|test_stop_arm_force_is_the_deliberate_escape|Verifies arm(force=True) works after stop.
tests/test_killswitch.py|function|test_stop_switch_path_is_frozen_at_construction|Verifies switch path is frozen at construction.
tests/test_killswitch.py|function|test_default_control_dir_is_a_sibling_of_the_worktree_root|Verifies default control dir location.
tests/test_killswitch.py|function|test_latency_latch_within_one_poll_interval|Measures latch latency within poll interval.
tests/test_killswitch.py|function|test_latency_operator_cli_stops_from_another_terminal|Measures latency via CLI in another terminal.
tests/test_killswitch.py|function|test_latency_gate_child_tree_dies|Measures gate child tree death latency.
tests/test_gate_discrimination.py|constant|ROOT|Path to repository root.
tests/test_gate_discrimination.py|class|FakeSandbox|Stand-in for system_check.Sandbox with no git.
tests/test_gate_discrimination.py|function|scripted_gate_runner|Returns a fake gate runner with predetermined outcomes.
tests/test_gate_discrimination.py|class|CorpusDesignTests|Tests for corpus design invariants.
tests/test_gate_discrimination.py|class|ApplyMutationTests|Tests for apply/restore mechanics.
tests/test_gate_discrimination.py|class|RunCorpusTests|Tests for run_corpus orchestration.
tests/test_gate_discrimination.py|class|HeadOnlySandboxTests|Tests for HeadOnlySandbox.
tests/test_gate_discrimination.py|class|DefaultGateRunnerTests|Tests for default gate runner.
tests/test_gate_discrimination.py|class|ReceiptBootstrapContractTests|Tests for receipt/bootstrap contract.
tests/test_gate_discrimination.py|class|AnchorLinesTests|Tests for anchor line calculation.
tests/test_gate_discrimination.py|class|FilterByCoverageTests|Tests for coverage filtering.
tests/test_gate_containment.py|function|probe|Fixture that spawns contained child and returns parsed fields, canary, and log for later assertions.
tests/test_gate_containment.py|function|test_LOW_APPEND_THROUGH_THE_INHERITED_HANDLE_WORKS|Guarantees the contained child can append through its handle, verifying the allow side works.
tests/test_gate_containment.py|function|test_a_contained_pytest_gate_passes_a_real_worktree|Guarantees a real pytest run inside containment passes and capfd works.
tests/test_gate_containment.py|function|test_a_medium_integrity_log_target_is_REFUSED|Guarantees a Medium-integrity log target raises ContainmentUnavailable.
tests/test_gate_containment.py|function|test_a_low_labelled_log_target_is_ACCEPTED|Guarantees a Low-labelled log target is accepted as LowIntegrityLog.
tests/test_gate_containment.py|function|test_the_verified_target_cannot_be_SWAPPED_while_the_handle_is_open|Guarantees the log file cannot be renamed, deleted, or written while the handle is open.
tests/test_gate_containment.py|function|test_a_raw_handle_can_never_be_handed_to_the_spawner|Guarantees spawn_contained rejects non-LowIntegrityLog objects.
tests/test_gate_containment.py|function|test_a_handle_off_the_allowlist_is_INVISIBLE_to_the_child|Guarantees an inheritable handle not on the allowlist is invisible to the child (ERROR_INVALID_HANDLE).
tests/test_gate_containment.py|function|test_CONTROL_the_same_sentinel_IS_usable_without_the_allowlist|Guarantees the attack works without the allowlist, confirming the guard's necessity.
tests/test_gate_containment.py|function|test_READ_through_the_inherited_handle_fails|Guarantees the child cannot read from its log handle (REFUSED:5).
tests/test_gate_containment.py|function|test_TRUNCATE_through_the_inherited_handle_fails|Guarantees the child cannot truncate its log handle (REFUSED:5).
tests/test_gate_containment.py|function|test_DELETE_and_REPLACE_of_the_log_by_path_both_fail|Guarantees the child cannot delete, rename, or reopen-write the log file by path.
tests/test_gate_containment.py|function|test_CONTROL_read_and_truncate_work_on_a_fully_opened_handle|Guarantees that the refusal is due to rights, not file properties.
tests/test_gate_containment.py|function|test_the_shipped_mask_is_exactly_append_read_attributes_synchronize|Guarantees the granted_access mask is exactly 0x00100084 and all forbidden bits are absent.
tests/test_gate_containment.py|function|test_a_CHATTY_contained_gate_completes_instead_of_deadlocking|Guarantees a chatty contained gate finishes without deadlock, even with >64KB output.
tests/test_gate_containment.py|function|test_a_chatty_contained_gate_is_still_CANCELLABLE|Guarantees cancellation works on a chatty contained gate, with elapsed time <60s.
tests/test_gate_containment.py|function|test_CONTROL_an_undrained_PIPE_wedges_the_same_chatty_writer|Guarantees that a pipe (undrained) deadlocks with a chatty writer, justifying file redirect.
tests/test_mapping_cli.py|constant|FIXTURE_SHA|Provides a fixed SHA for testing git stamp.
tests/test_mapping_cli.py|constant|FIXTURE_BRANCH|Provides a fixed branch name for testing git stamp.
tests/test_mapping_cli.py|constant|BASE|Defines a minimal source tree structure for test fixtures.
tests/test_mapping_cli.py|constant|NARRATIVE|Provides a realistic narrative markdown for test fixtures.
tests/test_mapping_cli.py|function|mk|Creates directory structure and writes files for a test repo.
tests/test_mapping_cli.py|function|fake_git|Creates a minimal .git directory with HEAD and a single ref for testing.
tests/test_mapping_cli.py|function|repo|Pytest fixture that sets up a sandbox repo with narrative and git.
tests/test_mapping_cli.py|function|run|Invokes render.main with --repo and --no-git, returning exit code.
tests/test_mapping_cli.py|function|snapshot|Returns the path to the snapshot file in the repo.
tests/test_mapping_cli.py|function|page|Returns the content of the generated map HTML page.
tests/test_mapping_cli.py|function|listing|Returns a set of all file paths relative to the repo root.
tests/test_mapping_cli.py|function|test_json_is_parseable_and_carries_both_halves|Verifies --json output has schema, counts, narrative presence, and gate.
tests/test_mapping_cli.py|function|test_json_writes_nothing|Verifies --json does not create any new files or modify the repo.
tests/test_mapping_cli.py|function|test_json_counts_agree_with_the_module_list|Verifies module counts in JSON match the enumerated list per classification.
tests/test_mapping_cli.py|function|test_check_without_a_baseline_fails_and_says_so|Verifies --check exits 1 with error message when no baseline snapshot exists.
tests/test_mapping_cli.py|function|test_check_is_clean_immediately_after_a_write|Verifies --check exits 0 after a successful map run.
tests/test_mapping_cli.py|function|test_check_exits_non_zero_on_unaccepted_new_island|Verifies --check exits 1 when a new unreached module appears.
tests/test_mapping_cli.py|function|test_check_writes_nothing_even_when_drift_exists|Verifies --check does not modify snapshot file even when drift is detected.
tests/test_mapping_cli.py|function|test_check_passes_once_the_island_is_accepted|Verifies --check exits 0 after accepting a new island via --accept.
tests/test_mapping_cli.py|function|test_accept_refuses_a_reason_that_is_not_one|Verifies --accept rejects a reason not in the allowed vocabulary.
tests/test_mapping_cli.py|function|test_accept_refuses_a_horizon_beyond_the_cap|Verifies --accept rejects an until date beyond the allowed limit.
tests/test_mapping_cli.py|function|test_accept_does_not_re_baseline_unrelated_drift|Verifies accepting one island does not automatically accept others.
tests/test_mapping_cli.py|function|test_accept_without_a_snapshot_refuses|Verifies --accept exits 1 if no snapshot exists yet.

## DEPENDS

DEPENDS|tests/test_killswitch.py|daedalus.spine.cancel
DEPENDS|tests/test_killswitch.py|daedalus.spine.killswitch
DEPENDS|tests/test_killswitch.py|daedalus.kairos.worktree
DEPENDS|tests/test_gate_discrimination.py|gate_discrimination
DEPENDS|tests/test_gate_discrimination.py|daedalus.spine.bootstrap
DEPENDS|tests/test_gate_discrimination.py|daedalus.spine.attempt
DEPENDS|tests/test_gate_containment.py|daedalus.spine.containment
DEPENDS|tests/test_gate_containment.py|daedalus.spine.attempt
DEPENDS|tests/test_mapping_cli.py|daedalus.mapping.drift
DEPENDS|tests/test_mapping_cli.py|daedalus.mapping.render
DEPENDS|tests/test_mapping_cli.py|pytest
DEPENDS|tests/test_mapping_cli.py|json
DEPENDS|tests/test_mapping_cli.py|re
DEPENDS|tests/test_mapping_cli.py|shutil
DEPENDS|tests/test_mapping_cli.py|subprocess
DEPENDS|tests/test_mapping_cli.py|pathlib.Path
DEPENDS|tests/test_typegraph_regression.py|daedalus.context_plan
DEPENDS|tests/test_typegraph_regression.py|daedalus.structcore.clones
DEPENDS|tests/test_typegraph_regression.py|daedalus.structcore.index
DEPENDS|tests/test_typegraph_regression.py|daedalus.structcore.languages
DEPENDS|tests/test_typegraph_regression.py|daedalus.structcore.parse
DEPENDS|daedalus/spine/ledger.py|daedalus.spine.envelope
DEPENDS|daedalus/mapping/spectral.py|daedalus.mapping.inventory
DEPENDS|daedalus/memstore.py|daedalus/sensitivity (secret_floor_rule)
DEPENDS|daedalus/eval/graph_delta.py|structcore.graph
DEPENDS|daedalus/eval/graph_delta.py|structcore.parse
DEPENDS|daedalus/eval/graph_delta.py|structcore.languages
DEPENDS|daedalus/eval/graph_delta.py|structcore.artifacts
DEPENDS|daedalus/structcore/slice.py|markdown_mod (daedalus/structcore/markdown.py)
DEPENDS|daedalus/structcore/slice.py|build_index, resolution_context (daedalus/structcore/index.py)
DEPENDS|daedalus/structcore/slice.py|doc_spec_for, spec_for (daedalus/structcore/languages.py)
DEPENDS|daedalus/structcore/slice.py|extract_units (daedalus/structcore/parse.py)
DEPENDS|daedalus/structcore/slice.py|count_tokens (daedalus/structcore/tokens.py)
DEPENDS|daedalus/structcore/slice.py|slice_egress_rule (daedalus/sensitivity/__init__.py)

## WRITES

WRITES|daedalus/progress.py|runs/progress/events.jsonl
WRITES|daedalus/memory/projection_worker.py|vector_index.sqlite
WRITES|tests/test_typegraph_forest.py|temporary cache directory (via DAEDALUS_CACHE_DIR)
WRITES|tests/test_mapping_cli.py|tmp_path (test sandbox)
WRITES|tests/test_typegraph_regression.py|<tmpdir>/tgreg-cache-*
WRITES|tests/test_typegraph_regression.py|<tmpdir>/tgreg-tree-*

## READS

READS|tests/test_typegraph_forest.py|tests/fixtures/typegraph (via FIXTURE)
READS|daedalus/offload.py|repo files via _content_hash, _repo_snapshot, _scoped_snapshot
READS|daedalus/offload.py|environment variables OLLAMA_HOST, OFFLOAD_SLICE_TOKENS, DAEDALUS_AUTO_MINT
READS|tests/test_killswitch.py|The killswitch file path via Path operations.
READS|tests/test_gate_discrimination.py|ROOT/tools/gate_discrimination.py
READS|tests/test_gate_discrimination.py|ROOT
READS|tests/test_mapping_cli.py|repo fixture files
READS|tests/test_typegraph_regression.py|tests/fixtures/typegraph/
READS|tests/test_typegraph_regression.py|<tmpdir>/tgreg-tree-* models.py, clone_a.py, clone_b.py, usage.py
READS|daedalus/spine/ledger.py|SQLite database at self.path

## CLAIMS

CLAIMS|tests/test_mapping_cli.py|Module docstring: "--json and --check write NOTHING"
CLAIMS|tests/test_mapping_cli.py|Module docstring: "--check exits non-zero on unaccepted drift and zero when clean"
CLAIMS|tests/test_mapping_cli.py|Module docstring: "The page is self-contained: no external src/href"
CLAIMS|tests/test_mapping_cli.py|Module docstring: "A MISSING narrative renders every hand-written section as explicitly ABSENT"
CLAIMS|tests/test_typegraph_regression.py|The plan calls these non-negotiable, and they are the only tests in the suite whose job is to fail when a FUTURE change breaks the foundation.
CLAIMS|tests/test_typegraph_regression.py|T1 turns that accident into a guarded invariant.
CLAIMS|tests/test_typegraph_regression.py|T2 ensures no type or field name enters defs_by_file.
CLAIMS|tests/test_typegraph_regression.py|T3 ensures BM25 ranking is not silently corrupted by extra type names.
CLAIMS|daedalus/spine/ledger.py|Intent before effect: record_intent commits before the external effect, so crash window is only for effects without identifiable keys.
CLAIMS|daedalus/spine/ledger.py|Append-only in spirit: rows are never updated, only appended events.
CLAIMS|daedalus/spine/ledger.py|Double resolution is rejected (IntentAlreadyResolved), not silently absorbed.
CLAIMS|daedalus/mapping/spectral.py|'This module produces MEASUREMENTS ABOUT A PARTITION WE ALREADY DECLARED (the package layout on disk)'
CLAIMS|daedalus/mapping/spectral.py|'No graph is built here. graph_from_reach is an adapter over reach.analyse, not a second walker.'
CLAIMS|daedalus/mapping/spectral.py|'Nothing here returns an exit code, blocks a lane, moves a picker band, or decides anything.'
CLAIMS|daedalus/mapping/spectral.py|'Laplacian spectral theory as used here is defined for undirected graphs.'
CLAIMS|daedalus/mapping/spectral.py|'boundary_agreement ~1.0 means a REAL SEAM, ~0.5 means a FALSE WALL'
CLAIMS|daedalus/mapping/spectral.py|'modularity Q >= 0.3 with clear lift means real structure, lift <= 0 means filing not architecture'
CLAIMS|daedalus/mapping/spectral.py|'leak_rate >0.8 means a PASS-THROUGH package'
CLAIMS|daedalus/mapping/spectral.py|'confident is the honest brake: it is False when the winning gap is not meaningfully larger than the runner-up'
CLAIMS|daedalus/memstore.py|The canonical store is an APPEND-ONLY, HASH-CHAINED JSONL file at memory/ledger.local.jsonl. It is fail-loud, human-diffable, and tamper-evident.
CLAIMS|daedalus/memstore.py|If the secret floor fires, the entry is REFUSED (never written) and a redacted gate_outcome entry naming only the rule is appended instead.
CLAIMS|daedalus/eval/graph_delta.py|'The claim under test here is that the layered graph carries a second, independent signal: For a candidate patch, does the DELTA IN THE GRAPH carry information about the patch that the test suite does not — available before the tests run, at negligible cost?'
CLAIMS|daedalus/structcore/slice.py|_whole_repo_tokens: 'The fallback survives for index dicts that predate the field... Degraded is allowed; degraded-and-silent is not, hence the returned flag'
CLAIMS|daedalus/structcore/slice.py|_skeleton: 'the result is never larger than the raw document' (for documents)
CLAIMS|daedalus/structcore/slice.py|semantic_slice: 'The FOCUS GATE (the floor scan of the FULL focus text and its fail-closed refusal) runs FIRST and IDENTICALLY in both modes -- omitting the body never skips the gate, so a secret-bearing focus is refused either way.'
CLAIMS|tests/test_generated_inventory.py|Integrity is not freshness (module docstring)
CLAIMS|tests/test_generated_inventory.py|Two builds over one tree are byte identical (test_two_builds_over_one_tree_are_byte_identical)
CLAIMS|tests/test_generated_inventory.py|Editing a derived field breaks the digest (test_editing_a_derived_field_breaks_the_digest)
CLAIMS|tests/test_generated_inventory.py|Editing a human field does not break the digest (test_editing_a_human_field_does_not_break_the_digest)
CLAIMS|tests/test_generated_inventory.py|An annotation cannot set a status (test_an_annotation_cannot_set_a_status)
CLAIMS|tests/test_generated_inventory.py|No hand-written rationale is lost after harvest (test_no_hand_written_rationale_is_lost)
CLAIMS|tests/test_generated_inventory.py|A second harvest is idempotent (test_a_second_harvest_is_idempotent)

## UNWIRED

UNWIRED|daedalus/core.py|_gov_discrimination (private function not called within visible portion of core.py)
UNWIRED|daedalus/core.py|_gov_write_confinement (private function not called within visible portion of core.py)
UNWIRED|daedalus/skills.py|Constant SPEC_URL is defined and exported but not referenced within this file.
UNWIRED|daedalus/skills.py|Constant SPEC_COMMIT is defined and exported but not referenced within this file.
UNWIRED|daedalus/skills.py|Constant SPEC_BLOB_SHA is defined and exported but not referenced within this file.
UNWIRED|daedalus/skills.py|Constant SPEC_SHA256 is defined and exported but not referenced within this file.
UNWIRED|daedalus/skills.py|Constant SPEC_LICENCE is defined and exported but not referenced within this file.
UNWIRED|daedalus/gui_catalogue.py|SearchHit (listed in __all__ but no definition in visible excerpt)

## SMELL

SMELL|daedalus/provider_router.py|Duplication of provider mode logic across _mode, _deepseek_write_allowed, and inline in select_provider.
SMELL|daedalus/eval/mint.py|_mint_from_diffs handles scope, target selection, label extraction, filtering, and capping – multiple responsibilities in one function
SMELL|tests/test_typegraph_forest.py|Pinning logic for environment variables duplicated from test_typegraph_index.py (comment line)
SMELL|daedalus/offload.py|High number of internal dependencies and multiple responsibilities suggest potential god-object
SMELL|daedalus/offload.py|Duplication of snapshot logic (whole-repo and scoped) could be unified