# Claims about `gated-writes.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] If offload() finishes with 'escalated_after_verify_fail' and non-empty wrote, the gate catches it, but the patch bytes are still captured as artifact (though not promoted).
2. [risk] The offload-verify gate only checks offload's own verdict; it does not independently verify the patch, relying on offload's verify+rollback cascade as the sole authority.
3. [risk] The name 'gated_writes' implies a write fence, but the module only gates attempts, not writes. Offload() can still auto-land into primary checkout outside a wave.
4. [risk] Phase 2 promotion is opt-in and not wired into KairosScheduler.dispatch() default path, so concurrent writes may bypass promotion entirely.
5. [risk] The curated command gate is only used if provided; otherwise, only the offload-verify gate runs, which is a weak check.
6. [todo] Consider adding a write fence in Phase 1 that prevents offload from auto-landing into primary checkout during a wave.
7. [todo] Ensure that artifact persistence (artifact_dir) does not bypass the primary checkout fence.
8. [todo] Wire Phase 2 promotion into the default dispatch path or document why it is opt-in.
9. [todo] Add independent verification of the patch in the gate, not just offload's verdict.
10. [todo] Clarify naming: rename module to reflect it orders attempts, not fences writes.