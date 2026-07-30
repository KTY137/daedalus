# Claims about `memstore.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Windows sharing violation in _ends_without_newline: opens ledger for reading while another process may have it open for append, causing PermissionError and crashing append instead of gracefully handling torn line.
2. [risk] No cross-process append serialisation: two daemons/processes appending simultaneously can interleave writes, silently corrupting the chain (though hash chain will break, detection is reactive).
3. [risk] _normalize_entry silently drops unexpected keys inside 'trust' dict, which contradicts the strict-reject posture for other sub-dicts; could hide mis-specified callers.
4. [risk] verify_ledger function body absent from provided context; full tamper-evidence guarantee unconfirmed.
5. [todo] Change _ends_without_newline to read last byte without re-opening, or use append-mode with atomic read/write using os.lseek?
6. [todo] Consider file-level lock (e.g., portalocker) on Windows for cross-process append safety.
7. [todo] Implement verify_ledger body or provide it for audit.
8. [todo] Validate trust sub-fields to reject unknown keys.