# Mission ledger 2026-08-24

Continues runs/watchdog/mission-20260823/PROGRESS.md; plan still docs/missions/MISSION_2026-08-23.md until a new one lands.
Standing rule for every session (shepherd, owner order 2026-08-23): one row per finished item, append here; `git diff --cached --stat` before EVERY commit, and NEVER trust a pathspec during a merge (see docs/inventory/2026-08-24/PROVENANCE_910e76dc.md).

| when (UTC) | session | item | HEAD after | note |
|---|---|---|---|---|
| 23:4xZ | (lease/gate session, rows to fill in) | 3e52b768 provenance record; 7b05c7f9 gate1 replay record; 5cea1e61 deny-floor kill-criterion measurement; 4a5fe768 merge(gate0) deny floor admits the evaluator loader | 4a5fe768 | rows appended by the shepherd from git log -- please backfill your own notes |
| 00:55Z | shepherd: B6 "silent deaths" REFUTED -- my process filter matched python.exe, the Store alias runs as python3.10.exe | (running) | runs 2 (00:18) and 3 (01:01) were BOTH alive; run 3 killed to halve the load, run 2 (PID 30560, athena-b6b.out, clone of 910e76dc, --timeout 5400) continues overnight; schtasks/WMI relaunches abandoned (the "locked file" was run 3 holding its redirect -- healthy). Lesson: on this box a liveness probe must match python3.10.exe too |
| 01:35Z | B6 run 2 finished honestly: baseline_red = suite TIMEOUT at 5400 s under double load | (run 5 started) | run 5: --timeout 9000, clone of HEAD (3fd5fd5e), athena-b6e.out; expected wall-clock 20-30 h on this box (13 full-suite runs) -- the real price of an unscoped receipt; liveness probes now match python3.10.exe |
| 02:55Z | B6 run 5 baseline_red was REAL and is fixed: the review subjects were not byte-pinned | (run 6 started) | test_repository_head_revision_integration_review hashes seven files by raw blob sha; unpinned they materialise CRLF in every fresh clone (D7 daemon) -- review passed in the worktree, failed in the sandbox from the same commit. All seven pinned -text (b05f80be + 89132d83), census 20/20, fresh clone 29 passed (MEASURED). Run 6: clone of 89132d83, --timeout 9000, athena-b6f.out. Clone also showed the concurrent_begin load flake once (known) |
