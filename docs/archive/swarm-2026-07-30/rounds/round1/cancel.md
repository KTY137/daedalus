# Claims about `cancel.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] Race condition: ManagedProcess registers in _LIVE only after Popen and after_spawn succeed. A concurrent cancel_all_managed() may miss a process that is already running (but not yet in _LIVE), violating the guarantee that the sweep kills all contained children. Trigger: rapid spawns and a kill‑switch event in that window.
2. [risk] PosixSessionBackend.signal_group returns False on any OSError (e.g., process already exited), but the CancelResult.stage could be STAGE_GRACEFUL with graceful=True even if the signal was never actually delivered, because the exit might have been coincidental. This mischaracterizes the outcome.
3. [risk] Posix backend kill_tree swallows all OSError; if both killpg and process.kill() fail (e.g., stuck in D state, permission error), cancel returns STAGE_TREE_KILL with returncode=None, and killed property returns True, misleading callers that rely on tree being dead.
4. [risk] ManagedProcess.__del__ relies on deterministic collection, which is not guaranteed on non-CPython implementations; the docstring claim that an orphaned object always kills survivors is therefore weaker than stated.
5. [todo] Move _LIVE.add() earlier (e.g., right after Popen) to close the race, ensuring cancel_all_managed sees every process even if containment fails, and remove on failure.
6. [todo] Clarify docstrings: 'Reliable cancellation' should note limitations on posix when process is unkillable; the idempotency claim only holds before release.
7. [todo] Fix posix kill_tree to verify termination after wait and raise/report if still alive, or return a distinct stage like 'kill_failed'.