# Census shard 11/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/spine/cancel.py|constant|BACKEND|Selected backend class based on platform.
daedalus/spine/cancel.py|constant|BACKEND_NAME|Name of the selected backend.
tests/test_gui_catalogue.py|constant|REPO_ROOT|path to repository root
tests/test_gui_catalogue.py|constant|SHIPPED|path to shipped catalogue directory
tests/test_gui_catalogue.py|function|test_entry_without_licence_is_refused_at_parse|entry without licence is refused at parse
tests/test_gui_catalogue.py|function|test_entry_with_empty_licence_is_refused_at_parse|entry with empty licence is refused at parse
tests/test_gui_catalogue.py|function|test_entry_without_licence_is_refused_at_construction|entry without licence is refused at construction
tests/test_gui_catalogue.py|function|test_unlicensed_entry_is_quarantined_not_served|unlicensed entry is quarantined and not served
tests/test_gui_catalogue.py|function|test_unlicensed_entry_is_unreachable_from_search|unlicensed entry is unreachable from search
tests/test_gui_catalogue.py|function|test_entry_without_provenance_is_refused|entry without provenance is refused
tests/test_gui_catalogue.py|function|test_provenance_requires_every_field|provenance requires every field
tests/test_gui_catalogue.py|function|test_provenance_retrieved_must_be_a_date|provenance retrieved must be a date
tests/test_gui_catalogue.py|function|test_unprovenanced_entry_is_quarantined_and_unsearchable|unprovenanced entry is quarantined and unsearchable
tests/test_gui_catalogue.py|function|test_unrecognised_licence_is_refused_not_assumed_permissive|unrecognised licence is refused, not assumed permissive
tests/test_gui_catalogue.py|function|test_licence_that_merely_contains_mit_is_not_treated_as_mit|licence containing 'MIT' is not treated as MIT (substring guard)
tests/test_gui_catalogue.py|function|test_every_licence_in_the_table_maps_to_a_known_use_mode|every licence in table maps to known use mode
tests/test_gui_catalogue.py|function|test_entry_declaring_a_derived_field_is_refused|entry declaring a derived field is refused
tests/test_gui_catalogue.py|function|test_a_restricted_entry_cannot_declare_itself_vendorable|restricted entry cannot declare itself vendorable
tests/test_gui_catalogue.py|function|test_use_mode_is_computed_from_the_licence|use mode is computed from licence
tests/test_gui_catalogue.py|function|test_reciprocal_is_not_vendorable_because_a_human_decides|reciprocal is not vendorable because a human decides
tests/test_gui_catalogue.py|function|test_unknown_key_is_refused|unknown key is refused
tests/test_gui_catalogue.py|function|test_the_schema_has_no_place_to_vendor_source|schema has no place to vendor source (no files/content keys)
tests/test_gui_catalogue.py|function|test_bad_kind_is_refused|bad kind is refused
tests/test_gui_catalogue.py|function|test_duplicate_name_is_rejected_not_overwritten|duplicate name is rejected not overwritten
tests/test_gui_catalogue.py|function|test_unreadable_file_is_reported_not_swallowed|unreadable file is reported not swallowed
tests/test_gui_catalogue.py|function|test_missing_catalogue_directory_is_empty_not_an_error|missing catalogue directory is empty not an error
tests/test_gui_catalogue.py|function|test_unresolved_dependency_is_reported_never_guessed|unresolved dependency is reported never guessed
tests/test_gui_catalogue.py|function|test_prompt_rendering_carries_the_repo_wide_untrusted_notice|prompt rendering carries repo-wide untrusted notice
tests/test_gui_catalogue.py|function|test_the_notice_is_imported_not_a_second_copy|notice is imported not a second copy
tests/test_gui_catalogue.py|function|test_untrusted_bytes_are_fenced_and_labelled_with_their_origin|untrusted bytes are fenced and labelled with origin
tests/test_gui_catalogue.py|function|test_the_notice_precedes_every_untrusted_byte|notice precedes every untrusted byte
tests/test_gui_catalogue.py|function|test_an_injection_in_an_entry_stays_inside_the_fence|injection in entry stays inside the fence
tests/test_gui_catalogue.py|function|test_prompt_rendering_states_the_copy_prohibition|prompt rendering states copy prohibition for proprietary
tests/test_gui_catalogue.py|function|test_search_adds_no_sixth_ranking_predicate|search adds no sixth ranking predicate
tests/test_gui_catalogue.py|function|test_search_ranks_by_purpose_not_only_by_name|search ranks by purpose not only by name
tests/test_gui_catalogue.py|function|test_search_respects_limit_and_kind_and_first_party_filters|search respects limit, kind, and first-party filters
tests/test_gui_catalogue.py|function|test_search_refuses_an_empty_objective|search refuses an empty objective
tests/test_gui_catalogue.py|function|test_latent_is_off_by_default_and_says_so|latent is off by default and says so
tests/test_gui_catalogue.py|function|test_latent_failure_degrades_but_is_named|latent failure degrades but is named
tests/test_gui_catalogue.py|function|test_latent_uses_the_repo_embedding_store_not_a_new_one|latent uses repo embedding store not a new one
tests/test_gui_catalogue.py|function|test_shipped_catalogue_loads_clean|shipped catalogue loads clean
tests/test_gui_catalogue.py|function|test_every_shipped_entry_has_a_licence_and_a_provenance|every shipped entry has licence and provenance
tests/test_gui_catalogue.py|function|test_the_glass_set_is_present_and_ours|glass set is present and first-party
tests/test_gui_catalogue.py|function|test_every_first_party_entry_points_at_a_file_that_exists|every first-party entry points at an existing file
tests/test_gui_catalogue.py|function|test_the_three_licence_traps_are_reference_only|three licence traps are reference_only
tests/test_gui_catalogue.py|function|test_no_shipped_entry_carries_third_party_source|no shipped entry carries third-party source
tests/test_gui_catalogue.py|function|test_split_licence_entries_force_a_human_decision|split licence entries force a human decision
tests/test_gui_catalogue.py|function|test_shipped_catalogue_answers_a_real_build_question|shipped catalogue answers a real build question
tests/test_markdown_wikilinks.py|module|test_markdown_wikilinks|Guarantees all tests for wikilink functionality
tests/test_markdown_wikilinks.py|constant|PLAIN_DOC|Guarantees a sample document with no wikilinks
tests/test_markdown_wikilinks.py|constant|PLAIN_NO_HEADINGS|Guarantees a sample document without headings
tests/test_markdown_wikilinks.py|constant|PLAIN_DOC_FINGERPRINT|Guarantees the expected hash for plain document with wikilinks
tests/test_markdown_wikilinks.py|constant|PLAIN_NO_HEADINGS_FINGERPRINT|Guarantees the expected hash for plain document without headings
tests/test_markdown_wikilinks.py|constant|PLAIN_KNOWN|Guarantees known file set for legacy edge test
tests/test_markdown_wikilinks.py|constant|VAULT|Guarantees a vault file set for resolution tests
tests/test_markdown_wikilinks.py|constant|DOC|Guarantees the document path used in tests
tests/test_markdown_wikilinks.py|constant|MIXED|Guarantees a mixed document for determinism test
tests/test_markdown_wikilinks.py|class|NoWikilinkDocumentIsUnmoved|Guarantees that documents without wikilinks parse identically as before
tests/test_markdown_wikilinks.py|class|WikilinkForms|Guarantees correct parsing of various wikilink syntax forms
tests/test_markdown_wikilinks.py|class|Resolution|Guarantees correct resolution of wikilinks to files and refusal to guess
tests/test_markdown_wikilinks.py|class|Determinism|Guarantees that results are deterministic regardless of iteration order
daedalus/structcore/forest.py|constant|SCHEMA_VERSION|Version string "daedalus-forest/1"
daedalus/structcore/forest.py|class|ForestNode|Frozen dataclass representing a node with id, kind, and attributes
daedalus/structcore/forest.py|class|ForestEdge|Frozen dataclass representing a directed edge with source, target, relation, weight, evidence, and attributes
daedalus/structcore/forest.py|class|ForestHyperedge|Frozen dataclass representing a hyperedge with id, relation, members, weight, evidence, and attributes
daedalus/structcore/forest.py|class|KnowledgeForest|Frozen dataclass representing a deterministic forest snapshot with nodes, edges, hyperedges, root, provenance, schema, and properties
daedalus/structcore/forest.py|function|build_knowledge_forest|Normalizes a structcore index and optional temporal co-change pairs into a KnowledgeForest
daedalus/eval/report.py|constant|HEADER|Provides the header string for Daedalus distillation eval reports.
daedalus/eval/report.py|function|render_tier1|Renders Tier 1 deterministic slice recall + compression results as ASCII table, with provenance breakdown and focus-withheld/errored sections.
daedalus/eval/report.py|function|render_arms|Renders A/B/C arms report (distilled slice vs whole-repo vs BM25) as ASCII table, with provenance breakdown and c_beats_a analysis.
daedalus/eval/report.py|function|render_tier2|Renders Tier 2 LLM task-success results (slice vs whole-repo) as ASCII table, including truncated warning and errored tasks.
daedalus/eval/report.py|function|render_gate|Renders advisory regression-ratchet gate report (counterfactual recall comparison), with regressions, improvements, new/missing tasks, and errored/focus-withheld sections.
daedalus/eval/report.py|function|render|Combines all render functions (tier1, optional tier2/arms) into a single output string.
daedalus/context_plan.py|module|context_plan|Hybrid, evidence-bearing context planning over the Daedalus Knowledge Forest.
daedalus/context_plan.py|constant|CONTEXT_PLAN_SCHEMA|Schema identifier for context planning receipts.
daedalus/context_plan.py|constant|LEXICAL_PROJECTOR_VERSION|Version string for lexical BM25 projector.
daedalus/context_plan.py|constant|LATENT_MAPPER_VERSION|Version string for latent event-path mapper.
daedalus/context_plan.py|constant|LATENT_STATUS_DISABLED|Sentinel status for latent source not requested.
daedalus/context_plan.py|constant|LATENT_STATUS_READY|Sentinel status for latent source answered successfully.
daedalus/context_plan.py|constant|LATENT_STATUS_ERROR|Sentinel status for latent source raised an error.
daedalus/context_plan.py|class|LexicalSeedResult|Data class holding BM25 lexical seed scores, query terms, and matched terms.
daedalus/context_plan.py|class|LatentSeedResult|Data class holding latent seed results, including status, message, scores, and mapped events.
daedalus/context_plan.py|class|HybridSeedResult|Data class holding fused lexical and latent seed scores with metadata.
daedalus/context_plan.py|class|ContextPlanningResult|Data class holding the complete context planning result, including objective, seeds, DSS result, and receipt.
daedalus/context_plan.py|function|lexical_seed_scores|Compute BM25 baseline scores over path and symbol-name evidence from the index.
daedalus/context_plan.py|function|latent_not_requested|Return a sentinel LatentSeedResult indicating latent seeds were not requested.
daedalus/context_plan.py|function|latent_memory_seed_scores|Search versioned event projections and map events to file paths to produce latent seed scores.
daedalus/context_plan.py|function|fuse_seed_scores|Fuse lexical and latent seed scores using weighted linear combination and normalize.
daedalus/context_plan.py|function|plan_context|Build a hybrid DSS plan from a natural language objective and optional parameters.
tests/test_picker_work_queue.py|constant|BASE|provides a 40-character hex string for base revision
tests/test_picker_work_queue.py|constant|OBSERVED|provides a 40-character hex string for observed head
tests/test_picker_work_queue.py|constant|TARGET|provides the target path string design/visual-lab/src/main.tsx
tests/test_picker_work_queue.py|constant|GATE_ARGV|provides a list of command-line arguments for the gate
tests/test_picker_work_queue.py|function|test_work_queue_source_states_are_distinct_and_path_is_confined|verifies that work queue source states are distinct and the path is confined to repo root
tests/test_picker_work_queue.py|function|test_work_queue_path_cannot_escape_through_a_symlink|verifies that a symlink cannot be used to escape the repo root
tests/test_picker_work_queue.py|function|test_disabled_map_source_is_not_refreshed_into_the_primary_repo|verifies that a disabled map source is not refreshed
tests/test_picker_work_queue.py|function|test_queue_candidate_binds_bytes_base_scope_gate_and_observed_head|verifies candidate binding with base, scope, gate, and observed head
tests/test_picker_work_queue.py|function|test_invalid_queue_never_admits_a_partial_candidate|verifies that invalid queue never admits a partial candidate
tests/test_picker_work_queue.py|function|test_policy_feasibility_suppresses_task_before_ranking|verifies that policy feasibility suppresses task before ranking
tests/test_picker_work_queue.py|function|test_external_repo_uses_one_repo_bound_ledger_for_read_and_write|verifies external repo uses one repo-bound ledger for read and write
tests/test_picker_work_queue.py|function|test_legacy_taskspec_body_and_digest_shape_are_unchanged|verifies legacy TaskSpec body and digest shape remain unchanged
tests/test_picker_work_queue.py|function|test_offload_runner_forwards_declared_paths_and_cannot_be_widened|verifies offload runner forwards declared paths and cannot be widened
tests/test_picker_work_queue.py|function|test_taskspec_command_gate_is_the_attempt_default|verifies TaskSpec command gate is the attempt default
tests/test_picker_work_queue.py|function|test_artifact_outside_target_scope_is_refused_before_gate|verifies artifact outside target scope is refused before gate
tests/test_picker_work_queue.py|function|test_in_scope_artifact_reaches_the_gate|verifies in-scope artifact reaches the gate
tests/test_picker_work_queue.py|function|test_green_gate_cannot_rewrite_the_tree_after_artifact_capture|verifies green gate cannot rewrite the tree after artifact capture
tests/test_picker_work_queue.py|function|test_post_gate_binding_error_fails_closed_and_resolves_intent|verifies post-gate binding error fails closed and resolves intent
tests/test_picker_work_queue.py|function|test_review_packet_is_safe_for_a_cp1252_windows_console|verifies review packet is safe for a cp1252 Windows console
tests/test_envelope_join.py|function|test_one_trace_spans_three_producers|One trace id appears in spine ledger, loop ledger, and bridge record.
tests/test_envelope_join.py|function|test_the_three_producers_agree_on_the_key_name|All producers use the same key name for trace id.
tests/test_envelope_join.py|function|test_the_bridge_carries_the_trace_across_the_process_boundary|Trace id is preserved in request file for watcher process.
tests/test_envelope_join.py|function|test_an_untraced_request_is_never_given_a_private_id|adopt_trace(None) does not mint a trace id.
tests/test_envelope_join.py|function|test_a_trace_does_not_leak_into_the_next_run|Trace context is cleared after run exception.
tests/test_envelope_join.py|function|test_two_runs_do_not_share_a_trace|Nested trace contexts produce distinct ids.
tests/test_envelope_join.py|function|test_a_v1_ledger_is_migrated_in_place_and_its_rows_survive|v1 ledger migrates and old rows have trace_id NULL, new rows get trace_id.
tests/test_envelope_join.py|function|test_a_v1_ledger_opened_READ_ONLY_still_reads|Read-only v1 ledger returns rows with trace_id None, no migration occurs.
tests/test_envelope_join.py|function|test_an_untraced_intent_is_written_exactly_as_v1_wrote_it|Untraced intents are byte-identical to v1 format.
tests/test_envelope_join.py|function|test_the_spine_payload_column_is_never_wrapped|Payload column remains unwrapped; envelope is built on read.
tests/test_envelope_join.py|function|test_intent_to_statement_is_ite6_shaped_and_digests_the_stored_sha|to_statement produces correct in-toto statement digesting stored sha.
tests/test_envelope_join.py|function|test_the_loop_ledger_reads_a_v1_document_and_a_v2_document|LoopLedger.load returns same shape for v1 and v2.
tests/test_envelope_join.py|function|test_a_v1_loop_record_can_still_be_recorded_into|record does not KeyError on v1 loop records without trace_ids.
tests/test_envelope_join.py|function|test_a_legacy_bridge_report_still_parses|Legacy bridge report without trace/envelope parses correctly.
tests/test_envelope_join.py|function|test_a_payload_that_merely_has_a_type_key_is_not_unwrapped|is_statement correctly rejects decoy _type.
tests/test_envelope_join.py|function|test_stamp_never_mutates_its_argument_and_incoming_trace_wins|Stamp creates new dict; incoming trace_id is preserved.
tests/test_envelope_join.py|function|test_gen_ai_names_match_the_semantic_convention_spelling|GenAI attribute names match OTel semantic conventions.
tests/test_envelope_join.py|function|test_no_opentelemetry_runtime_was_taken_with_the_names|envelope.py does not import opentelemetry.
tests/test_envelope_join.py|function|test_gen_ai_projection_drops_what_it_cannot_name|gen_ai_attributes drops fields without a mapping.
tests/test_envelope_join.py|function|test_the_loop_report_carries_and_renders_the_trace|LoopReport.to_dict includes trace_id and renders grep command.
tests/test_envelope_join.py|function|test_an_untraced_report_prints_no_trace_line|LoopReport without trace_id does not print trace line.
tests/test_envelope_join.py|function|test_the_loop_cli_prints_a_greppable_trace_id|CLI --dry-run prints a greppable trace_id in stdout.
tests/test_semantic_route_live.py|module|test_semantic_route_live|This module tests the real semantic_route against a live (fake-backed) embedding server, guaranteeing that the route runs when backend answers and reports honestly when it doesn't.
tests/test_semantic_route_live.py|class|FakeOllama|Real HTTP server that answers /api/embeddings however you tell it to, records prompts.
tests/test_semantic_route_live.py|class|LatentRouteRunsTests|Tests that the latent route runs, overrides keyword choice, caches role vectors, and returns bare dict from legacy wrapper.
tests/test_semantic_route_live.py|class|HonestFailureTests|Tests that failure modes (host unreachable, model not found, embeddings unsupported, bad response, empty/degenerate/ambiguous embeddings) are reported distinctively.
tests/test_semantic_route_live.py|class|CacheRecoveryTests|Tests that transient failure does not poison the route and roster change invalidates cached vectors.
tests/test_semantic_route_live.py|class|PathOwnershipTests|Tests that owned path skips the backend entirely and is distinguishable from failure.
tests/test_semantic_route_live.py|class|VisibilityTests|Tests that legacy wrapper warns when route never ran, does not warn when it ran, and result serialises correctly.
tests/test_semantic_route_live.py|class|RosterTests|Tests that the active_agents filter is honoured and the latent route sees only allowed agents.
tests/test_semantic_route_live.py|class|RealBackendTests|Tests against the real local backend, skipping gracefully if unavailable, and ensures routing succeeds either way.
daedalus/kairos/scheduler.py|constant|FREE_LANES|Guarantees the set of providers that Ikarus may dispatch (non-Claude).
daedalus/kairos/scheduler.py|constant|DEFAULT_AVAILABILITY|Guarantees default availability with local bench on and external benches dormant.
daedalus/kairos/scheduler.py|class|Assignment|Guarantees a dataclass holding task assignment, acceptance status, and reason.
daedalus/kairos/scheduler.py|class|KairosScheduler|Guarantees bounded concurrency via max_workers and max_parallel_writes, and safe dispatch routing.
daedalus/kairos/scheduler.py|function|main|Guarantees a CLI entry point for demo task planning.
tests/test_structcore_coverage.py|constant|REPO_ROOT|path to repo root
tests/test_structcore_coverage.py|constant|C_BODY|C function body for test fixtures
tests/test_structcore_coverage.py|constant|C_SIBLING|C sibling function body
tests/test_structcore_coverage.py|constant|CPP_BODY|C++ method body
tests/test_structcore_coverage.py|constant|WIDGET_CPP|C++ class implementation
tests/test_structcore_coverage.py|class|CppSymbolSliceTest|tests for symbol resolution in C/C++ slices

