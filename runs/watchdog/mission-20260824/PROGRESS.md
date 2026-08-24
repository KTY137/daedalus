# Mission ledger 2026-08-24

Continues runs/watchdog/mission-20260823/PROGRESS.md; plan still docs/missions/MISSION_2026-08-23.md until a new one lands.
Standing rule for every session (shepherd, owner order 2026-08-23): one row per finished item, append here; `git diff --cached --stat` before EVERY commit, and NEVER trust a pathspec during a merge (see docs/inventory/2026-08-24/PROVENANCE_910e76dc.md).

| when (UTC) | session | item | HEAD after | note |
|---|---|---|---|---|
| 23:4xZ | (lease/gate session, rows to fill in) | 3e52b768 provenance record; 7b05c7f9 gate1 replay record; 5cea1e61 deny-floor kill-criterion measurement; 4a5fe768 merge(gate0) deny floor admits the evaluator loader | 4a5fe768 | rows appended by the shepherd from git log -- please backfill your own notes |
| 00:55Z | shepherd: B6 "silent deaths" REFUTED -- my process filter matched python.exe, the Store alias runs as python3.10.exe | (running) | runs 2 (00:18) and 3 (01:01) were BOTH alive; run 3 killed to halve the load, run 2 (PID 30560, athena-b6b.out, clone of 910e76dc, --timeout 5400) continues overnight; schtasks/WMI relaunches abandoned (the "locked file" was run 3 holding its redirect -- healthy). Lesson: on this box a liveness probe must match python3.10.exe too |
| 01:35Z | B6 run 2 finished honestly: baseline_red = suite TIMEOUT at 5400 s under double load | (run 5 started) | run 5: --timeout 9000, clone of HEAD (3fd5fd5e), athena-b6e.out; expected wall-clock 20-30 h on this box (13 full-suite runs) -- the real price of an unscoped receipt; liveness probes now match python3.10.exe |
