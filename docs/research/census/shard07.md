# Census shard 7/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_mapping_cli.py|function|test_accept_refuses_to_inherit_a_snapshot_whose_digest_does_not_verify|Verifies --accept refuses to carry forward a hand-edited snapshot.
tests/test_mapping_cli.py|function|test_accept_still_works_on_an_honest_snapshot|Verifies --accept still works on a proper, unmodified snapshot.
tests/test_mapping_cli.py|function|test_accept_refuses_a_snapshot_from_another_schema|Verifies --accept refuses a snapshot with a different schema version.
tests/test_mapping_cli.py|function|test_default_run_writes_the_page_and_the_snapshot|Verifies default run creates HTML page and snapshot file.
tests/test_mapping_cli.py|function|test_default_run_prints_the_drift_before_re_baselining_it|Verifies default run prints drift details before re-baselining.
tests/test_mapping_cli.py|function|test_the_page_never_reads_its_own_output_back|Verifies page content preserves narrative across regenerations.
tests/test_mapping_cli.py|function|test_page_has_no_external_src_or_href|Verifies HTML page has no external src or href (self-contained).
tests/test_mapping_cli.py|function|test_page_carries_both_themes_and_lets_the_toggle_win|Verifies page includes both dark/light theme styles and toggle.
tests/test_mapping_cli.py|function|test_status_vocabulary_is_on_the_page_with_its_meanings|Verifies status vocabulary chips are present on the page.
tests/test_mapping_cli.py|function|test_agent_authored_html_in_source_is_escaped|Verifies HTML in module docstrings is escaped in output.
tests/test_mapping_cli.py|function|test_agent_authored_html_in_the_narrative_is_escaped|Verifies HTML in narrative is escaped.
tests/test_mapping_cli.py|function|test_acceptance_prose_is_escaped|Verifies acceptance reasons with HTML are escaped.
tests/test_mapping_cli.py|function|test_inline_markup_cannot_smuggle_a_tag|Verifies inline markup escapes HTML before applying formatting.
tests/test_mapping_cli.py|function|test_missing_narrative_marks_every_section_absent|Verifies missing narrative causes all sections to show ABSENT.
tests/test_mapping_cli.py|function|test_a_single_missing_section_is_absent_not_omitted|Verifies a single missing section is marked ABSENT, not omitted.
tests/test_mapping_cli.py|function|test_a_keyless_section_still_renders|Verifies a section without a key is still rendered.
tests/test_mapping_cli.py|function|test_narrative_sections_are_addressed_by_key_not_by_wording|Verifies narrative sections are matched by key, not heading text.
tests/test_mapping_cli.py|function|test_narrative_markdown_subset_renders|Verifies narrative markdown (code, bold, table, list) renders correctly.
tests/test_mapping_cli.py|function|test_stamp_reflects_the_fixture_revision|Verifies page stamp shows the fixture's git SHA and branch.
tests/test_mapping_cli.py|function|test_stamp_reads_a_packed_ref|Verifies git stamp reads revision from packed-refs.
tests/test_mapping_cli.py|function|test_stamp_degrades_to_unknown_without_a_repo|Verifies stamp degrades gracefully without a .git directory.
tests/test_mapping_cli.py|function|test_dirty_tree_is_stated_on_the_page|Verifies dirty tree state is indicated on the page.
tests/test_mapping_cli.py|function|test_build_writes_nothing|Verifies render.build does not modify the repo.
tests/test_mapping_cli.py|function|test_the_page_and_the_gate_never_run_two_analyses|Verifies reach and switches analysis is called exactly once per command.
tests/test_mapping_cli.py|function|test_the_reconciliation_is_arithmetic_not_prose|Verifies gate counts are reconcilable via arithmetic over the same data.
tests/test_typegraph_regression.py|function|setUpModule|Sets up temporary cache and second tree, pins environment variables so build flags are explicit.
tests/test_typegraph_regression.py|function|tearDownModule|Restores environment variables and cleans up temporary directories.
tests/test_typegraph_regression.py|class|T1DuplicationIsByteIdentical|Asserts the duplication block is byte-identical between type-off and type-on builds on the fixture tree; verifies the leak creates a cluster out of nothing.
tests/test_typegraph_regression.py|class|T1DuplicationIsByteIdenticalOnANonEmptyTree|Repeats T1 on a generated tree with non-empty duplication block; checks cluster members are not type or field names.
tests/test_typegraph_regression.py|class|TheCatastropheIsReal|Demonstrates that feeding three same-arity dataclasses as CodeUnits to renamed_clusters yields one false cluster, confirming the risk.
tests/test_typegraph_regression.py|class|T2DefsByFileIsByteIdentical|Asserts defs_by_file and imports_by_file are byte-identical; verifies no type or field name enters the resolver table.
tests/test_typegraph_regression.py|class|T2DefsByFileOnTheSecondTree|Repeats T2 on the generated tree; confirms models.py defines no symbols and no class/field names are resolvable.
daedalus/spine/ledger.py|constant|SCHEMA_VERSION|Database schema version, currently 2.
daedalus/spine/ledger.py|constant|STATE_INTENDED|Constant for intent state 'INTENDED'.
daedalus/spine/ledger.py|constant|STATE_COMPLETED|Constant for intent state 'COMPLETED'.
daedalus/spine/ledger.py|constant|STATE_FAILED|Constant for intent state 'FAILED'.
daedalus/spine/ledger.py|constant|TERMINAL_STATES|Tuple of terminal states.
daedalus/spine/ledger.py|constant|ROOT|Repository root path, used for default DB path.
daedalus/spine/ledger.py|constant|DEFAULT_DB_PATH|Default path to spine.sqlite3.
daedalus/spine/ledger.py|constant|DEFAULT_BUSY_TIMEOUT_MS|Default busy timeout in ms.
daedalus/spine/ledger.py|constant|PREDICATE_SPINE_INTENT|Re-exported predicate type from envelope.
daedalus/spine/ledger.py|function|canonical_json|Re-exported canonical JSON serialiser.
daedalus/spine/ledger.py|function|canonical_sha|Re-exported SHA256 of canonical JSON.
daedalus/spine/ledger.py|function|current_trace_id|Re-exported current trace ID.
daedalus/spine/ledger.py|function|statement|Re-exported ITE-6 statement builder.
daedalus/spine/ledger.py|function|subject_for|Re-exported subject builder.
daedalus/spine/ledger.py|class|SpineError|Base exception for ledger refusals.
daedalus/spine/ledger.py|class|UnknownIntent|Raised when no intent with given id exists.
daedalus/spine/ledger.py|class|IntentAlreadyResolved|Raised when resolving an already-terminal intent.
daedalus/spine/ledger.py|class|Intent|Dataclass representing a recorded intent with current state.
daedalus/spine/ledger.py|class|IntentEvent|Dataclass representing a single intent event.
daedalus/spine/ledger.py|class|SpineLedger|Crash-safe ledger managing SQLite storage of intents and events.
daedalus/spine/ledger.py|function|default_db_path|Returns the ledger path, overridable by env var.
daedalus/mapping/spectral.py|constant|HAVE_MATH|Indicates whether the math extra (networkx) is available.
daedalus/mapping/spectral.py|constant|MATH_EXTRA_HINT|Installation hint string for the math extra.
daedalus/mapping/spectral.py|constant|DEFAULT_TRIALS|Default number of random partition trials for modularity baseline.
daedalus/mapping/spectral.py|constant|DEFAULT_SEED|Default random seed for reproducibility.
daedalus/mapping/spectral.py|constant|DEFAULT_K_MAX|Maximum number of eigenvalues to consider for eigengap heuristic.
daedalus/mapping/spectral.py|function|graph_from_edges|Builds an undirected networkx graph from a source-to-targets mapping.
daedalus/mapping/spectral.py|function|graph_from_reach|Builds an undirected networkx graph from a ReachReport, optionally scoped to prefixes.
daedalus/mapping/spectral.py|function|declared_partition|Groups modules by their declared directory package using inventory._area_of.
daedalus/mapping/spectral.py|function|fiedler_report|Returns algebraic connectivity, Fiedler vector, and boundary agreement per package.
daedalus/mapping/spectral.py|function|modularity_report|Returns Newman modularity Q of declared partition vs random partitions.
daedalus/mapping/spectral.py|function|conductance_report|Returns per-package leak rate and symmetric conductance.
daedalus/mapping/spectral.py|function|eigengap_report|Returns cluster count estimate from normalized Laplacian eigengap heuristic.
daedalus/memstore.py|constant|ENTRY_VERSION|Specifies the version of the memory entry format.
daedalus/memstore.py|constant|STATE_VERSION|Specifies the version of the memory state format.
daedalus/memstore.py|constant|ROOT|Root path of the project parent directory.
daedalus/memstore.py|constant|DEFAULT_LEDGER_PATH|Default path to the ledger JSONL file.
daedalus/memstore.py|constant|DEFAULT_STATE_PATH|Default path to the state JSON file.
daedalus/memstore.py|constant|MEM_CONFIRM_THRESHOLD|Minimum confirmations before promotion from quarantine.
daedalus/memstore.py|constant|LAYERS|Tuple of memory layer names: episodic, semantic, procedural.
daedalus/memstore.py|constant|KINDS|Tuple of allowed entry kinds.
daedalus/memstore.py|function|append_entry|Appends one memory entry with secret floor check, returns id.
daedalus/memstore.py|function|append_confirm|Appends a confirmation record for an entry id.
daedalus/memstore.py|function|append_flag|Appends a flag record with failure list for an entry.
daedalus/memstore.py|function|load_ledger|Reads all ledger records, skipping torn lines.
daedalus/memstore.py|function|ledger_head|Returns (count, head_entry_sha) for tamper evidence.
daedalus/memstore.py|function|verify_ledger|Walks the chain and returns (ok, failures) detecting tampering.
daedalus/eval/graph_delta.py|constant|DELTA_VERSION|Identifies the version of the delta measurement ('1').
daedalus/eval/graph_delta.py|function|load_mutations|Imports the mutation corpus from tools/gate_discrimination.py without copying.
daedalus/eval/graph_delta.py|class|LayerDelta|Represents what moved in one layer (added/removed names).
daedalus/eval/graph_delta.py|class|DeltaResult|Aggregates mutation measurement with detection status and layers.
daedalus/eval/graph_delta.py|function|measure|Applies one mutation in memory and reports deltas per layer.
daedalus/eval/graph_delta.py|function|run|Runs the measurement over all mutations and returns aggregated results.
daedalus/eval/graph_delta.py|function|render|Formats results as a human-readable string.
daedalus/eval/graph_delta.py|function|main|CLI wrapper that runs measurement and writes JSON evidence.
daedalus/structcore/slice.py|module|slice|module that provides semantic_slice and estimate_tokens for distill-to-context
daedalus/structcore/slice.py|function|estimate_tokens|estimates token count using tiktoken or heuristic
daedalus/structcore/slice.py|function|semantic_slice|assembles a semantic slice of a target with focus, neighbors, budget, and egress gating
tests/test_generated_inventory.py|constant|ROOT|Resolved path to repo root
tests/test_generated_inventory.py|constant|FIXTURE_SHA|Fixed SHA for test git head
tests/test_generated_inventory.py|constant|FIXTURE_BRANCH|Fixed branch name for test git
tests/test_generated_inventory.py|constant|BASE|Base file dictionary for mk fixture
tests/test_generated_inventory.py|constant|OLD_HANDWRITTEN|Example old schema inventory for harvest tests
tests/test_generated_inventory.py|function|mk|Creates file structure from dict
tests/test_generated_inventory.py|function|fake_git|Creates minimal .git with SHA and branch
tests/test_generated_inventory.py|function|built|Calls inventory.build with defaults
tests/test_generated_inventory.py|function|statuses|Extracts module-to-status mapping from doc
tests/test_generated_inventory.py|function|features|Returns all features from doc areas
tests/test_generated_inventory.py|function|test_status_comes_from_reachability_not_from_a_human|Asserts status derived from reachability analysis
tests/test_generated_inventory.py|function|test_every_count_matches_the_list_beside_it|Asserts counts alignment with feature lists
tests/test_generated_inventory.py|function|test_the_prose_lists_cannot_disagree_with_the_structured_entries|Asserts prose lists match structured entries
tests/test_generated_inventory.py|function|test_unreached_is_the_count_a_deleted_test_cannot_lower|Asserts unreached count is invariant under test deletion
tests/test_generated_inventory.py|function|test_two_builds_over_one_tree_are_byte_identical|Asserts deterministic output
tests/test_generated_inventory.py|function|test_the_generator_analyses_the_way_the_product_does|Asserts generator uses index-based analysis
tests/test_generated_inventory.py|function|test_editing_a_derived_field_breaks_the_digest|Asserts digest failure on derived field edit
tests/test_generated_inventory.py|function|test_editing_a_derived_list_breaks_the_digest|Asserts digest failure on derived list edit
tests/test_generated_inventory.py|function|test_editing_a_human_field_does_not_break_the_digest|Asserts digest tolerance for human fields
tests/test_generated_inventory.py|function|test_repo_state_head_is_covered_by_the_digest|Asserts head is digest-covered
tests/test_generated_inventory.py|function|test_repo_state_dirty_is_not_covered|Asserts dirty is not digest-covered
tests/test_generated_inventory.py|function|test_an_annotation_cannot_set_a_status|Asserts annotation cannot override derived status
tests/test_generated_inventory.py|function|test_annotation_overreach_is_reported_not_swallowed|Asserts overreaching annotation fields are reported
tests/test_generated_inventory.py|function|test_a_narrative_feature_can_never_be_ranked|Asserts narrative features not in work queue
tests/test_generated_inventory.py|function|test_the_harvest_places_every_hand_written_feature|Asserts count conservation during harvest
tests/test_generated_inventory.py|function|test_no_hand_written_rationale_is_lost|Asserts all notes survive harvest
tests/test_generated_inventory.py|function|test_one_feature_naming_several_modules_annotates_all_of_them|Asserts multi-module feature annotates all
tests/test_generated_inventory.py|function|test_a_second_harvest_is_idempotent|Asserts second harvest matches first
tests/test_generated_inventory.py|function|test_a_harvested_note_reaches_the_generated_feature|Asserts harvested note appears in generated feature
tests/test_generated_inventory.py|function|test_a_promised_package_that_is_not_on_disk_is_stale|Asserts packaging ghost detected as stale
tests/test_generated_inventory.py|function|test_bytecode_whose_sources_are_gone_is_stale|Asserts orphan bytecode detected as stale
tests/test_generated_inventory.py|function|test_bytecode_beside_live_sources_is_not_stale|Asserts sibling source prevents stale detection
tests/test_generated_inventory.py|function|test_a_package_missing_from_the_wheel_is_reported_but_not_queued|Asserts unlisted package reported but not stale
tests/test_generated_inventory.py|function|test_check_fails_when_nothing_generated_the_file|Asserts check fails on missing inventory
tests/test_generated_inventory.py|function|test_check_fails_on_a_file_that_is_not_json|Asserts check fails on non-JSON file
tests/test_generated_inventory.py|function|test_check_fails_on_the_previous_schema|Asserts check fails on old schema
tests/test_generated_inventory.py|function|test_check_is_clean_immediately_after_a_refresh|Asserts check clean after refresh
tests/test_generated_inventory.py|function|test_check_catches_a_hand_edited_status|Asserts check detects hand-edited status
tests/test_generated_inventory.py|function|test_check_catches_a_tree_that_moved_under_the_file|Asserts check detects tree changes
tests/test_generated_inventory.py|function|test_the_generated_file_records_the_revision_it_was_generated_against|Asserts file records head and branch
tests/test_generated_inventory.py|function|test_the_picker_can_still_read_the|Asserts picker can read generated file (incomplete test name)
daedalus/spine/bootstrap.py|constant|ROOT|Path to the repository root
daedalus/spine/bootstrap.py|constant|DISCRIMINATION_REL_PATH|Path where discrimination measurement is recorded
daedalus/spine/bootstrap.py|constant|CRITICAL_DEFECT_CLASSES|Defect classes that must be killed completely for gate to be proven
daedalus/spine/bootstrap.py|constant|KILL_RATE_FLOOR|Overall kill rate floor (0.80)
daedalus/spine/bootstrap.py|constant|EXIT_OK|Exit code 0 for success
daedalus/spine/bootstrap.py|constant|EXIT_NO_CANDIDATE|Exit code 2 when no candidate produced
daedalus/spine/bootstrap.py|constant|EXIT_SOURCES_UNAVAILABLE|Exit code 3 when sources unavailable
daedalus/spine/bootstrap.py|constant|EXIT_ERROR|Exit code 1 for error
daedalus/spine/bootstrap.py|class|SourceRefresh|Records what regeneration was attempted and succeeded
daedalus/spine/bootstrap.py|class|GateDiscrimination|Records whether gate has been shown to discriminate
daedalus/spine/bootstrap.py|class|ShadowResult|Represents one shadow iteration, never promotes
daedalus/spine/bootstrap.py|function|refresh_sources|Regenerates derived sources so the circle can start
daedalus/spine/bootstrap.py|function|gate_discrimination|Reads discrimination receipt and judges it
daedalus/structcore/clones.py|function|normalize_source|Normalizes source text by stripping comments and whitespace for fingerprint comparison.
daedalus/structcore/clones.py|function|fingerprint|Returns a short SHA1 hash of normalized source for exact clone detection.
daedalus/structcore/clones.py|function|abstract_normalize|Returns abstracted token string with identifiers/literals replaced by placeholders.
daedalus/structcore/clones.py|function|abstract_fingerprint|Returns SHA1 hash of abstracted tokens for renamed clone detection.
daedalus/structcore/clones.py|function|token_bag|Returns Counter of abstracted tokens for near-miss overlap computation.
daedalus/structcore/clones.py|class|CloneMemo|Caches exact and abstract fingerprints per unit to avoid recomputation across passes.
daedalus/structcore/clones.py|function|unit_clusters|Groups units by exact fingerprint into clone clusters.

