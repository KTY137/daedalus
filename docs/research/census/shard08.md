# Census shard 8/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/structcore/clones.py|function|window_runs|Extracts normalized line-run hashes from a single file.
daedalus/structcore/clones.py|function|window_clusters_from_runs|Cross-file clustering from precomputed run hashes.
daedalus/structcore/clones.py|function|window_clusters|Full sliding-window clone detection across files.
daedalus/structcore/clones.py|function|renamed_clusters|Groups units by abstract fingerprint excluding exact duplicates.
daedalus/structcore/clones.py|constant|TYPE3_EXCLUDED_LANGUAGES|Languages excluded from near-miss Type-3 pass due to token alphabet sparsity.
daedalus/structcore/artifacts.py|module|artifacts|Provides artifact edge extraction and schema reading.
daedalus/structcore/artifacts.py|constant|ARTIFACTS_VERSION|Semantic version tag for this module's data format.
daedalus/structcore/artifacts.py|constant|MAX_SCHEMA_BYTES|Bounded read limit for schema extraction.
daedalus/structcore/artifacts.py|constant|MAX_COLUMNS|Maximum number of columns to extract from a schema.
daedalus/structcore/artifacts.py|constant|MAX_LITERALS_PER_FILE|Maximum path literals extracted from one file.
daedalus/structcore/artifacts.py|constant|NOT_SUPPORTED|Sentinel for unimplemented schema extraction.
daedalus/structcore/artifacts.py|constant|UNREADABLE|Sentinel for failed schema read.
daedalus/structcore/artifacts.py|constant|READ|Sentinel for successful schema read.
daedalus/structcore/artifacts.py|constant|ARTIFACT_KINDS|Mapping from suffix to (family, has_schema_reader).
daedalus/structcore/artifacts.py|function|artifact_family|Returns artifact family for a given file path.
daedalus/structcore/artifacts.py|function|artifact_node_id|Generates a unique node ID for an artifact.
daedalus/structcore/artifacts.py|function|is_artifact_node_id|Checks if a node ID is an artifact node.
daedalus/structcore/artifacts.py|constant|LITERAL_RULES|Language-specific regex rules for extracting path literals.
daedalus/structcore/artifacts.py|constant|LITERAL_LANGUAGES|Mapping from suffix to language name for literal extraction.
daedalus/structcore/artifacts.py|constant|LITERAL_FILENAMES|Filenames (e.g., Makefile) to language mapping.
daedalus/structcore/artifacts.py|function|literal_language|Returns the literal-extraction language for a given file.
daedalus/structcore/artifacts.py|dataclass|PathLiteral|Represents a single path-shaped literal extracted from code.
daedalus/structcore/artifacts.py|function|extract_literals|Extracts path literals from a file's text.
daedalus/structcore/artifacts.py|function|_candidates|Generates candidate file paths for a literal.
daedalus/structcore/artifacts.py|dataclass|ArtifactEdge|Represents a resolved edge from source to artifact.
daedalus/structcore/artifacts.py|dataclass|ResolveReport|Aggregates results of resolving literals against known files.
daedalus/structcore/artifacts.py|function|resolve_literals|Binds literals to actual files in a known set.
daedalus/structcore/artifacts.py|dataclass|Column|Describes a single column/schema field.
daedalus/structcore/artifacts.py|dataclass|ArtifactSchema|Describes the schema of an artifact or reason for unknown.
daedalus/structcore/artifacts.py|function|_csv_schema|Reads CSV/TSV header to extract column names.
daedalus/structcore/artifacts.py|function|_json_schema|Extracts keys from JSON object or first record.
daedalus/structcore/artifacts.py|function|_npy_schema|Parses NPY header to extract dtype and field names.
daedalus/structcore/artifacts.py|constant|OPTIONAL_READERS|Maps artifact families to optional dependency packages.
daedalus/structcore/artifacts.py|constant|SCHEMA_FROM_CODE|Placeholder for tier-1 code-declared schema extraction (not implemented).
daedalus/structcore/artifacts.py|function|read_schema|Reads schema from a bounded binary blob.
daedalus/structcore/artifacts.py|dataclass|SchemaComparison|Compares a declared schema with an observed artifact schema.
daedalus/structcore/artifacts.py|function|to_dict|Converts various dataclasses to dicts (multiple definitions).
daedalus/progress_sources.py|function|watch_stream|Wraps an event-payload iterator to transparently record CLAIMED, GENERATING, and DONE events based on stream deltas, yielding items unchanged.
daedalus/progress_sources.py|function|record_offload_result|Decomposes an offload() result dict into events: tool_ran, gate_verdict, disk_change (based on content hash diff), and done. Never reads worker self-report.
daedalus/progress_sources.py|function|record_attempt_result|Decomposes an AttemptResult into events: tool_ran, gate_verdict, patch_produced, and done. Never emits disk_changed.
daedalus/progress_sources.py|function|track_call|Claims a unit, calls a blocking function with optional heartbeat, then decomposes recognized result shapes or marks done. Re-raises exceptions.
daedalus/progress_sources.py|function|snapshot_from_ledger|Read-only poll of spine ledger for one unit by effect_key or id, returning UnitProgress or None.
daedalus/progress_sources.py|function|open_attempts|Returns list of UnitProgress for all open ledger intents for a given kind (default attempt.candidate).
daedalus/preservation.py|constant|LOST|string constant representing a fact token that vanished entirely
daedalus/preservation.py|constant|REDUCED|string constant for fewer occurrences but at least one survives
daedalus/preservation.py|constant|DEMOTED|string constant for text that survived but markup did not
daedalus/preservation.py|constant|SECTION|string constant for a heading that disappeared
daedalus/preservation.py|constant|RECASED|string constant for text that survived modulo case/whitespace
daedalus/preservation.py|constant|STRUCTURE|string constant for table rows or code fences lost
daedalus/preservation.py|constant|SEVERITY_ORDER|ordered list of severity strings for display
daedalus/preservation.py|constant|BLOCKING|frozenset of severities that fail the gate (only LOST)
daedalus/preservation.py|class|Finding|frozen dataclass representing a single artefact change finding
daedalus/preservation.py|class|PreservationResult|dataclass holding a list of findings and overall ok flag
daedalus/preservation.py|function|check_preservation|main pure function comparing before/after text and returning PreservationResult
daedalus/preservation.py|function|is_prose_path|returns True if given relative path ends with a known prose extension
daedalus/preservation.py|function|project|returns markup-stripped whitespace-collapsed view of a markdown document
tests/test_ollama_native.py|class|FakeOllama|Context manager for fake Ollama server that records requests and returns scripted responses.
tests/test_ollama_native.py|class|NativeChatBodyTests|Tests for native_chat request body options including num_ctx, temperature, force_json, keep_alive, tools.
tests/test_ollama_native.py|class|NativeChatAdapterTests|Tests for native_chat response adaptation: tool_call arguments serialization, ID preservation, round-trip normalization.
tests/test_ollama_native.py|class|NativeChatErrorTests|Tests that HTTP errors and unreachable hosts raise ProviderHTTPError.
tests/test_ollama_native.py|class|RewriteWindowTests|Tests for window replacement lines, slice injection, oversized file skipping, and drop-to-fit logic.
tests/test_ollama_native.py|class|AgenticWindowTests|Tests for pre-flight refusal of oversized objectives, mid-loop eviction, and slice injection.
tests/test_spine_picker.py|constant|INVENTORY|Sample inventory fixture for testing.
tests/test_spine_picker.py|constant|BASELINE|Sample eval baseline fixture for testing.
tests/test_spine_picker.py|constant|GATE_RESULT|Sample gate result fixture for testing.
tests/test_spine_picker.py|constant|INDEX|Sample hotspot index fixture for testing.
tests/test_spine_picker.py|function|no_eval|Fixture that monkeypatches _load_baseline to keep eval hermetic.
tests/test_spine_picker.py|class|Boom|Exception used to verify no attempt runs.
tests/test_spine_picker.py|class|FakeGate|Fake gate result for review packet tests.
tests/test_spine_picker.py|class|FakeArtifact|Fake artifact for review packet tests.
tests/test_spine_picker.py|class|FakeResult|Fake attempt result for review packet tests.
tests/test_spine_picker.py|function|test_every_candidate_carries_a_reason_a_score_and_evidence|Verifies all candidates have reason, score, and evidence.
tests/test_spine_picker.py|function|test_candidate_without_evidence_is_refused_not_silently_dropped|Ensures NoEvidence raised for missing or minimal evidence.
tests/test_spine_picker.py|function|test_measured_offset_can_never_cross_a_band|Confirms band_offset is clamped within its band.
tests/test_spine_picker.py|function|test_ranking_is_deterministic_for_a_fixed_inventory|Verifies queue order is reproducible.
tests/test_spine_picker.py|function|test_ranking_is_insensitive_to_input_order|Verifies rank output is independent of input order.
tests/test_spine_picker.py|function|test_ties_break_on_task_id_not_on_arrival|Verifies tie-breaking by task_id.
tests/test_spine_picker.py|function|test_source_priority_order_holds_across_sources|Verifies source ordering in queue.
tests/test_spine_picker.py|function|test_more_tested_island_outranks_less_tested_island|Verifies islands ordered by test count.
tests/test_spine_picker.py|function|test_limit_truncates_the_ranked_queue_not_the_sources|Verifies limit truncates queue but sources retain counts.
tests/test_spine_picker.py|function|test_malformed_inventory_degrades_to_an_empty_queue|Verifies malformed inventory yields empty queue with reasons.
tests/test_spine_picker.py|function|test_missing_inventory_file_is_an_empty_inventory_not_a_crash|Verifies missing inventory file yields empty queue.
tests/test_spine_picker.py|function|test_prose_arrays_are_never_queued_but_the_discrepancy_is_reported|Verifies prose islands are not queued but noted.
tests/test_spine_picker.py|function|test_a_broken_eval_baseline_does_not_empty_the_queue|Verifies inventory survives broken eval baseline.
tests/test_spine_picker.py|function|test_cheap_eval_source_queues_only_recorded_misses_and_says_so|Verifies eval baseline queues only tasks with recall < 1.0.
tests/test_spine_picker.py|function|test_eval_gate_source_queues_regressions_and_unmeasurable_primaries|Verifies gate result queues regressions and errored primaries.
tests/test_spine_picker.py|function|test_hotspots_rank_by_measured_score_share|Verifies hotspot ranking by score.
tests/test_spine_picker.py|function|test_hotspots_degrade_when_the_index_carries_no_ranking|Verifies empty index yields no hotspot candidates.
tests/test_spine_picker.py|function|test_expensive_sources_are_off_by_default|Verifies eval gate and hotspots are opt-in.
tests/test_spine_picker.py|function|test_opt_in_sources_are_consulted_when_asked|Verifies opt-in sources are consulted when requested.
tests/test_spine_picker.py|function|test_a_failing_opt_in_source_is_reported_not_raised|Verifies failing opt-in sources are reported as notes.
tests/test_spine_picker.py|function|test_candidates_convert_to_a_real_taskspec_carrying_the_evidence|Verifies candidate.to_task_spec produces TaskSpec with metadata.
tests/test_spine_picker.py|function|test_island_gate_paths_come_from_the_recorded_tests|Verifies gate paths from recorded tests.
tests/test_spine_picker.py|function|test_review_packet_contains_the_diff_and_the_gate_verdict|Verifies review packet includes diff and gate verdict.
tests/test_spine_picker.py|function|test_review_packet_reports_a_passing_gate_as_evidence_not_permission|Verifies passing gate is evidence, not permission.
tests/test_spine_picker.py|function|test_review_packet_does_not_offer_a_reaped_branch_for_inspection|Verifies reaped branch bypasses diff inspection.
tests/test_spine_picker.py|function|test_review_packet_handles_an_attempt_that_produced_no_patch|Verifies no-patch attempt review.
tests/test_spine_picker.py|function|test_an_empty_patch_never_offers_an_apply_command|Verifies empty patch omits apply command.
tests/test_spine_picker.py|function|test_review_packet_truncates_a_huge_diff_and_says_it_did|Verifies diff truncation message.
tests/test_spine_picker.py|function|test_dry_run_performs_no_attempt|Verifies --dry-run prevents attempt.
tests/test_spine_picker.py|function|test_bare_invocation_defaults_to_the_dry_run|Verifies default invocation is dry run.
tests/test_spine_picker.py|function|test_json_output_performs_no_attempt_either|Verifies --json prevents attempt.
tests/test_loop.py|class|FakeWaveResult|Wraps a list of results from FakeExecutor.
tests/test_loop.py|class|FakeExecutor|Records run_wave calls and returns scripted results.
tests/test_loop.py|class|FakeCandidate|Minimal candidate with task_id, paths, score.
tests/test_loop.py|function|make_driver|Creates a LoopDriver with stubbed picker, governance, and session-builder.
tests/test_loop.py|function|patch_env|Patches three external reads (governance, picker, spend) for the driver.
tests/test_loop.py|function|run_driver|Calls patch_env and then driver.run().
tests/test_loop.py|function|spend_series|Returns a closure that yields spend readings, repeating the last.
tests/test_loop.py|class|TestTheStop|Tests killswitch behavior.
tests/test_loop.py|class|TestBounds|Tests iteration, wall clock, and spend bounds.
tests/test_loop.py|class|TestGovernance|Tests governance red/green behavior.
tests/test_loop.py|class|TestConvergence|Tests candidate failure tracking and path claiming.
tests/test_loop.py|class|TestObservabilityAndDryRun|Tests event logging and dry-run properties.
tests/test_spine_return_arc.py|constant|INVENTORY|A sample feature inventory fixture for tests.
tests/test_spine_return_arc.py|function|no_eval|Keeps the cheap eval source hermetic by monkeypatching _load_baseline.
tests/test_spine_return_arc.py|function|test_attempt_intent_kind_has_not_drifted_from_the_writer|Verifies that picker.ATTEMPT_INTENT_KIND equals attempt.INTENT_KIND.
tests/test_spine_return_arc.py|function|test_the_defect_this_closes_same_queue_forever|Without memory, recorded failures do not change the queue.
tests/test_spine_return_arc.py|function|test_an_attempted_candidate_sinks_but_is_never_dropped|An attempted candidate sinks in rank but remains in the queue.
tests/test_spine_return_arc.py|function|test_memory_moves_to_the_band_floor_but_never_out_of_the_band|Memory penalizes to the band floor but does not cross band boundaries.
tests/test_spine_return_arc.py|function|test_memory_attaches_the_evidence_that_moved_it|Memory attaches prior_attempts and outcome evidence to the candidate.
tests/test_spine_return_arc.py|function|test_memory_still_decides_when_the_penalty_ties_at_the_band_floor|Tie-breaking between attempted and untried candidates at the band floor uses reason.
tests/test_spine_return_arc.py|function|test_forget_disables_memory|Setting use_attempt_memory=False disables memory despite a ledger existing.
tests/test_spine_return_arc.py|function|test_a_missing_ledger_is_an_empty_memory_not_a_failure|A missing ledger file results in empty memory, not failure.
tests/test_spine_return_arc.py|function|test_an_unreadable_ledger_is_reported_never_silently_forgotten|An unreadable ledger reports an error and falls back to no memory.
tests/test_spine_return_arc.py|function|test_a_rewritten_instruction_does_not_inherit_the_old_attempts_memory|A task with a changed instruction is not penalized by previous attempts.
tests/test_spine_return_arc.py|function|test_the_same_instruction_is_what_sinks_a_candidate|Only identical instructions cause the penalty.
tests/test_spine_return_arc.py|function|test_memory_has_no_window_an_old_attempt_is_still_remembered|Memory does not have a recency window; old attempts are remembered.
tests/test_spine_return_arc.py|function|test_ranking_a_queue_does_not_modify_the_ledger|Reading the ledger for ranking does not change its bytes.
tests/test_spine_return_arc.py|function|test_ranking_never_initialises_a_ledger_it_merely_reads|The picker does not initialize a non-ledger database.
tests/test_spine_return_arc.py|function|test_the_reader_cannot_write_even_if_asked|A read-only ledger raises an error on write attempts.
tests/test_spine_return_arc.py|function|test_a_read_only_open_does_not_create_a_ledger|Opening a missing ledger read-only does not create the parent directories.
tests/test_spine_return_arc.py|function|test_memory_only_matches_the_task_it_actually_attempted|Memory only affects tasks that have been attempted.
tests/test_spine_return_arc.py|function|test_head_is_read_off_disk_without_spawning_anything|HEAD is resolved by reading .git files directly.
tests/test_spine_return_arc.py|function|test_a_detached_head_holding_a_raw_sha_resolves|A detached HEAD with a raw SHA resolves correctly.
tests/test_spine_return_arc.py|function|test_a_packed_ref_resolves|HEAD resolves through packed-refs.
tests/test_spine_return_arc.py|function|test_a_linked_worktree_resolves_through_commondir|Linked worktree HEAD resolves via commondir.
tests/test_spine_return_arc.py|function|test_a_directory_that_is_not_a_repo_reads_as_unknown|Non-repo directories yield None for HEAD.
tests/test_spine_return_arc.py|function|test_a_stale_inventory_is_withheld_loudly_not_ranked|A stale inventory suppresses the queue and reports loudly.
tests/test_spine_return_arc.py|function|test_a_matching_inventory_is_ranked_normally|A fresh inventory is ranked normally.
tests/test_spine_return_arc.py|function|test_a_dirty_snapshot_alone_does_not_suppress|Dirty inventory without revision mismatch does not suppress.
tests/test_spine_return_arc.py|function|test_freshness_fails_open_when_there_is_no_git_to_ask|Without .git, freshness fails open and allows the queue.
tests/test_spine_return_arc.py|function|test_an_inventory_with_no_recorded_revision_is_not_trusted|An inventory without repo_state is suppressed.
tests/test_spine_return_arc.py|function|test_stale_inventory_flag_re_admits_the_candidates|The --stale-inventory flag allows the queue despite staleness.
tests/test_spine_return_arc.py|function|test_a_short_recorded_sha_matches_a_long_head_by_prefix|Short recorded SHA matches full HEAD by prefix.
tests/test_spine_return_arc.py|function|test_a_recorded_head_that_is_not_a_real_abbreviated_sha_is_refused|Invalid recorded SHA formats are refused.
tests/test_spine_return_arc.py|function|test_a_shorter_actual_head_does_not_satisfy_a_longer_recorded_one|Actual HEAD being shorter than recorded fails freshness.
daedalus/tools/vet.py|constant|VET_VERSION|Identifies verdict meaning version
daedalus/tools/vet.py|constant|CLEAR|Outcome indicating no findings
daedalus/tools/vet.py|constant|REVIEW|Outcome indicating human review needed
daedalus/tools/vet.py|constant|BLOCK|Outcome indicating disqualifying finding

