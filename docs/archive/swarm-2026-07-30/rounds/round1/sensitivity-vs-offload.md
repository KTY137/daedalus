# Claims about `sensitivity-vs-offload.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] HIGH: _slice_context in daedalus/offload.py depends on sensitivity.lane_for_host to distinguish local vs remote. A false 'trusted' classification allows a remote Ollama endpoint to receive distilled context, defeating the fence's egress controls. The slice is built inside ollama branch but the trust check is only on lane label, not on resolved host connectivity.
2. [risk] MEDIUM: If project policy is not loaded (pol=None), semantic_slice may default to no filtering, potentially including sensitive files in slice. Combined with above, this could leak unredacted content remotely.
3. [todo] Add a direct check in _slice_context that resolves host is actually local (e.g., via socket.gethostbyname) before trusting lane result, to prevent single-point-of-failure bypass.
4. [todo] Write integration test with OLLAMA_HOST set to a remote IP and OFFLOAD_SLICE_TOKENS>0; verify offload refuses to inject slice and logs clear refusal reason.
5. [todo] Audit lane_for_host logic to ensure it correctly identifies loopback, private IPs, and unrouteable addresses; any ambiguity must fail 'untrusted'.
6. [todo] Document that slice wire is dark by default and that enabling it demands explicit host validation in deployment.