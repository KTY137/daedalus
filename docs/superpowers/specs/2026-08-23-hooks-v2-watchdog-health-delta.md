# Hooks v2 watchdog health delta

- Work Packet ID: `G0-HOOKS-V2-WATCHDOG-HEALTH-DELTA`
- Classification: `ALIGNED`
- Active gate: Gate 0 — Canonical Kernel
- Owner: repository owner
- Builder: Codex
- Base revision: `5f6bfc06f4cbcccbb2d0e6f770ce58ae24209c41`
- Dependencies: Hooks v2 and the work watchdog from the base revision

## Constitutional fit

This packet touches **One kernel** and **Provenance**. The canonical
`UserPromptSubmit` dispatcher must not turn absent or unreadable watchdog
evidence into a positive health claim. It does not add an entrypoint, store,
policy, guard, or promotion path.

## Scope

In scope:

- `daedalus/hooks/events.py`
- `tests/test_hooks_v2.py`
- this Work Packet

All other paths are forbidden. The packet changes only the interpretation and
delta reporting of `runs/watchdog/health.json`.

## Frozen acceptance matrix

| ID | Condition | Required result |
| --- | --- | --- |
| A1 | first turn and `health.json` is absent | no `WATCHDOG` text and no `last_watchdog` state |
| A2 | a valid alarm was observed, then `health.json` is absent | no clear text; the prior alarm state remains |
| A3 | a valid alarm was observed, then `health.json` is invalid | no clear text; the prior alarm state remains |
| A4 | a valid alarm is followed by valid `{"anomalies": []}` | emit `WATCHDOG: all clear` once and store `[]` |
| A5 | an unchanged valid alarm or unchanged valid clear state | remain quiet |

Failure semantics: missing, unreadable, or structurally invalid health is
unknown. Unknown input neither replaces the last evidenced state nor reports
health. Hook execution remains fail-open and read-only with respect to the
watchdog.

## Baseline

On the base revision, the existing delta test passes (`1 passed`) because it
starts with a valid alarm. A throwaway-repository probe with no health artifact
measured:

```text
health_exists= False
before_has_last_watchdog= False
watchdog_lines= ['WATCHDOG: all clear']
after_last_watchdog= []
```

The historical `python tools/iron_plan_guard.py verify` command is unavailable
because revision 7 retired and removed that guard by owner decision. The plan
remains the semantic authority.

## Verification and rollback

Run the focused watchdog-delta tests, the complete Hooks-v2 suite, and
`git diff --check`. Rollback is one ordinary revert of this packet's commit;
no state migration is required because the stored value remains a list for
every evidenced watchdog observation.

## Builder evidence

- Focused acceptance cases: `2 passed in 9.41s`.
- Complete `tests/test_hooks_v2.py`: `56 passed in 97.29s`.
- `python -m py_compile daedalus/hooks/events.py tests/test_hooks_v2.py`: pass.
- `git diff --check`: pass (only the repository's CRLF conversion warnings).
- Root diff review requested explicit invalid-UTF-8 coverage; that case now
  remains quiet and preserves the last evidenced alarm.