## DEPENDS

DEPENDS|tests/test_projection_worker.py|daedalus.context_plan
DEPENDS|tests/test_projection_worker.py|daedalus.structcore
DEPENDS|tests/test_council_canary.py|daedalus.council.canary
DEPENDS|tests/test_council_canary.py|daedalus.council.vendors
DEPENDS|tests/test_ui_governance.py|daedalus.core
DEPENDS|tests/test_ui_governance.py|daedalus.web_api
DEPENDS|tests/test_ui_governance.py|daedalus.config
DEPENDS|tests/test_ui_governance.py|daedalus.sensitivity
DEPENDS|tests/test_ui_governance.py|daedalus.spine.bootstrap
DEPENDS|daedalus/verifier.py|daedalus.preservation
DEPENDS|daedalus/verifier.py|daedalus.schemas
DEPENDS|daedalus/verifier.py|daedalus.spine.docrefs
DEPENDS|daedalus/semantic_route.py|daedalus.providers.ollama (DEFAULT_HOST)
DEPENDS|daedalus/semantic_route.py|daedalus.router (load_agents, route_task)
DEPENDS|tests/test_bootstrap_receipt.py|daedalus.spine.bootstrap
DEPENDS|tests/test_bootstrap_receipt.py|daedalus.spine.attempt
DEPENDS|tests/test_bootstrap_receipt.py|daedalus.offload
DEPENDS|tests/test_typegraph_fixture.py|daedalus.structcore
DEPENDS|tests/test_latent_index_integrity.py|daedalus.memory.embeddings
DEPENDS|tests/test_host_predicate.py|daedalus.council.vendors
DEPENDS|tests/test_host_predicate.py|daedalus.sensitivity
DEPENDS|tests/test_council_vendors.py|daedalus.council.vendors
DEPENDS|tests/test_council_vendors.py|daedalus.sensitivity
DEPENDS|tests/test_council_vendors.py|daedalus.adapters.subprocess_adapter
DEPENDS|tests/test_council_vendors.py|daedalus.providers._openai_compat
DEPENDS|tests/test_council_vendors.py|daedalus.council.bus
DEPENDS|daedalus/dctx.py|daedalus.structcore.slice
DEPENDS|daedalus/dctx.py|daedalus.sensitivity
DEPENDS|tests/test_bridge_restart.py|daedalus.file_bridge
DEPENDS|tests/test_bridge_restart.py|daedalus.memory
DEPENDS|tests/test_bridge_restart.py|daedalus.core
DEPENDS|daedalus/eval/ceiling.py|daedalus.structcore.churn
DEPENDS|daedalus/eval/ceiling.py|daedalus.structcore.index
DEPENDS|daedalus/eval/ceiling.py|daedalus.structcore.languages

