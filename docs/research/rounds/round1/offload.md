# Claims about `offload.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] write verification gate missing in offload.py; write may succeed without verification
2. [risk] scoped snapshot for parallel dispatch may miss worker writes outside declared paths
3. [todo] clarify isolate_paths assumption and enforce path restriction or document risk
4. [todo] add after-snapshot and diff in offload to verify writes