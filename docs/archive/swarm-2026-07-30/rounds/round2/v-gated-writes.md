# Verification: v-gated-writes

Source file gated-writes.py was not provided; all claims are UNDECIDABLE.

## Verdicts

- UNDECIDABLE: [risk] Claim 1: offload() finishes with 'escalated_after_verify_fail' and non-empty wrote, the gate catches it, but patch bytes still captured.
- UNDECIDABLE: [risk] Claim 2: offload-verify gate only checks offload's own verdict, not independently verify patch.
- UNDECIDABLE: [risk] Claim 3: module only gates attempts, not writes; offload() can auto-land into primary checkout outside a wave.
- UNDECIDABLE: [risk] Claim 4: Phase 2 promotion opt-in and not wired into KairosScheduler.dispatch() default path.
- UNDECIDABLE: [risk] Claim 5: curated command gate only used if provided; otherwise only offload-verify gate runs.
- UNDECIDABLE: [todo] Claim 6: add write fence in Phase 1 that prevents offload from auto-landing during a wave.
- UNDECIDABLE: [todo] Claim 7: ensure artifact persistence does not bypass primary checkout fence.
- UNDECIDABLE: [todo] Claim 8: wire Phase 2 promotion into default dispatch path or document why opt-in.
- UNDECIDABLE: [todo] Claim 9: add independent verification of patch in gate.
- UNDECIDABLE: [todo] Claim 10: rename module to reflect it orders attempts.