## DEPENDS

DEPENDS|daedalus/structcore/slice.py|graph (daedalus/structcore/graph.py)
DEPENDS|tests/test_generated_inventory.py|daedalus.mapping.drift
DEPENDS|tests/test_generated_inventory.py|daedalus.mapping.inventory
DEPENDS|tests/test_generated_inventory.py|daedalus.mapping.reach
DEPENDS|tests/test_generated_inventory.py|daedalus.mapping.render
DEPENDS|daedalus/spine/bootstrap.py|daedalus.config
DEPENDS|daedalus/spine/bootstrap.py|daedalus.spine.picker
DEPENDS|daedalus/spine/bootstrap.py|daedalus.spine.attempt
DEPENDS|daedalus/structcore/clones.py|daedalus.structcore.languages
DEPENDS|daedalus/structcore/clones.py|daedalus.structcore.parse
DEPENDS|daedalus/structcore/artifacts.py|csv, io, json, re, struct, dataclasses, pathlib (stdlib only).
DEPENDS|daedalus/progress_sources.py|daedalus.progress
DEPENDS|daedalus/progress_sources.py|daedalus.health
DEPENDS|daedalus/progress_sources.py|daedalus.spine.ledger
DEPENDS|daedalus/progress_sources.py|daedalus.spine.attempt (conditional)
DEPENDS|tests/test_ollama_native.py|daedalus.providers._ollama_native
DEPENDS|tests/test_ollama_native.py|daedalus.providers._openai_compat
DEPENDS|tests/test_ollama_native.py|daedalus.providers.ollama
DEPENDS|tests/test_spine_picker.py|daedalus.spine.picker
DEPENDS|tests/test_spine_picker.py|pytest
DEPENDS|tests/test_loop.py|daedalus.loop
DEPENDS|tests/test_loop.py|daedalus.core
DEPENDS|tests/test_loop.py|daedalus.spine.picker
DEPENDS|tests/test_loop.py|daedalus.kairos.scheduler
DEPENDS|tests/test_loop.py|daedalus.progress
DEPENDS|tests/test_spine_return_arc.py|daedalus.spine.picker
DEPENDS|tests/test_spine_return_arc.py|daedalus.spine.ledger
DEPENDS|tests/test_spine_return_arc.py|daedalus.spine.attempt
DEPENDS|daedalus/tools/vet.py|daedalus.sensitivity
DEPENDS|tests/test_ikarus_shells.py|daedalus.health
DEPENDS|tests/test_ikarus_shells.py|daedalus.ikarus_os
DEPENDS|tests/test_ikarus_shells.py|daedalus.ikarus_act
DEPENDS|tests/test_projection_worker.py|daedalus.memory.embeddings
DEPENDS|tests/test_projection_worker.py|daedalus.memory.projection_worker

