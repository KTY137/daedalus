# Verification: v-vet

Verified three claims about vet.py: TOCTOU between stat and read confirmed (file size check bypassable); binary detection limited to first 4KB confirmed; docstring accuracy about line drift refuted (docstring correctly describes behavior, no fix needed).

## Confirmed / actionable

- TOCTOU fix: In _scan_file, read file content first (e.g., into memory up to MAX_FILE_BYTES+1) and then check size, or re-stat after read to ensure size hasn't changed.
- Binary detection improvement: Extend heuristic to check entire file for NUL or use python-magic for reliable binary detection, to avoid missing binary files that start with text-like content.

## Verdicts

- CONFIRMED: TOCTOU in _scan_file: stat then read without re-checking size (vet.py; _scan_file function, line ~370).
- CONFIRMED: Binary heuristic only checks first 4096 bytes for NUL, not the whole file, potentially missing later binary indicators (vet.py; _scan_file, line ~382).
- REFUTED: Docstring in scan_text about line number drift is accurate and consistent with the code; no fix required.
