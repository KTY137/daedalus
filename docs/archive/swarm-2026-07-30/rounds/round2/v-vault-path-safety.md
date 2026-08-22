# Verification: v-vault-path-safety

Source file 'vault-path-safety.py' was not located. All claims are UNDECIDABLE because the implementation cannot be inspected. Locate the file and re-run review.

## Verdicts

- UNDECIDABLE: Trailing dots/spaces only checked per segment before join, but not after path resolution (e.g., 'page.md ' passes segment check but Windows strips space)
- UNDECIDABLE: Reserved device names checked only on stem (seg.split('.')[0].lower()), so 'CON.txt.md' passes (stem='con') but 'CON' is still a device name
- UNDECIDABLE: Windows 8.3 short names allow traversal without '..' (e.g., PROJEC~1/..../Windows/win.ini) - vault_rel does not expand short names
- UNDECIDABLE: Drive-relative paths (C:foo.md) bypass absolute check because they lack leading / and regex requires colon at position 1
- UNDECIDABLE: Case-insensitive collisions on Windows (e.g., PAGE.MD vs page.md) not detected, could overwrite existing page
- UNDECIDABLE: Unicode normalization (e.g., U+FF0E fullwidth dot) not normalized, so trailing dot check can be bypassed
- UNDECIDABLE: TOCTOU between symlink check (probe.is_symlink()) and resolve() - a symlink can be swapped after check
- UNDECIDABLE: UNC paths (//server/share/...) bypass absolute check because they start with // not /
- UNDECIDABLE: Fix TOCTOU by using a single atomic check: open file with O_NOFOLLOW and then resolve, or use os.stat with follow_symlinks=False on all components
- UNDECIDABLE: Reject drive-relative paths (single letter followed by colon, not at start) by checking for colon in any segment
- UNDECIDABLE: Extend reserved device name check to full segment (not just stem) and also check after removing extension
- UNDECIDABLE: Add Windows 8.3 short name expansion via ctypes or subprocess (fsutil) before validation
- UNDECIDABLE: On Windows, case-fold the entire path and check for collisions with existing pages
- UNDECIDABLE: Normalize Unicode (NFD or NFC) before checks, especially for dots and spaces
- UNDECIDABLE: Check trailing dots/spaces on the final resolved path, not just segments
- UNDECIDABLE: Reject UNC paths (starting with // or \\) explicitly
