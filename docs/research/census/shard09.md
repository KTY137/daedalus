# Census shard 9/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/tools/vet.py|constant|UNSCANNABLE|Outcome indicating scan failure
daedalus/tools/vet.py|constant|MAX_FILE_BYTES|Maximum file size for scanning
daedalus/tools/vet.py|constant|MAX_FILES_SCANNED|Maximum number of files to scan
daedalus/tools/vet.py|constant|TEXT_SUFFIXES|Set of text file extensions
daedalus/tools/vet.py|constant|RULES|List of all scan rules
daedalus/tools/vet.py|constant|ALLOWANCE_PATH|Path to tool-allowances.json
daedalus/tools/vet.py|class|Finding|Represents a single scan finding with evidence
daedalus/tools/vet.py|class|Verdict|Aggregated scan result for a subject
daedalus/tools/vet.py|function|load_allowances|Loads allowances from file, returns dict and errors
daedalus/tools/vet.py|function|apply_allowances|Downgrades BLOCK findings to REVIEW based on allowances
daedalus/tools/vet.py|function|scan_text|Scans text for all rule matches deterministically
daedalus/tools/vet.py|function|vet_skill|Vets a Skill dataclass, returns Verdict
daedalus/tools/vet.py|function|vet_mcp_server|Vets an MCP server entry, returns Verdict
tests/test_ikarus_shells.py|constant|PROJECT|The project name used in tests: 'sunny_garden'
tests/test_ikarus_shells.py|class|RouteTest|Tests the _route function that routes intents to shells and handles capability decisions.
tests/test_ikarus_shells.py|class|ClassifyOnceTest|Tests that classify() runs exactly once per request and that streaming/blocking forms do not reclassify.
tests/test_ikarus_shells.py|class|StartFinalAgreementTest|Tests that start and final events agree on intent and shell, and that reconcile handles mismatches.
tests/test_ikarus_shells.py|class|ProviderFenceTest|Tests that the provider argument is ignored on the hand path and honored on the voice path.
tests/test_ikarus_shells.py|class|HandLivenessVocabularyTest|Tests that hand_state composes the one liveness predicate with five-word vocabulary and caching behavior.
tests/test_ikarus_shells.py|class|HandRefusesInWordsTest|Tests that confirmations to absent/unknown hands are refused in words, and proposals report cached state without new probes.
tests/test_ikarus_shells.py|class|GermanActRequestTest|Tests the round-trip of German act requests from classification through offer, confirmation, and enqueue.
tests/test_ikarus_shells.py|class|FalsePositiveDoesNotReachTheHandTest|Tests that 'does that make sense' is answered not queued, while real build requests still reach the hand.
tests/test_projection_worker.py|constant|REPO_ROOT|Root directory of the repository used for subprocess calls
tests/test_projection_worker.py|constant|MODEL|Fake model name for testing
tests/test_projection_worker.py|constant|DIMENSION|Default embedding dimension (8)
tests/test_projection_worker.py|class|FakeBackend|Counts calls and simulates embedding with deterministic vectors; supports failure injection
tests/test_projection_worker.py|class|ConstantBackend|Returns same unit vector for all texts, ensuring every event matches
tests/test_projection_worker.py|class|StubEmbedServer|Local HTTP server mimicking Ollama /api/embed for subprocess kill tests
tests/test_projection_worker.py|function|make_record|Creates a minimal journal record dict with given index and optional paths/summary
tests/test_projection_worker.py|function|write_journal|Writes list of records as JSONL to a file
tests/test_projection_worker.py|function|append_journal|Appends records to an existing JSONL file
tests/test_projection_worker.py|function|projection_rows|Returns (total rows, distinct source_hashes) from the vector store DB
tests/test_projection_worker.py|function|index_count|Returns count of rows in embedding_indexes table
tests/test_projection_worker.py|function|journal|Pytest fixture: creates a temporary journal with 6 records
tests/test_projection_worker.py|function|db|Pytest fixture: returns temporary path for vector store DB
tests/test_projection_worker.py|function|make_worker|Helper to create a ProjectionWorker with given journal, db, backend, and extra kwargs
tests/test_projection_worker.py|function|test_journal_position_ignores_a_partial_trailing_line|Verifies that journal_position ignores incomplete trailing lines
tests/test_projection_worker.py|function|test_scan_journal_reports_offsets_and_malformed_lines|Verifies scan_journal reports malformed lines and correct end_offset
tests/test_projection_worker.py|function|test_first_run_projects_every_entry_and_records_the_watermark|Verifies initial run projects all entries and records watermark in EventVectorStore
tests/test_projection_worker.py|function|test_second_run_over_an_unchanged_journal_does_no_embedding_work|Verifies incrementality: no embedding work on unchanged journal
tests/test_projection_worker.py|function|test_appending_to_the_journal_makes_a_search_report_stale_until_the_worker_runs|Verifies that appending makes search report stale until worker runs again
tests/test_projection_worker.py|function|test_the_worker_writes_the_index_the_context_planner_actually_searches|Verifies that worker writes index usable by latent_memory_seed_scores
tests/test_projection_worker.py|function|test_a_crash_between_embedding_and_the_watermark_neither_duplicates_nor_skips|Verifies crash resumption does not duplicate or skip entries
tests/test_projection_worker.py|function|test_a_killed_worker_process_resumes_without_loss_or_duplication|Verifies real subprocess kill leads to consistent state
tests/test_projection_worker.py|function|test_a_backend_outage_stops_and_leaves_a_watermark_for_what_landed|Verifies backend outage stops processing and watermark reflects what landed
tests/test_projection_worker.py|function|test_model_drift_refuses_and_contributes_no_vector|Verifies model drift is detected and no vectors are added
tests/test_projection_worker.py|function|test_a_rewritten_journal_is_refused_as_forked|Verifies rewritten journal with same length is detected via content hash
tests/test_projection_worker.py|function|test_a_truncated_journal_is_refused_as_forked|Verifies truncated journal is detected and refused
tests/test_projection_worker.py|function|test_a_partial_trailing_line_is_never_consumed|Verifies partial trailing line is not consumed and can be completed later
tests/test_projection_worker.py|function|test_a_malformed_line_is_reported_and_does_not_wedge_the_worker|Verifies malformed line is reported and worker continues
tests/test_projection_worker.py|function|test_blank_content_is_skipped_rather_than_embedded|Verifies blank summaries are skipped and not embedded
tests/test_projection_worker.py|function|test_dry_run_creates_no_database_and_calls_no_backend|Verifies dry run creates no DB and makes no embedding calls
tests/test_projection_worker.py|function|test_limit_bounds_the_run_and_leaves_it_resumable|Verifies limit bounds run and leaves watermark for resumption
tests/test_council_canary.py|class|PerfectLane|A fake lane that answers every probe correctly by reading the nonce from the prompt.
tests/test_council_canary.py|constant|NONCE|A test nonce string used in probe checks.
tests/test_council_canary.py|function|test_checker_accepts_the_correct_answer|Tests that each probe's checker accepts the correct answer.
tests/test_council_canary.py|function|test_checker_rejects_a_wrong_answer|Tests that each probe's checker rejects a wrong answer.
tests/test_council_canary.py|function|test_checker_rejects_an_empty_reply|Tests that each probe's checker rejects an empty reply.
tests/test_council_canary.py|function|test_expected_matches_the_checkers_notion_of_correct|Tests that expect matches the checker's notion of correct for all probes.
tests/test_council_canary.py|function|test_probe_bodies_are_synthetic_and_carry_no_repo_source|Ensures probe bodies contain no repo source markers.
tests/test_council_canary.py|function|test_head_truncated_reply_is_wrong_answer_not_ok|Tests that a head-truncated reply is scored as wrong_answer, not ok.
tests/test_council_canary.py|function|test_tail_truncated_reply_is_wrong_answer_not_ok|Tests that a tail-truncated reply is scored as wrong_answer, not ok.
tests/test_council_canary.py|function|test_arrival_truncation_grades_as_wrong_answer_through_the_runner|Tests that truncation is correctly scored through the runner.
tests/test_council_canary.py|function|test_a_totally_silent_ok_reply_is_not_ok|Tests that a silent reply is not scored as ok.
tests/test_council_canary.py|function|test_anchoring_copy_is_detected|Tests that anchoring detection works.
tests/test_council_canary.py|function|test_anchoring_decoy_wins_even_when_the_correct_word_also_appears|Tests that anchoring fails even if correct word appears.
tests/test_council_canary.py|function|test_anchoring_failure_is_a_quality_signal_not_a_liveness_failure|Tests that anchoring failure is quality, not liveness.
tests/test_council_canary.py|function|test_quality_regression_does_not_trip_the_exit_code|Tests that quality regression does not affect exit code.
tests/test_council_canary.py|function|test_unavailable_and_wrong_answer_are_distinct_statuses|Tests that unavailable and wrong_answer are distinct statuses.
tests/test_council_canary.py|function|test_unavailable_never_runs_the_checker_and_is_never_a_regression|Tests that unavailable skips checker and is never a regression.
tests/test_council_canary.py|function|test_status_vocabulary_is_closed|Tests that status vocabulary is closed.
tests/test_council_canary.py|function|test_transport_failures_map_onto_the_closed_vocabulary|Tests that transport failures map to closed status vocabulary.
tests/test_council_canary.py|function|test_a_raising_lane_becomes_error_not_a_traceback|Tests that a raising lane becomes error status.
tests/test_council_canary.py|function|test_hung_lane_times_out_and_the_other_lanes_still_complete|Tests that a hung lane times out and others complete.
tests/test_council_canary.py|function|test_every_scheduled_probe_is_reported_even_when_abandoned|Tests that every scheduled probe is reported even when abandoned.
tests/test_council_canary.py|function|test_probes_within_one_lane_run_sequentially|Tests that probes within a lane run sequentially.
tests/test_council_canary.py|function|test_max_parallel_bounds_lanes_in_flight|Tests that max_parallel bounds lanes in flight.
tests/test_council_canary.py|function|test_history_roundtrip_append_and_load|Tests history append and load roundtrip.
tests/test_council_canary.py|function|test_first_ever_run_has_no_median_and_is_not_a_regression|Tests first-ever run behavior.
tests/test_council_canary.py|function|test_corrupt_line_is_skipped_not_fatal|Tests that corrupt history lines are skipped.
tests/test_council_canary.py|function|test_regression_is_previously_passing_now_failing|Tests that regression detection works.
tests/test_council_canary.py|function|test_never_passing_lane_is_reported_but_does_not_trip_the_exit_code|Tests never-passing lane reporting and exit code.
tests/test_council_canary.py|function|test_latency_delta_and_slower_flag|Tests latency delta and slower flag.
tests/test_council_canary.py|function|test_slower_needs_both_a_ratio_and_an_absolute_jump|Tests that slower requires both ratio and absolute jump.
tests/test_council_canary.py|function|test_history_is_keyed_on_vendor_model_and_probe|Tests that history is keyed on vendor, model, probe.
tests/test_council_canary.py|function|test_trailing_window_bounds_the_comparison|Tests trailing window bounds.
tests/test_council_canary.py|function|test_history_record_carries_which_check_failed|Tests that history record carries failed_check.
tests/test_council_canary.py|function|test_dry_run_calls_nothing|Tests that dry run calls nothing.
tests/test_ui_governance.py|constant|REPO|Path to repository root.
tests/test_ui_governance.py|constant|EXTENSION_JS|Path to VS Code extension JS.
tests/test_ui_governance.py|constant|WEBAPP_SRC|Path to web app source directory.
tests/test_ui_governance.py|class|GovernanceShapeTests|Tests payload shape and required fields.
tests/test_ui_governance.py|class|NeverGreenByAccidentTests|Tests that states don't collapse to green.
tests/test_ui_governance.py|class|AgreesWithTheRealAuthorityTests|Tests surface matches spine.bootstrap.
tests/test_ui_governance.py|class|WriteConfinementIsMeasuredNotReadTests|Tests write confinement gate is measured via live predicate.
tests/test_ui_governance.py|class|BothSurfacesRenderItTests|Tests both UI surfaces reference the governance verdict.
tests/test_ui_governance.py|class|ApiServesTheSameVerdictTests|Tests API endpoint matches dashboard block.
daedalus/verifier.py|constant|DEFAULT_TEST_TIMEOUT_S|Default timeout for test suite to avoid wedged harness
daedalus/verifier.py|constant|INCONCLUSIVE_STATUSES|Frozenset of statuses that mean the check never reached a verdict, distinguishing inconclusive from fail
daedalus/verifier.py|class|VerifyResult|Dataclass aggregating check results with verdict and reason_note for routing
daedalus/verifier.py|function|prose_before_images|Convert writer's rollback backups to repo-relative before-images for prose verification
daedalus/verifier.py|function|verify|Main verification function: run schema, did_work, per-file checks, optional tests, return VerifyResult
daedalus/semantic_route.py|constant|EMBED_MODEL|Default embedding model name, overridable via OLLAMA_EMBED_MODEL env var.
daedalus/semantic_route.py|constant|LATENT|Mechanism tag: embedding route actually ran and chose the agent.
daedalus/semantic_route.py|constant|PATH_OWNED|Mechanism tag: path ownership forced keyword routing by design.
daedalus/semantic_route.py|constant|FALLBACK|Mechanism tag: latent route failed, keyword router provided agent.
daedalus/semantic_route.py|constant|EMBED_TIMEOUT_ENV|Environment variable for warm embedding timeout.
daedalus/semantic_route.py|constant|DEFAULT_EMBED_TIMEOUT_S|Default warm timeout (10s).
daedalus/semantic_route.py|constant|EMBED_COLD_TIMEOUT_ENV|Environment variable for cold embedding timeout.
daedalus/semantic_route.py|constant|DEFAULT_EMBED_COLD_TIMEOUT_S|Default cold timeout (60s).
daedalus/semantic_route.py|function|cache_clear|Clears memoized role vectors (for roster changes or testing).
daedalus/semantic_route.py|class|LatentRouteResult|Data class holding agent, mechanism, and failure details; provides explain() and to_dict().
daedalus/semantic_route.py|function|semantic_route_explained|Routes objective to nearest role using embeddings; returns LatentRouteResult with provenance.
daedalus/semantic_route.py|function|semantic_route|Back-compat wrapper; returns agent dict and logs which mechanism fired.
tests/test_bootstrap_receipt.py|class|ThePositiveControl|Ensures that a clean receipt at matching revision allows promotion, and abbreviated head still matches full sha.
tests/test_bootstrap_receipt.py|class|TheFourDocumentedRefusals|Tests that the four documented refusal conditions in gate_discrimination are enforced.
tests/test_bootstrap_receipt.py|class|TheRevisionClauseMustNotFailOpen|Ensures that when head is unreadable or empty, a stale receipt is refused (fail closed).
tests/test_bootstrap_receipt.py|class|TheKillRateMustBeBounded|Ensures that kill rates >100% or negative are refused.
tests/test_bootstrap_receipt.py|class|TheDriverIsSafeToImport|Ensures the driver module has no top-level side effects and main() is guarded by __name__ == "__main__".
tests/test_bootstrap_receipt.py|class|TheWorktreeConfigStampIsReversible|Ensures that the config stamp restores original bytes exactly even when the body raises.
tests/test_bootstrap_receipt.py|class|TheLeakCheckIsAttributable|Ensures that leak detection correctly distinguishes candidate paths from unrelated changes and detects hash changes.
tests/test_bootstrap_receipt.py|class|TheExternalTargetReceipt|Ensures that the external target receipt includes correct repo, storage, gate, and primary unchanged.
tests/test_typegraph_fixture.py|constant|REPO_ROOT|Root path of the repository.
tests/test_typegraph_fixture.py|constant|FIXTURE|Path to the synthetic fixture directory.
tests/test_typegraph_fixture.py|constant|FIXTURE_MODULES|Captured list of fixture module paths.
tests/test_typegraph_fixture.py|constant|DUPLICATION_BASELINE|Captured empty duplication output.
tests/test_typegraph_fixture.py|constant|IMPORT_EDGES_BASELINE|Captured import edges for the fixture.
tests/test_typegraph_fixture.py|constant|UNITS_BASELINE|Captured extract_units output per file.
tests/test_typegraph_fixture.py|constant|DEFS_BASELINE|Captured defs_by_file output per file.
tests/test_typegraph_fixture.py|constant|DECLARED_TYPE_NAMES|Frozenset of all type names declared in the fixture.
tests/test_typegraph_fixture.py|constant|DECLARED_FIELD_NAMES|Frozenset of all field names declared in the fixture.
tests/test_typegraph_fixture.py|class|FixtureCorpusIsIntact|unittest.TestCase: asserts the fixture repo shape and parses.
tests/test_typegraph_fixture.py|class|ExtractUnitsSeesOnlyFunctions|unittest.TestCase: asserts extract_units returns only functions (I1).
tests/test_typegraph_fixture.py|class|IndexBaseline|unittest.TestCase: asserts index output matches baselines (I4).
tests/test_typegraph_fixture.py|class|ResolverHoldsOnlyFunctions|unittest.TestCase: asserts resolver defs_by_file contains only functions (I2).
tests/test_typegraph_fixture.py|class|DeterminismAcrossProcesses|unittest.TestCase: asserts byte-identical output across hash seeds.
tests/test_latent_index_integrity.py|class|FakeEmbeddingBackend|Deterministic pure-function embedding backend for tests.
tests/test_latent_index_integrity.py|class|NudgedBackend|FakeEmbeddingBackend perturbed by epsilon to test drift tolerance.
tests/test_latent_index_integrity.py|class|UnavailableBackend|Mock backend that always raises EmbeddingUnavailableError.
tests/test_latent_index_integrity.py|function|test_moved_model_tag_without_revision_is_refused_not_silently_mixed|Test that index refuses vectors after model tag moves without revision pin.
tests/test_latent_index_integrity.py|function|test_pinned_revision_does_not_stop_a_second_host_but_the_anchor_does|Test that pinned revision does not partition by host but runtime anchor does.
tests/test_latent_index_integrity.py|function|test_two_specs_never_share_a_search|Test that distinct specs partition and do not fallback.
tests/test_latent_index_integrity.py|function|test_a_spec_that_lies_about_the_request_is_refused|Test that spec fields provider, dimension, projector_version are cross-checked.
tests/test_latent_index_integrity.py|function|test_spec_overrides_loose_kwargs_rather_than_cross_checking_them|Test that spec overrides kwargs, cross-check unreachable.
tests/test_latent_index_integrity.py|function|test_identity_anchor_tolerates_ordinary_service_jitter|Test that sub-tolerance noise passes.
tests/test_latent_index_integrity.py|function|test_drift_is_detected_across_a_reopen_not_just_within_one_process|Test drift detection across process reopen.
tests/test_latent_index_integrity.py|function|test_anchor_provenance_marks_retrofitted_indexes_as_trust_on_first_use|Test that adopted anchor provenance is reported.
tests/test_latent_index_integrity.py|function|test_unpinned_movable_tag_is_reported_as_unpinned|Test that model without model_revision is reported unpinned.
tests/test_latent_index_integrity.py|function|test_mixed_width_vectors_in_one_index_are_refused_not_broadcast|Test that dimension mismatch in index is refused.
tests/test_latent_index_integrity.py|function|test_cosine_refuses_mismatched_widths_directly|Test that _cosine raises ValueError on dimension mismatch.
tests/test_latent_index_integrity.py|function|test_backend_that_changes_output_width_under_one_spec_is_refused|Test that backend dimension change is refused.

