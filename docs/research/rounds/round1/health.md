# Claims about `health.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] TOCTOU in `inherited` (line 149): if file is altered between the caller's read and the `stat()` call, the recorded age reflects the new version, not the one whose value was read. This could falsely report a stale value as fresh.
2. [risk] Docstring on exit code 2 (line 213) says `unknown` and `present` land on 2, but `NOT_PROVEN` includes `ABSENT`. Thus an absent optional probe also exits with code 2, contradicting the documented behavior.
3. [risk] The claim 'NOTHING HERE WRITES' and promises about read-only operation on spine ledger/vector index cannot be verified; none of those probes appear in the slice.
4. [risk] `Fact.__post_init__` (line 92) does not reject empty string for `source` on `INHERITED` facts, allowing a fact with no real provenance to pass validation.
5. [todo] Update docstring to include `absent` in the description of exit code 2, or change `NOT_PROVEN` to exclude absents of non‑required probes.
6. [todo] Add atomicity note to `inherited` docstring or consider opening the file once to capture both content and mtime atomically.
7. [todo] Tighten `Fact.__post_init__` to reject empty or whitespace‑only sources.