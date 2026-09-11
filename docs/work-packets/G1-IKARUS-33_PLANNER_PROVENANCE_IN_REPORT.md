# G1-IKARUS-33 — The mission report names the planner and whether context left the machine

Packet ID: G1-IKARUS-33

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: ea8b20522c21a16bbb118ef81d6b590bcef9e514

Working-tree context: base ea8b2052 is branch `loop/lane11-planner-progress` (G1-IKARUS-32 on the stage-15b integration); same worktree and interpreter recipe as G1-IKARUS-32

Dependencies: `G1-IKARUS-32` (measure-09 ran Codex over `allow_remote_context`; Momus named the routing question an egress decision the owner must see, not a configuration note), `G1-IKARUS-23` (history views)

Stage: owner loop of 2026-09-06, second tick, session daedalus-9d.

## Primary acceptance claim

Every computer-loop mission report, its content-addressed mission artifact, the chat rendering and the `/computer task` and `/computer tasks` history views state which planner proposed the steps and whether the retained observations left the machine: `planner: {"provider", "model", "remote_context"}`, taken from the admitted capabilities at mission start (the same values the policy digest already binds). The chat report renders one line, `Planner: <provider> (<model>) · Kontext hat den Rechner verlassen: ja|nein`. Reports retained before this packet have no `planner` key and still render. Nothing about routing, admission or the local-only default changes: `_require_context_route` is untouched, and choosing a remote planner remains an explicit owner configuration (`allow_remote_context: true` plus `planner_provider`) that this packet only makes visible after the fact.

Invariant 7 (provenance): material actions carry origin and inputs. Until now the report said how many planner calls ran but not who ran them; measure-09's page content went to OpenAI (and into the Codex CLI's own local rollout files under `~/.codex/sessions/`, a retention the flag does not mention) and nothing in the mission's evidence said so in words.

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (`planner_facts` captured after capability validation, added to the mission artifact and the final report, one line in `_chat_report`), `daedalus/orchestration/ikarus/computer_history.py` (`_project` carries `planner`), three tests in `tests/test_ikarus_computer_loop.py`, one in `tests/test_ikarus_computer_history.py`, one paragraph in `docs/IKARUS_COMPUTER.md`, this packet.

Out of scope and untouched: the policy module, `_require_context_route`, every provider transport, the desktop and web UI (they render the chat text and the history JSON as they are), `daedalus/runtimes/computer.py`, the registry (no door changes).

## Contracts and behavior

- `planner_facts = {"provider": capabilities["planner_provider"], "model": capabilities.get("planner_model"), "remote_context": capabilities.get("allow_remote_context") is True}`, read once after the capability validation and before the mission artifact is stored, so the artifact digest that the ledger claim binds covers it.
- The mission artifact gains `"planner"`; the final report gains `"planner"` next to `proposals`; the `unavailable`, `reconciliation_required` and replayed results are unchanged (the replayed result is the retained report and carries whatever it carried).
- `_chat_report` renders the line only when `report["planner"]` is a dict; `remote_context` is rendered as `ja` only for the boolean `True`, anything else as `nein`. The model is shown in parentheses when set.
- `computer_history._project` copies `stored.get("planner")` into the projection; the binding checks between ledger row, report artifact and mission artifact are unchanged, so a report artifact edited to claim a different planner still fails `terminal report does not bind this mission`.
- Honesty limit, stated: the facts come from the admitted capabilities, not from the transport. A provider that keeps local rollouts (Codex CLI) or a loopback Ollama endpoint that is actually a tunnel are outside what this line can know; it reports the policy decision, not packet captures.

## Acceptance matrix

| Check | Result (2026-09-06, this worktree) |
| --- | --- |
| four new tests without the change | 3 failed (`KeyError: 'planner'` in report, artifact and history; the legacy-report test passes by construction) |
| four new tests with the change | 4 passed |
| loop, history, adversarial, autonomy, schedule and schedule-autonomy suites | 172 passed (58.3 s) |
| ignition-bundle byte pins (`computer_history.py` and `computer_loop.py` are `-text` pinned) | `tests/test_ignition_bundle_gitattributes.py` 8 passed (39.3 s) |
| `tests/test_imports_graph.py` (module census; no import added) | 10 passed, 4 skipped (86.5 s) |

## Migration and rollback

Additive key in two JSON shapes; no stored artifact is rewritten and old reports render without the line. Rollback removes `planner_facts`, the two keys, the chat line and the history field; retained reports with the key are ignored by older readers.

## Evidence, expected failures, and review

Evidence: the acceptance matrix above (no live run: the facts are read from the same capabilities the live runs of G1-IKARUS-32 used, and measure-09's retained report at `docs/evidence/G1-IKARUS-32_PLANNER_PROGRESS_LIVE/computer-loop-measure-09_browser_bounded_codex-planner.json` shows the gap this packet closes: `planner_provider` appears only in the policy echo of the log, never in the report). Expected failure retained: none new. Review status: no independent review yet. Open owner question carried from G1-IKARUS-32: whether the desktop UI should offer the remote planner choice with this line shown before the first mission, not after; this packet does not add UI.

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above
