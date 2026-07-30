# Verification: v-index

6 claims confirmed, 2 undecidable due to missing code. Notable finding: _collect returns early when max_files=0, risking one-file limit. Full review blocked by missing build_index and truncated _per_file_pass.

## Confirmed / actionable

- Fix _collect returning after one file when max_files=0 by guarding the early exit e.g., `if max_files > 0 and len(out) >= max_files: return out`
- Obtain complete build_index and _per_file_pass code to verify all docstring promises and concurrency issues
- Implement and test exclusion logic for documents/types/wiki from modules, edges, etc. per docstring
- Review _per_file_pass for process pool order correctness and Windows compatibility (currently truncated)
- Add tests for filesystem atomicity with content-keyed cache under concurrent access (e.g., using parallel writes)

## Verdicts

- UNDECIDABLE - docstring guarantees about documents/types/wiki layering cannot be verified without build_index implementation
- CONFIRMED - _collect returns after one file if max_files=0; caller behavior unknown
- UNDECIDABLE - concurrency and Windows file handle issues cannot be assessed with truncated _per_file_pass
- CONFIRMED - Need to ensure document/type/wiki opt-in logic matches all docstring claims (exclusion from modules, edges, etc.)
- CONFIRMED - Need to review _per_file_pass for process pool order correctness and Windows compatibility
- CONFIRMED - Need to test filesystem atomicity with content-keyed cache under concurrent access
- CONFIRMED - Need to obtain complete file including build_index and rest of _per_file_pass
- CONFIRMED - Need to verify max_files handling in _collect and its callers