## WRITES

WRITES|daedalus/dctx.py|output receipt file (when --out given)
WRITES|tests/test_gui_catalogue.py|temporary directories (tmp_path)
WRITES|tests/test_envelope_join.py|tmp_path (temporary directory)
WRITES|tests/test_structcore_coverage.py|temporary test files under self.root
WRITES|daedalus/config.py|.agentenv/agentenv.json, .agentenv/agents/*.json, CLAUDE.md, AGENTS.md (via init_repo)
WRITES|tests/test_safety_reachability.py|<temporary directories during setup>

## READS

READS|tests/test_spine_picker.py|FEATURE_INVENTORY.json (via tmp_path)
READS|tests/test_loop.py|daedalus/loop.py
READS|daedalus/tools/vet.py|.agentenv/tool-allowances.json
READS|daedalus/tools/vet.py|Skill body and bundled files via scan_text
READS|tests/test_ui_governance.py|vscode-agent-env/extension.js
READS|tests/test_ui_governance.py|apps/web/src/**/*.ts*
READS|tests/test_ui_governance.py|.agentenv/agentenv.json (via daedalus.config)
READS|daedalus/verifier.py|repo_root (files on disk via subprocess and Path reads)
READS|tests/test_bootstrap_receipt.py|tools/bootstrap_receipt.py
READS|tests/test_typegraph_fixture.py|tests/fixtures/typegraph/