## WRITES

WRITES|daedalus/spine/ledger.py|SQLite database at self.path (default runs/spine/spine.sqlite3)
WRITES|daedalus/memstore.py|memory/ledger.local.jsonl
WRITES|daedalus/eval/graph_delta.py|runs/eval/graph_delta.json
WRITES|tests/test_generated_inventory.py|Repo files under tmp_path (e.g., pkg/wired.py, tests/test_main.py)
WRITES|tests/test_ollama_native.py|temporary directories (via tempfile)
WRITES|tests/test_loop.py|tests/test_loop.py/_looptmp/

## READS

READS|daedalus/spine/ledger.py|Read-only mode still creates -wal/-shm sidecars; file content unchanged but filesystem is touched.
READS|daedalus/memstore.py|memory/ledger.local.jsonl
READS|daedalus/eval/graph_delta.py|tools/gate_discrimination.py
READS|daedalus/eval/graph_delta.py|git log and diff-tree (via subprocess)
READS|daedalus/eval/graph_delta.py|mutation.file path (any file in repo)
READS|daedalus/structcore/slice.py|reads source files from disk via _read() within root
READS|tests/test_generated_inventory.py|Repo files under tmp_path
READS|daedalus/spine/bootstrap.py|docs/architecture-state.json
READS|daedalus/spine/bootstrap.py|runs/spine/gate_discrimination.json
READS|tests/test_ollama_native.py|temporary files (via Path read_bytes)

