# Claims about `picker.py`

Produced by 2 independent review agent(s) (deepseek-chat, deepseek-v4-pro). NONE of this is verified.

1. [risk] High-band sources (work_queue, map_island) can starve low-band but critical hotspots or eval misses forever due to band gap > BAND_SPAN.
2. [risk] No mechanism to escalate a candidate's band based on evidence, so a critical hotspot can never outrank a trivial map_island.
3. [risk] Default cheap sources skip eval and hotspots, so critical defects may never appear in the queue without explicit flags.
4. [risk] Work_queue source is disabled by default, so default queue relies on potentially stale inventory and map state.
5. [risk] Outcome memory reduces offset for failed attempts, creating a feedback loop that may starve hard problems.
6. [risk] Docref source has high band but limited write scope, so it may not address core code issues.
7. [risk] unvalidated evidence structure weakens audit guarantee
8. [risk] silent config masking by _project_config
9. [risk] NaN propagation into score and ranking
10. [risk] TOCTOU on queue file read
11. [todo] Consider adding a mechanism to escalate band based on evidence strength (e.g., if hotspot offset is max, allow band promotion).
12. [todo] Add a test to verify that a critical hotspot with max offset can outrank a trivial map_island candidate if evidence warrants.
13. [todo] Review outcome memory policy: consider not reducing offset for failed attempts on high-importance candidates.
14. [todo] Consider adding a 'starvation detector' that alerts if a low-band candidate has been pending for too long.
15. [todo] Make eval and hotspot sources cheap by default or add a warning when they are disabled.
16. [todo] Audit remaining sources and main loop for docstring alignment
17. [todo] Catch FileNotFoundError when reading queue
18. [todo] Add math.isfinite guard in _candidate
19. [todo] Enforce evidence schema in _candidate
20. [todo] Review resolve_project error handling