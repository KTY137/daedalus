# Claims about `council-bus.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Message-loss: _normalize_turn raises ValueError on invalid status (e.g., 'refused' from caller) or missing independence_class. If caller does not catch these, entire write may crash, discarding other turns. Trigger: a misbehaving vendor integration sending 'status'='refused'.
2. [risk] Cross-process chain corruption: _chain_state cache uses file signature; two processes may both read the same tail before either writes, leading to stale prev and broken chain. The lock is process-local. Trigger: simultaneous appends by multiple processes.
3. [risk] Vendor silence not visible: No dispatch/timeout code shown. When a vendor never answers, the system must record 'unavailable' turns. Without it, turns may be absent, violating the invariant of one turn per participant.
4. [risk] Ordering non-deterministic if caller fails to sort: append_round is expected to sort turns; if _chain_records is called directly with unsorted list, chain head becomes non-reproducible. Not visible in slice.
5. [risk] Replay acceptance: No nonce; duplicate bodies are permitted. An attacker replaying a past turn into a new round could be accepted, though round/ts injection may be hard.
6. [todo] Implement try/except around _normalize_turn in dispatch to catch validation errors and record as 'anomaly' instead of crashing.
7. [todo] Verify that vendor timeout/election logic generates 'unavailable' turns for silent vendors.
8. [todo] Enforce that _chain_records is only called with pre-sorted turns, or sort internally.
9. [todo] Implement cross-process locking (e.g., file lock) or ensure only one process writes.
10. [todo] Consider adding round-specific nonce to prevent cross-round replay if necessary.