# Claims about `offload-slicing.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Per-target budget `max(256, budget // len(targets))` can truncate a large file mid-function, producing a slice that omits critical logic without warning the caller. The meta reports `trimmed_count` but no severity flag.
2. [risk] `include_focus=False` for rewrite tasks omits the focus body; if the neighborhood is empty, the slice is empty but reported as 'injected' with 0 tokens, misleading the caller into thinking context was provided.
3. [risk] Default budget is 0 (disabled); the wire is dark unless `OFFLOAD_SLICE_TOKENS` is set. A caller unaware of this env var will never receive slice context, silently degrading local model performance.
4. [risk] No validation that the slice covers the intended function boundaries; a slice could start after a function's signature or end before its return, leading the model to infer incorrect behavior.
5. [todo] Add a `truncated_severely` boolean to meta when a slice's `trimmed_count` exceeds a threshold (e.g., >50% of tokens) or when the slice omits the first/last line of the target.
6. [todo] For rewrite tasks with `include_focus=False`, ensure the neighborhood slice is non-empty before marking as 'injected'; otherwise, fall back to full slice or report 'skipped'.
7. [todo] Consider adding a function-boundary detection in `semantic_slice` to guarantee that slices start and end at function/class boundaries, preventing mid-function truncation.
8. [todo] Document that `OFFLOAD_SLICE_TOKENS` must be set for the wire to activate; consider logging a warning at startup if the env var is unset.