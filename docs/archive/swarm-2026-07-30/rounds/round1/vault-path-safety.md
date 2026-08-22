# Claims about `vault-path-safety.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Trailing dots/spaces only checked per segment before join, but not after path resolution (e.g., 'page.md ' passes segment check but Windows strips space)
2. [risk] Reserved device names checked only on stem (seg.split('.')[0].lower()), so 'CON.txt.md' passes (stem='con') but 'CON' is still a device name
3. [risk] Windows 8.3 short names allow traversal without '..' (e.g., PROJEC~1/..\..\..\Windows\win.ini) - vault_rel does not expand short names
4. [risk] Drive-relative paths (C:foo.md) bypass absolute check because they lack leading / and regex requires colon at position 1
5. [risk] Case-insensitive collisions on Windows (e.g., PAGE.MD vs page.md) not detected, could overwrite existing page
6. [risk] Unicode normalization (e.g., U+FF0E fullwidth dot) not normalized, so trailing dot check can be bypassed
7. [risk] TOCTOU between symlink check (probe.is_symlink()) and resolve() - a symlink can be swapped after check
8. [risk] UNC paths (//server/share/...) bypass absolute check because they start with // not /
9. [todo] Fix TOCTOU by using a single atomic check: open file with O_NOFOLLOW and then resolve, or use os.stat with follow_symlinks=False on all components
10. [todo] Reject drive-relative paths (single letter followed by colon, not at start) by checking for colon in any segment
11. [todo] Extend reserved device name check to full segment (not just stem) and also check after removing extension
12. [todo] Add Windows 8.3 short name expansion via ctypes or subprocess (fsutil) before validation
13. [todo] On Windows, case-fold the entire path and check for collisions with existing pages
14. [todo] Normalize Unicode (NFD or NFC) before checks, especially for dots and spaces
15. [todo] Check trailing dots/spaces on the final resolved path, not just segments
16. [todo] Reject UNC paths (starting with // or \\) explicitly