## DEPENDS

DEPENDS|daedalus/eval/ceiling.py|daedalus.structcore.parse
DEPENDS|daedalus/eval/ceiling.py|daedalus.eval.harness
DEPENDS|daedalus/eval/ceiling.py|daedalus.eval.tasks
DEPENDS|tests/test_codex_provider.py|daedalus.core
DEPENDS|tests/test_codex_provider.py|daedalus.metrics
DEPENDS|tests/test_codex_provider.py|daedalus.offload
DEPENDS|tests/test_codex_provider.py|daedalus.projects
DEPENDS|tests/test_codex_provider.py|daedalus.provider_router
DEPENDS|tests/test_codex_provider.py|daedalus.providers
DEPENDS|tests/test_codex_provider.py|daedalus.providers.codex_cli
DEPENDS|tests/test_codex_provider.py|daedalus.sensitivity
DEPENDS|tests/test_dead_letter_replay.py|runs/council/room.py
DEPENDS|tests/test_dead_letter_replay.py|runs/council/dead_letter_replay.py
DEPENDS|tests/test_dead_letter_replay.py|runs/council/stream_hook.py
DEPENDS|daedalus/spine/cancel.py|ctypes, os, signal, subprocess, sys, threading, time, weakref, dataclasses, pathlib, typing
DEPENDS|tests/test_gui_catalogue.py|daedalus.gui_catalogue
DEPENDS|tests/test_gui_catalogue.py|daedalus.council.vendors
DEPENDS|tests/test_gui_catalogue.py|tokenize
DEPENDS|tests/test_gui_catalogue.py|json
DEPENDS|tests/test_gui_catalogue.py|pathlib
DEPENDS|tests/test_markdown_wikilinks.py|daedalus.structcore.markdown
DEPENDS|daedalus/context_plan.py|daedalus.memory
DEPENDS|daedalus/context_plan.py|daedalus.memory.embeddings
DEPENDS|daedalus/context_plan.py|daedalus.providers.ollama
DEPENDS|daedalus/context_plan.py|daedalus.structcore.dss
DEPENDS|daedalus/context_plan.py|daedalus.structcore.forest
DEPENDS|daedalus/context_plan.py|daedalus.structcore.index
DEPENDS|tests/test_picker_work_queue.py|daedalus.spine.attempt
DEPENDS|tests/test_picker_work_queue.py|daedalus.spine.picker
DEPENDS|tests/test_picker_work_queue.py|daedalus.spine.bootstrap
DEPENDS|tests/test_picker_work_queue.py|daedalus.spine.ledger
DEPENDS|tests/test_picker_work_queue.py|daedalus.offload
DEPENDS|tests/test_envelope_join.py|daedalus.file_bridge
DEPENDS|tests/test_envelope_join.py|daedalus.loop