## CLAIMS

CLAIMS|tests/test_generated_inventory.py|A promised package not on disk is stale (test_a_promised_package_that_is_not_on_disk_is_stale)
CLAIMS|tests/test_generated_inventory.py|Bytecode whose sources are gone is stale (test_bytecode_whose_sources_are_gone_is_stale)
CLAIMS|tests/test_generated_inventory.py|Bytecode beside live sources is not stale (test_bytecode_beside_live_sources_is_not_stale)
CLAIMS|tests/test_generated_inventory.py|A package missing from the wheel is reported but not queued (test_a_package_missing_from_the_wheel_is_reported_but_not_queued)
CLAIMS|tests/test_generated_inventory.py|Check fails on missing file, bad JSON, old schema, hand-edited status, and moved tree (multiple tests)
CLAIMS|daedalus/spine/bootstrap.py|This module never promotes candidates.
CLAIMS|daedalus/spine/bootstrap.py|It refuses to accept a green gate as evidence of quality.
CLAIMS|daedalus/spine/bootstrap.py|It never writes the primary checkout.
CLAIMS|daedalus/spine/bootstrap.py|Absent discrimination evidence is reported as unproven, never as fine.
CLAIMS|daedalus/structcore/clones.py|window_clusters works for any language without parser by sliding normalized line windows.
CLAIMS|daedalus/structcore/clones.py|normalize_source uses tokenize for Python for precise normalization.
CLAIMS|daedalus/structcore/artifacts.py|Refuse to guess. A literal that does not resolve to a file present in the file set is DROPPED and COUNTED, never bound to a near-match.
CLAIMS|daedalus/structcore/artifacts.py|Metadata only, never the payload. Schema reads are bounded by MAX_SCHEMA_BYTES and stop at the header. This layer never ingests data.
CLAIMS|daedalus/structcore/artifacts.py|Reading is not executing. No file here is imported, run, or evaluated. But parsing a hostile binary is still an attack surface, so every reader is bounded and failure is reported as unreadable, never as an empty schema.
CLAIMS|daedalus/structcore/artifacts.py|Artefacts are not code. Artefact nodes get their own id namespace and never enter modules, import_edges, all_units or the symbol resolver.
CLAIMS|daedalus/structcore/artifacts.py|A bounded read can truncate valid JSON, so say which it was.
CLAIMS|daedalus/progress_sources.py|Never edits, wraps internals, or monkeypatches the modules it reads.
CLAIMS|daedalus/progress_sources.py|Each snapshot function stamps observed_at/recomputes age at call time; nothing memoises results across calls.
CLAIMS|daedalus/progress_sources.py|No function reads worker's self-reported files_changed.
CLAIMS|daedalus/progress_sources.py|Between track_call's CLAIMED and result, no finer-grained progress is fabricated.
CLAIMS|daedalus/preservation.py|module is pure and offline (no I/O, no network) per module docstring
CLAIMS|daedalus/preservation.py|check_preservation is pure and offline per its docstring
CLAIMS|tests/test_ollama_native.py|'Everything is offline: a stdlib http.server on an ephemeral port stands in for Ollama...'
CLAIMS|tests/test_spine_picker.py|ORDER IS REPRODUCIBLE: same inputs produce same queue.
CLAIMS|tests/test_spine_picker.py|NOTHING RUNS UNLESS ASKED: dry-run tests prove no attempt via exception.
CLAIMS|tests/test_loop.py|Covers, in the order the brief ranked them: 1. the stop, 2. the bounds, 3. governance, 4. convergence, 5. observability
CLAIMS|daedalus/tools/vet.py|Static only, never executes anything
CLAIMS|daedalus/tools/vet.py|Fail-closed: unknown is not clean
CLAIMS|daedalus/tools/vet.py|Findings not scores
CLAIMS|daedalus/tools/vet.py|No policy about hosts; delegates to sensitivity.lane_for_host
CLAIMS|tests/test_projection_worker.py|Adversarial tests for the memory -> vector-index projection worker.
CLAIMS|tests/test_council_canary.py|Offline tests for the vendor canary with no network, no Ollama, no vendor CLI, no CLI entry point; tests truncation, anchoring, unavailable/wrong_answer distinction, budget, history, and dry-run.

