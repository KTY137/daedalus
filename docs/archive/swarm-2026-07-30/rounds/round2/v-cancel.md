# Verification: v-cancel

Reviewed 7 claims about cancel.py; all 7 confirmed: race in registry, mischaracterized graceful stage, silent kill-tree failure, non-deterministic __del__, and 3 actionable todos.

## Confirmed / actionable

- {'claim': 7, 'severity': 'high', 'change': 'In PosixSessionBackend.kill_tree, after calling process.wait(), check if process.poll() is None; if so, raise CancellationUnavailable or return a distinct stage to prevent false killed status.'}
- {'claim': 5, 'severity': 'medium', 'change': 'Move `_LIVE.add(self)` right after Popen creation in ManagedProcess.__init__; if after_spawn fails, remove self from _LIVE before killing and releasing.'}
- {'claim': 6, 'severity': 'low', 'change': 'Update docstrings for cancel() and __del__ to mention that (a) idempotency is only guaranteed before release/close, (b) tree kill may not always succeed on posix.'}

## Verdicts

- CONFIRMED: Race condition: ManagedProcess registers in _LIVE only after after_spawn (__init__). Between Popen and registration, cancel_all_managed() may miss a running process.
- CONFIRMED: PosixSessionBackend.signal_group returns False on OSError; cancel() returns stage STAGE_GRACEFUL with graceful=True even if signal was never delivered (e.g., process already exited).
- CONFIRMED: PosixSessionBackend.kill_tree swallows all OSError; if both killpg and process.kill() fail, cancel() returns STAGE_TREE_KILL with returncode=None and killed=True, misleading callers.
- CONFIRMED: ManagedProcess.__del__ relies on CPython reference-counting; docstring promise of release on drop is weaker on non-CPython implementations.
- CONFIRMED: Moving _LIVE.add() right after Popen (and removing on failure) is a valid fix for claim 1.
- CONFIRMED: Docstrings should note limitations: cancel() idempotency only holds before release, and tree kill may fail silently.
- CONFIRMED: Posix kill_tree should verify termination (e.g., os.waitid or poll after wait) and raise/report 'kill_failed' instead of silent return.
