# G1-IKARUS-35 — Scheduled tasks say whether anything will ever run them

Packet ID: G1-IKARUS-35

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: a425a9b052e8dd95cfc5ec968e2cb3a799fcef2e

Working-tree context: base a425a9b0 is branch `loop/lane11-planner-progress` (G1-IKARUS-32..34); same worktree and interpreter recipe as G1-IKARUS-32

Dependencies: `G1-IKARUS-20` (scheduling; automatic dispatch requires the File Bridge watcher for the exact authority root), `G1-IKARUS-21`/`G1-IKARUS-23` (queue, finite recurrence, autonomy commands), `file_bridge.watch` (the registered watcher door; the desktop never adopts it in v0.1.6)

Stage: owner loop of 2026-09-06, fifth tick, session daedalus-9d.

## Primary acceptance claim

Every chat reply that stores or lists scheduled computer work (`/computer schedule`, `queue`, `every`, `scheduled`, `run-due`) states, from the watcher heartbeat, whether a File Bridge watcher is currently ticking this authority root, and if not, the exact command that would: `Watcher: aktiv für diesen Ordner (PID …, letzter Tick vor … s)` or `Watcher: nicht aktiv (<state>); Aufträge werden nicht automatisch ausgeführt, /computer run-due prüft manuell. Start: python -m daedalus.file_bridge watch --repo-root "<root>"`, with a third form when a watcher runs for a different root. The same facts travel in the envelope as `computer.watcher`. The projection is a fail-open read (an unreadable heartbeat is `unknown`, never `alive`), grants nothing and starts nothing.

Why this is an autonomy packet: the measured state of this installation on 2026-09-06 (below) is that nothing ticks the owner's queued tasks and no reply said so. Section 7.2 of the plan requires unavailable dependencies to be reported as unavailable; the queue's runner was such a dependency, silently.

## Measured

Live, 2026-09-06 04:10, two installations on this box. (1) The lane worktree's own installation (the heartbeat path is derived from the module's root, so each checkout is its own installation): no heartbeat file; \`watcher_projection\` reports \`state: none\`, \`serves_this_root: null\`, \`ticks_this_root: false\`, and the line reads "Watcher: nicht aktiv (none); Aufträge werden nicht automatisch ausgeführt, \`/computer run-due\` prüft manuell. Start: \`python -m daedalus.file_bridge watch --repo-root "<repo>"\`". (2) The main checkout's \`runs/bridge_heartbeat.json\`, read directly: 117,343 s old and naming a pytest temporary directory as \`repo_root\` (a test wrote it on 2026-09-04); through the projection that is \`stale\` for a foreign root, not ticking. Before this packet the same replies said "Der File-Bridge-Watcher dieser Installation führt fällige Aufträge aus", which was false on this box for two days.

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (`watcher_projection`, `_watcher_line`, three chat handlers gain the line and the `watcher` envelope field), three tests in `tests/test_ikarus_computer_loop.py`, one paragraph in `docs/IKARUS_COMPUTER.md`, this packet.

Out of scope and untouched: the watcher itself, `file_bridge.watch`, `computer_schedule.py`, the Kairos scheduler, the desktop (v0.1.6 never adopts a watcher; adopting one is a separate effectful packet with its own registry row), any automatic start of anything.

## Contracts and behavior

- `watcher_projection(authority_root, *, now=None)` reads `daedalus.file_bridge.heartbeat_status(now)` lazily (no module-level import; the census is unchanged) and returns `{state, serves_this_root, ticks_this_root, age_s, pid, watcher_root, restart, detail}`. `serves_this_root` is `None` without a heartbeat, else the resolved-path equality of the heartbeat's `repo_root` and the authority root. `ticks_this_root` is true only for `alive` or `busy` and `serves_this_root`. Any exception in the read yields `state: unknown` with the exception name in `detail`.
- `restart` always names this root, not the heartbeat's, so the owner's copy-paste command serves the tasks they just stored.
- Odysseus (2026-09-06, findings 4 and 5), repaired in the fix-forward commit: a fresh heartbeat whose writer process no longer exists reported `alive`; `_pid_alive` (Windows `OpenProcess`, POSIX `kill 0`) now turns that into `state: dead_pid`, not ticking, with `pid_alive` in the projection (existence, not identity: a reused pid still passes, and the stale window of 120 s bounds the rest). A heartbeat without `repo_root` (`--project` mode) is now worded "läuft ohne Ordnerbindung" instead of naming `None`.
- Replies: the fixed sentence about the watcher is replaced by `_watcher_line(projection)`; the envelope carries `watcher` next to the stored result (`cancel` replies are unchanged, they store nothing to run).
- Unchanged: admission, claims, dispatch, cancellation, the one-mission-per-tick rule, and the fact that a stored task's delivery state is never a success claim.

## Acceptance matrix

| Check | Result (2026-09-06, this worktree) |
| --- | --- |
| three new tests without the change | 3 failed (`AttributeError: watcher_projection`) |
| three new tests with the change | 3 passed |
| loop, adversarial, history, autonomy, schedule and schedule-autonomy suites | 179 passed (53.1 s) |
| import census (`tests/test_imports_graph.py`) | 10 passed, 4 skipped: the file_bridge import is inside the function |
| live projection against this installation | `stale`, other root, not ticking (see Measured) |
| `computer_loop.py` line endings | LF (byte pin respected) |

## Migration and rollback

Additive envelope field and a changed sentence in three replies; no stored artifact changes. Rollback removes the two functions and restores the fixed sentence.

## Evidence, expected failures, and review

Evidence: the acceptance matrix; the live projection output is quoted in Measured (the heartbeat file is runtime state under `runs/`, not retained). Expected failure retained: on this box the projection is `stale` for a foreign root, which is the finding. Review: none yet; the design is a read-only projection of an existing status function and follows the `unavailable` reporting pattern of G1-IKARUS-26. Open, for the owner: whether the desktop should own a watcher (an effectful packet, registry row `file_bridge.watch` exists for the CLI) so that scheduled autonomy works without a terminal.

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above