## DEPENDS

DEPENDS|daedalus/structcore/graph.py|daedalus/structcore/markdown (code_modules)
DEPENDS|tests/test_picker_outcome.py|daedalus.spine.picker
DEPENDS|tests/test_picker_outcome.py|daedalus.spine.ledger
DEPENDS|tests/test_picker_outcome.py|daedalus.spine.attempt
DEPENDS|tests/test_structcore_parallel.py|daedalus.structcore.cache
DEPENDS|tests/test_structcore_parallel.py|daedalus.structcore.clones
DEPENDS|tests/test_structcore_parallel.py|daedalus.structcore.index
DEPENDS|tests/test_structcore_parallel.py|daedalus.structcore.languages
DEPENDS|tests/test_structcore_parallel.py|daedalus.structcore.parse
DEPENDS|tests/test_structcore_center_naming.py|daedalus.structcore.index
DEPENDS|tests/test_structcore_center_naming.py|daedalus.structcore.ignore
DEPENDS|tests/test_structcore_ignore.py|daedalus.structcore.ignore
DEPENDS|tests/test_structcore_ignore.py|daedalus.structcore.index
DEPENDS|tests/test_structcore_ignore.py|daedalus.web_api
DEPENDS|tests/test_structcore_ignore.py|daedalus.structcore.slice
DEPENDS|tests/test_worktree_properties.py|daedalus.kairos.worktree
DEPENDS|daedalus/adapters/subprocess_adapter.py|.base (AgentAdapter)
DEPENDS|daedalus/adapters/subprocess_adapter.py|.events (AgentCapabilities, AgentEvent, AgentMessage, CommandOutput, SessionEnded, SessionStarted, TextDelta, ToolCompleted, ToolRequested, event_to_transport_record)
DEPENDS|daedalus/adapters/subprocess_adapter.py|.transport (TransportSink)
DEPENDS|tests/test_comms.py|daedalus.config
DEPENDS|tests/test_comms.py|daedalus.enforce
DEPENDS|tests/test_comms.py|daedalus.file_bridge
DEPENDS|tests/test_comms.py|daedalus.core
DEPENDS|tests/test_comms.py|daedalus.kairos
DEPENDS|tests/test_comms.py|daedalus.providers
DEPENDS|tests/test_canary_livewire.py|daedalus.cli
DEPENDS|tests/test_canary_livewire.py|daedalus.council.canary
DEPENDS|tests/test_canary_livewire.py|daedalus.council.session
DEPENDS|tests/test_canary_livewire.py|daedalus.council.vendors
DEPENDS|tests/test_spend_coverage.py|daedalus.budget
DEPENDS|tests/test_temporal_ceiling.py|daedalus.eval.ceiling
DEPENDS|tests/test_temporal_ceiling.py|daedalus.structcore.churn
DEPENDS|tests/test_containment.py|daedalus/spine/containment.py
DEPENDS|tests/test_preservation.py|daedalus.preservation

