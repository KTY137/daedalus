# Claims about `index.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] docstring guarantees about documents/types/wiki layering cannot be verified without build_index implementation
2. [risk] _collect will return after one file if max_files=0; unknown if caller defaults to 0 or uses that value
3. [risk] concurrency and Windows file handle issues cannot be assessed with truncated _per_file_pass
4. [todo] Ensure document/type/wiki opt-in logic matches all docstring claims (e.g., exclusion from modules, edges, etc.)
5. [todo] Review _per_file_pass for process pool order correctness and Windows compatibility
6. [todo] Test filesystem atomicity with content-keyed cache under concurrent access
7. [todo] Obtain complete file including build_index and rest of _per_file_pass
8. [todo] Verify max_files handling in _collect and its callers