## CLAIMS

CLAIMS|tests/test_ui_governance.py|The promotion verdict must reach every surface and must never read green.
CLAIMS|tests/test_ui_governance.py|GovernanceShapeTests: Payload has the operator question answered.
CLAIMS|tests/test_ui_governance.py|NeverGreenByAccidentTests: Worst gate wins, no gates is unknown, unreadable revision refuses.
CLAIMS|tests/test_ui_governance.py|AgreesWithTheRealAuthorityTests: Promotion allowed matches gate discrimination exactly.
CLAIMS|tests/test_ui_governance.py|WriteConfinementIsMeasuredNotReadTests: Confinement gate probes the real write predicate.
CLAIMS|tests/test_ui_governance.py|BothSurfacesRenderItTests: Both surfaces render the verdict (source-level check).
CLAIMS|tests/test_ui_governance.py|ApiServesTheSameVerdictTests: API endpoint matches dashboard block.
CLAIMS|daedalus/verifier.py|verify: 'closes the silent-escalation hole' and ensures bad local output is caught before shipping or looping
CLAIMS|daedalus/semantic_route.py|The latent route never breaks routing; errors fall back to keyword router.
CLAIMS|daedalus/semantic_route.py|Provenance is provided via LatentRouteResult, distinguishing LATENT, PATH_OWNED, and FALLBACK mechanisms.
CLAIMS|daedalus/semantic_route.py|Failures are never cached; degenerate vectors, dimension mismatch, and ties are treated as failures.
CLAIMS|daedalus/semantic_route.py|Cold model load timeout is separate from warm timeout to avoid silent degradation.
CLAIMS|tests/test_bootstrap_receipt.py|The module docstring claims gate_discrimination is the only thing between pytest ran and promotion, and it fails closed four ways.
CLAIMS|tests/test_bootstrap_receipt.py|ThePositiveControl claims that if it fails, every refusal test passes for the wrong reason.
CLAIMS|tests/test_bootstrap_receipt.py|TheRevisionClauseMustNotFailOpen claims that the condition 'if head and measured_head and not head.startswith(...)' must fail closed when head is falsy.
CLAIMS|tests/test_typegraph_fixture.py|The type/data-structure graph's TRIPWIRE suite — passes against UNMODIFIED code.
CLAIMS|tests/test_typegraph_fixture.py|I1: extract_units returns ONLY functions/methods.
CLAIMS|tests/test_typegraph_fixture.py|I2: graph.build_resolver(...).defs_by_file contains only function/method names.
CLAIMS|tests/test_typegraph_fixture.py|I4: modules / import_edges / duplication are byte-identical to the pre-feature build.
CLAIMS|test_moved_model_tag_without_revision_is_refused_not_silently_mixed|The index must refuse to accept vectors when the model tag moves without a revision pin.
CLAIMS|test_pinned_revision_does_not_stop_a_second_host_but_the_anchor_does|Pinned revision does not partition by host; runtime anchor does.
CLAIMS|test_two_specs_never_share_a_search|Distinct specs must partition searches and not fall back.
CLAIMS|test_a_spec_that_lies_about_the_request_is_refused|Spec fields provider, dimension, projector_version are cross-checked against live backend output.
CLAIMS|test_spec_overrides_loose_kwargs_rather_than_cross_checking_them|When spec is supplied, kwargs are ignored; cross-check is unreachable from public API.
CLAIMS|test_identity_anchor_tolerates_ordinary_service_jitter|Sub-tolerance noise and pure rescale do not trigger drift.
CLAIMS|test_drift_is_detected_across_a_reopen_not_just_within_one_process|Verification cache must not persist across processes.
CLAIMS|test_anchor_provenance_marks_retrofitted_indexes_as_trust_on_first_use|Missing anchor leads to adoption; provenance returned as 'adopted'.
CLAIMS|test_unpinned_movable_tag_is_reported_as_unpinned|Model without model_revision has pins_model_revision False.
CLAIMS|test_mixed_width_vectors_in_one_index_are_refused_not_broadcast|Short vectors must not be zero-padded or truncated.
CLAIMS|test_cosine_refuses_mismatched_widths_directly|_cosine raises ValueError on dimension mismatch.
CLAIMS|test_backend_that_changes_output_width_under_one_spec_is_refused|Model with different width is refused.
CLAIMS|test_dangling_identity_anchor_is_reported_as_a_corrupt_index|Orphaned anchor projection triggers invalid_index.

## UNWIRED

UNWIRED|daedalus/progress.py|UnitProgress
UNWIRED|daedalus/progress.py|BatchProgress
UNWIRED|daedalus/progress.py|snapshot
UNWIRED|daedalus/progress.py|batch_snapshot
UNWIRED|daedalus/progress.py|render
UNWIRED|daedalus/progress.py|render_batch
UNWIRED|daedalus/progress.py|to_payload
UNWIRED|daedalus/progress.py|main

## SMELL

SMELL|tests/test_generated_inventory.py|High density of similar test functions, potential for reduced readability or maintenance overhead
SMELL|daedalus/spine/bootstrap.py|Imports private function _picker_source_mode from daedalus.spine.picker
SMELL|daedalus/structcore/clones.py|near_clusters function is referenced in comments but not defined in the visible file slice.
SMELL|daedalus/structcore/clones.py|_safety function used in cluster functions but not imported from the visible imports.
SMELL|daedalus/structcore/artifacts.py|CompareSchema comparison function is promised (docstring 'compare_schema') but defined elsewhere or missing.