## UNWIRED

UNWIRED|daedalus/gui_catalogue.py|SearchResult (listed in __all__ but no definition in visible excerpt)
UNWIRED|daedalus/gui_catalogue.py|load_catalogue (listed in __all__ but no definition in visible excerpt)
UNWIRED|daedalus/gui_catalogue.py|parse_entry (listed in __all__ but no definition in visible excerpt)
UNWIRED|daedalus/gui_catalogue.py|search (listed in __all__ but no definition in visible excerpt)
UNWIRED|daedalus/gui_catalogue.py|render_for_prompt (listed in __all__ but no definition in visible excerpt)
UNWIRED|daedalus/conversation.py|new_conversation_id
UNWIRED|daedalus/council/bus.py|canonical_body (public function only called internally)
UNWIRED|daedalus/council/bus.py|canonical_body_json (public function only called internally)

## SMELL

SMELL|tests/test_killswitch.py|Multiple test functions for similar stop conditions are repetitively written instead of being parameterized.
SMELL|tests/test_gate_containment.py|File truncated at end; function test_the_attestation_records_MEASURED_facts incomplete.
SMELL|tests/test_gate_containment.py|Unused import: uuid (not referenced in visible code)
SMELL|daedalus/eval/graph_delta.py|Similar flattening of Counter to set in _literal_keys, _structure_keys, _ast_refs; could be abstracted.
SMELL|daedalus/structcore/slice.py|_whole_repo_tokens fallback uses chars//4 which may produce inconsistent token counts vs slice_tokens, affecting reduction_pct accuracy