# Verification: v-offload

Verified claims: scoped snapshot risk confirmed; isolate_paths assumption undocumented; write verification gate and after-snapshot are unclear from provided code snippet.

## Confirmed / actionable

- Enforce write-scope in isolate_paths mode or document risk of undetected writes (e.g., by using full-repo snapshot when possible).
- Clarify isolate_paths assumption: add enforcement (e.g., worker path restriction) or explicit documentation of the bypass risk.

## Verdicts

- UNDECIDABLE: write verification gate missing; need full offload.py to see post-run verification step.
- CONFIRMED: scoped snapshot only hashes declared paths, may miss writes outside.
- CONFIRMED: isolate_paths assumption not enforced, just documented.
- UNDECIDABLE: add after-snapshot and diff; need full offload.py to confirm if already present.
