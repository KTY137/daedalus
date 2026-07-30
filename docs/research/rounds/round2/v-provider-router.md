# Verification: v-provider-router

Cannot verify claims because provider-router.py is not provided. All verdicts are UNDECIDABLE.

## Verdicts

- UNDECIDABLE: Review-only substring bypass: _is_review_only() matches substrings like 'review' in 'not_review' or 'review_and_apply', allowing write tasks to be misclassified as review-only. File needed: provider-router.py.
- UNDECIDABLE: External write lanes trust: no validation that external_write_lanes_for_repo returns expected values; malformed config could silently disable or enable write lanes. File needed: provider-router.py.
- UNDECIDABLE: Fence dominance threshold bypass: small repos (<20 modules) always keep fence UP, but threshold 0.75 can be gamed by adding many non-fenced files to dilute ratio. File needed: provider-router.py.
- UNDECIDABLE: Model capability mismatch: no check for tool-calling, context window, or modality before routing to a provider (e.g., image task to text-only Ollama). File needed: provider-router.py.
- UNDECIDABLE: Silent fallback on provider failure: decide() degrades to Claude without logging or reporting the original provider failure, making debugging hard. File needed: provider-router.py.
- UNDECIDABLE: No modality routing: objective may require image/audio but provider may not support it; no check exists. File needed: provider-router.py.