## WRITES

WRITES|daedalus/providers/codex_cli.py|temporary directory (schema and output files)
WRITES|daedalus/gui/lint.py|runs/gui/report.json
WRITES|daedalus/shift.py|runs/shift.json
WRITES|daedalus/shift.py|runs/shift.json.lock
WRITES|daedalus/arch_memory.py|runs/arch_memory.json
WRITES|daedalus/arch_memory.py|runs/arch_memory.shown

## READS

READS|tests/test_spend_coverage.py|(recursively scans all .py files in repo root)
READS|daedalus/eval/mutate.py|Reads Python source files from repository during mutation generation.
READS|tests/test_containment.py|daedalus/spine/containment.py (via inspect.getsource)
READS|tests/test_stream_hook.py|HOOK_PATH (stream_hook.py file)
READS|tests/test_spine_map_source.py|architecture-state.json (via load_map_state)
READS|daedalus/structcore/cache.py|daedalus/structcore/parse.py
READS|tests/test_gate_containment_job_caps.py|REPO_ROOT (reads the repository root path for PYTHONPATH)
READS|daedalus/spine/docref_gate.py|target document file (.md) at path from --doc argument
READS|daedalus/spine/docref_gate.py|repo root directory (--repo-root) for scanning
READS|daedalus/build.py|session snapshot files

