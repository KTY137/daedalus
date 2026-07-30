# Claims about `provider-router.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Review-only substring bypass: _is_review_only() matches substrings like 'review' in 'not_review' or 'review_and_apply', allowing write tasks to be misclassified as review-only.
2. [risk] External write lanes trust: no validation that external_write_lanes_for_repo returns expected values; malformed config could silently disable or enable write lanes.
3. [risk] Fence dominance threshold bypass: small repos (<20 modules) always keep fence UP, but threshold 0.75 can be gamed by adding many non-fenced files to dilute ratio.
4. [risk] Model capability mismatch: no check for tool-calling, context window, or modality before routing to a provider (e.g., image task to text-only Ollama).
5. [risk] Silent fallback on provider failure: decide() degrades to Claude without logging or reporting the original provider failure, making debugging hard.
6. [risk] No modality routing: objective may require image/audio but provider may not support it; no check exists.
7. [todo] Log provider failure and fallback reason; consider raising alert or returning error instead of silent fallback.
8. [todo] Add capability check before routing: verify provider supports required tools, context size, and modality.
9. [todo] Improve _is_review_only() to use exact match or NLP-based classification to prevent substring bypass.
10. [todo] Revisit fence dominance logic: add minimum absolute count of fenced modules to prevent gaming.
11. [todo] Validate external_write_lanes_for_repo output against known lane names and schema.
12. [todo] Add modality field to objective metadata and route accordingly.