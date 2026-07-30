# Claims about `attempt.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] gitdir redirection via .git file: if TaskAttempt doesn't pass git_dir to _git, a malicious candidate can rewrite .git to point to a path inside the primary checkout's .git, bypassing the overlap guard that only checks cwd vs. repo_root (doc claims no mutating command reaches the repo, but .git corruption is possible).
2. [risk] Missing GIT_ATTR_GLOBAL strip: _git_env leaves GIT_ATTR_GLOBAL intact, so candidate-controlled filter execution may be possible if the operator has that variable set and the candidate can write to the referenced attributes file.
3. [risk] Uncaught TimeoutExpired: _git doesn't handle subprocess timeout; if the caller (TaskAttempt.run) does not catch it, the result may be an unhandled exception, violating the documented 'always returns AttemptResult' contract.
4. [todo] Confirm that TaskAttempt always provides git_dir to _git (resolved via _read_gitdir_pointer) for every mutating git call, or extend the overlap guard to also check the resolved gitdir against the primary checkout.
5. [todo] Finish reviewing the full TaskAttempt implementation to verify ledger ordering, artifact_dir fencing, and runner isolation claims.
6. [todo] Audit TaskAttempt.run to ensure all subprocess exceptions from _git are caught and converted to a failure state.
7. [todo] Add GIT_ATTR_GLOBAL to the _git_env pop list, or set it explicitly to /dev/null (or equivalent on Windows).