## WRITES

WRITES|tests/test_mutation_score.py|temporary directories (fixture repos)
WRITES|tests/test_picker_outcome.py|temporary spine database (spine.sqlite3)
WRITES|tests/test_picker_outcome.py|temporary feature inventory file
WRITES|tests/test_structcore_parallel.py|temporary directories via tempfile and _write
WRITES|tests/test_structcore_parallel.py|DAEDALUS_CACHE_DIR environment variable
WRITES|daedalus/structcore/cache.py|directory: cache_root()

## READS

READS|tests/test_host_predicate.py|daedalus/
READS|daedalus/dctx.py|git repository (via subprocess and _read)
READS|daedalus/eval/ceiling.py|reads git history (subprocess calls to git) and source files from repo worktree (Path.read_text)
READS|tests/test_dead_letter_replay.py|runs/council/room.py
READS|tests/test_dead_letter_replay.py|runs/council/dead_letter_replay.py
READS|tests/test_dead_letter_replay.py|runs/council/stream_hook.py
READS|tests/test_gui_catalogue.py|daedalus.gui_catalogue source file (gc.__file__)
READS|tests/test_gui_catalogue.py|catalogue/gui/*.json (SHIPPED)
READS|tests/test_envelope_join.py|tmp_path (temporary directory)
READS|tests/test_structcore_coverage.py|temporary test files under self.root

## CLAIMS

CLAIMS|test_search_without_a_journal_position_reports_unanchored_never_fresh|Default freshness is 'unanchored'.
CLAIMS|test_search_over_a_stale_index_says_so_instead_of_ready|Search with stale journal returns status 'stale' but results.
CLAIMS|test_watermark_refuses_to_move_backwards|Journal position must not decrease.
CLAIMS|test_watermark_refuses_a_rewritten_journal_at_an_unchanged_position|Journal content hash must match at same position.
CLAIMS|test_search_refuses_when_the_journal_forked_under_the_index|Forked journal returns journal_forked status, no matches.
CLAIMS|test_unknown_journal_id_is_unanchored_not_fresh|Unseen journal ID results in unanchored freshness.
CLAIMS|test_journal_position_rejects_nonsense|Constructor validates journal_id and position.
CLAIMS|test_an_offline_backend_is_not_reported_as_drift|Embedder unavailable yields embedder_unavailable, not model_drift.
CLAIMS|tests/test_host_predicate.py|Consolidates host-to-lane predicate onto sensitivity.lane_for_host
CLAIMS|tests/test_host_predicate.py|Tests pin both halves: the shared answers, and the absence of any caller-local copy.
CLAIMS|tests/test_council_vendors.py|Offline tests with no network, no Ollama, no vendor CLI: every transport is injected.
CLAIMS|daedalus/dctx.py|'THIS MODULE ADDS NO CONTEXT LOGIC. compile is a thin wrapper over structcore.slice.semantic_slice'
CLAIMS|tests/test_bridge_restart.py|The module docstring describes expected idempotency behavior after a crash.
CLAIMS|daedalus/eval/ceiling.py|Read-only: never writes the store, the baseline, or any file (stated in module docstring).
CLAIMS|tests/test_dead_letter_replay.py|replay puts a turn into the room ONLY via room.append_turn
CLAIMS|tests/test_dead_letter_replay.py|replaying the same spool twice does not duplicate a turn
CLAIMS|tests/test_dead_letter_replay.py|a malformed spool line is reported and left in the spool, and does not abort replay of good lines
CLAIMS|tests/test_dead_letter_replay.py|after a successful replay, verify_room() is clean
CLAIMS|tests/test_dead_letter_replay.py|--dry-run changes nothing
CLAIMS|tests/test_dead_letter_replay.py|the full loop closes end to end: a real stream_hook dead letter can be replayed back into an attested room
CLAIMS|daedalus/spine/cancel.py|Fail-closed: better to refuse the launch than to run work we cannot cancel.
CLAIMS|tests/test_gui_catalogue.py|The GUI catalogue is DATA, and unprovenanced data is unusable.
CLAIMS|tests/test_markdown_wikilinks.py|NO REGRESSION guarantee
CLAIMS|tests/test_markdown_wikilinks.py|REFUSE TO GUESS guarantee
CLAIMS|tests/test_markdown_wikilinks.py|SEPARATE RELATIONS guarantee
CLAIMS|tests/test_markdown_wikilinks.py|DETERMINISM guarantee
CLAIMS|daedalus/structcore/forest.py|Module docstring: 'Deterministic, domain-neutral Code-Knowledge Forest snapshots'
CLAIMS|daedalus/structcore/forest.py|KnowledgeForest docstring: 'A deterministic evidence snapshot, suitable for storage and comparison.'
CLAIMS|daedalus/context_plan.py|The planner turns a natural-language objective into file-level seed evidence, then delegates coarse-to-fine propagation to DSS.
CLAIMS|daedalus/context_plan.py|plan_context: 'No source material is emitted or rewritten.'
CLAIMS|tests/test_picker_work_queue.py|Focused proof for the curated picker -> attempt path. No model or network is used.
CLAIMS|tests/test_envelope_join.py|One id, three formats, one grep.

## UNWIRED

UNWIRED|daedalus/eval/mint.py|MINT_CONFIRM_THRESHOLD
UNWIRED|daedalus/eval/mint.py|DEFAULT_MINT_STORE_PATH
UNWIRED|daedalus/structcore/dss.py|build_forest_hierarchy (function) - not called within this file
UNWIRED|daedalus/structcore/dss.py|restrict_scores (function) - not called within this file
UNWIRED|daedalus/structcore/dss.py|prolongate_scores (function) - not called within this file
UNWIRED|daedalus/structcore/dss.py|carry_temporal_scores (function) - not called within this file
UNWIRED|daedalus/structcore/dss.py|diffuse_relation_scores (function) - not called within this file
UNWIRED|daedalus/structcore/dss.py|DSS_SCHEMA_VERSION (constant) - not used within this file

## SMELL

SMELL|daedalus/progress_sources.py|Function _bridge_progress is incomplete (signature only) and public symbol snapshot_from_bridge is declared in __all__ but not defined in the visible excerpt.
SMELL|daedalus/tools/vet.py|Combines skill and MCP server vetting in a single module; attack surfaces differ
SMELL|tests/test_ikarus_shells.py|Tests internal functions (_route,_shell_for,_hand_state,_reconcile_final) indicating tight coupling to implementation.
SMELL|tests/test_ui_governance.py|Test method 'test_vscode_surface_reaches_governance_through_the_web_app' calls another test method directly, creating a dependency between tests.
SMELL|tests/test_ui_governance.py|Test class 'BothSurfacesRenderItTests' contains a test that checks for unreachable code ('dashboardHtml'), which is a meta-test.