## CLAIMS

CLAIMS|tests/test_git_is_a_process_launcher.py|test_the_product_pins_no_textconv_in_the_option_list claims the product passes --no-textconv.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_CONTROL_an_attributesFile_in_the_admin_config_fires claims an attributesFile in admin config fires.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_the_exec_config_keys_are_pinned_empty_on_the_command_line claims -c beats config files to disable core.attributesFile.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_a_real_attempt_does_not_execute_the_candidates_filter claims a real attempt does not execute candidate's filter.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_an_ordinary_patch_is_still_captured_correctly claims patch capture still works after hardening.
CLAIMS|tests/test_mapping_spectral.py|Every metric in spectral.py is tested against a synthetic graph whose answer is known BEFORE the code runs
CLAIMS|daedalus/structcore/graph.py|Compiler-precise symbol resolution is SCIP/stack-graphs territory; this is an honest v1 name-based approach
CLAIMS|tests/test_picker_outcome.py|The band invariant is not negotiable: an outcome may move a candidate inside its band and never out of it, and memory is a PENALTY, never a filter.
CLAIMS|tests/test_picker_outcome.py|Every contrast below rests on this: the twins really are indistinguishable before memory speaks.
CLAIMS|tests/test_picker_outcome.py|Two identical candidates are ordered by their outcome.
CLAIMS|tests/test_picker_outcome.py|At the band floor, clean is picked after gates_failed.
CLAIMS|tests/test_picker_outcome.py|Severity outranks the attempt count.
CLAIMS|tests/test_picker_outcome.py|No outcome can move a candidate out of its band.
CLAIMS|tests/test_picker_outcome.py|Memory never promotes a candidate.
CLAIMS|tests/test_picker_outcome.py|No outcome removes work from the queue.
CLAIMS|tests/test_picker_outcome.py|Every attempt state the writer can produce is classified.
CLAIMS|tests/test_picker_outcome.py|The policy is internally well-formed.
CLAIMS|tests/test_picker_outcome.py|The policy is ordered the way its prose claims.
CLAIMS|tests/test_picker_outcome.py|An unknown or missing outcome fails closed.
CLAIMS|tests/test_picker_outcome.py|An in-flight attempt is sunk as hard as a finished one.
CLAIMS|tests/test_picker_outcome.py|Repeats of a mild outcome compound.
CLAIMS|tests/test_picker_outcome.py|Compounding counts the instruction not the task_id.
CLAIMS|tests/test_picker_outcome.py|The score carries the argument that produced it.
CLAIMS|tests/test_picker_outcome.py|The note names the outcomes it acted on.
CLAIMS|tests/test_picker_outcome.py|A candidate already below its ceiling is reported as held.
CLAIMS|tests/test_structcore_parallel.py|The bar for this work is DETERMINISM, not speed: the parallel and cached paths must produce byte-identical indexes to the serial one.
CLAIMS|tests/test_structcore_parallel.py|Order preservation is load-bearing (the clone passes consume it positionally).
CLAIMS|daedalus/observe/shape.py|The module guarantees it does not read element values, only metadata (family, dtype, shape, names).
CLAIMS|daedalus/observe/shape.py|describe guarantees that redact hook is applied to all names extracted.
CLAIMS|tests/test_structcore_center_naming.py|Center-relative naming ensures that a declared center means the subtree is the project, it is the package root, and imports resolve correctly, preventing false edges.
CLAIMS|tests/test_worktree_properties.py|cleanup never removes through a reparse point
CLAIMS|daedalus/adapters/subprocess_adapter.py|one-shot CLI profiles do not expose a portable approval protocol (in approve/reject methods)

