# Claims about `worktree.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Docstring mismatch: _remove_tree_no_follow claims fresh lstat before every syscall, but retry paths in _force_unlink, _force_rmdir, _unlink_reparse_point do not re-verify, widening the attack window.
2. [risk] _is_reparse_point returns False on OSError/ValueError, failing open. If an error prevents stat'ing a reparse point, it allows traversal into attacker-controlled junctions.
3. [risk] Incomplete code: _remove_tree_no_follow body truncated; could not verify that re-checks at scan, per-child unlink, and rmdir drain are performed as claimed.
4. [risk] GitWorktreeManager and cleanup_worktree not visible; docstring claims about allocation record integrity and identity checks cannot be verified.
5. [risk] _chain_between raises ValueError if target not under root, could propagate unhandled if callers don’t ensure containment.
6. [todo] Request full implementation of _remove_tree_no_follow, including walk loop and _verify_reachable.
7. [todo] Request full GitWorktreeManager implementation to verify containment claims.