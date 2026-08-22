# Verification: v-memstore

Verified 8 claims about memstore.py: 3 risks confirmed, 1 undecidable (verify_ledger absent). No refuted claims. File has cross-process safety issues, trust key validation missing, and missing verification implementation.

## Confirmed / actionable

- Add cross-process file locking (e.g., portalocker) around ledger append to prevent write interleaving.
- In _ends_without_newline, avoid opening for reading while another process may be appending; use os.lseek on append handle or handle exception.
- In _normalize_entry, validate trust sub-dict keys and reject unknown ones to be consistent with other sub-dict validation.
- Implement verify_ledger function with full tamper-evidence checking and make available in codebase.

## Verdicts

- CONFIRMED: _ends_without_newline opens ledger for reading while another process may append, risking PermissionError on Windows.
- CONFIRMED: No cross-process append serialisation; threading.Lock only per-process, can interleave writes.
- CONFIRMED: _normalize_entry silently drops unexpected keys inside 'trust' dict, contradicting strict rejection for other sub-dicts.
- UNDECIDABLE: verify_ledger function body not present in provided code; full tamper-evidence guarantee cannot be confirmed.