## UNWIRED

UNWIRED|daedalus/structcore/artifacts.py|compare_schema: referenced only in docstring; no actual definition found in this file.
UNWIRED|daedalus/preservation.py|is_prose_path is defined here but not called within this file
UNWIRED|tests/test_spine_return_arc.py|test_attempt_intent_kind_has_not_drifted_from_the_writer
UNWIRED|tests/test_spine_return_arc.py|test_the_defect_this_closes_same_queue_forever
UNWIRED|tests/test_spine_return_arc.py|test_an_attempted_candidate_sinks_but_is_never_dropped
UNWIRED|tests/test_spine_return_arc.py|test_memory_moves_to_the_band_floor_but_never_out_of_the_band
UNWIRED|tests/test_spine_return_arc.py|test_memory_attaches_the_evidence_that_moved_it
UNWIRED|tests/test_spine_return_arc.py|test_memory_still_decides_when_the_penalty_ties_at_the_band_floor

## SMELL

SMELL|daedalus/structcore/forest.py|build_knowledge_forest is a long monolithic function handling multiple concerns (module nodes, type nodes, import edges, document links, type edges, temporal edges, clone hyperedges); could be split.
SMELL|daedalus/structcore/forest.py|_clone_members handles two input structures ('files' vs 'sites') suggesting potential duplication in cluster input format.
SMELL|tests/test_semantic_route_live.py|Accesses private function `sr._role_vectors_detailed` in CacheRecoveryTests.test_roster_change_invalidates_cached_vectors.
SMELL|tests/test_prose_gate.py|Duplication of TemporaryDirectory setup pattern across multiple test methods.
SMELL|tests/test_mutation_score.py|sys.path.insert(0, ...) side-effect at module load