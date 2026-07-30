# Claims about `containment.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] `_verify_job_config` does not verify `ActiveProcessLimit` or `JobMemoryLimit` values, despite docstring claiming all settings are read back; potential for silently accepting incorrect limits.
2. [risk] If `AssignProcessToJobObject` fails in `_assign_to_job`, the suspended child process is leaked without cleanup, contradicting the lifetime guarantee.
3. [risk] Missing function `_log_as_hex` (called in `_create_process`) raises `NameError`, caught by bare except, resulting in silent loss of debug logging.
4. [todo] Add verification of limit values in `_verify_job_config` for `ActiveProcessLimit` and `JobMemoryLimit`.
5. [todo] Ensure suspended process is terminated if job assignment fails; close handles to avoid resource leak.
6. [todo] Define or remove `_log_as_hex`.