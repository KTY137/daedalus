# Gate-0 Work Packet: deterministic UTF-8 hook stdin

- Packet ID: `G0-HOOKS-UTF8-STDIN`
- Classification: `ALIGNED`
- Active gate: Gate 0 — Canonical Kernel
- Owner: Codex builder; repository owner decides merge/promotion
- Base revision: `5f6bfc06f4cbcccbb2d0e6f770ce58ae24209c41`
- Dependency: the registered `daedalus.hooks` dispatcher from hooks v2
- Invariants touched: One kernel, Provenance, Bounded effects

## Scope

In scope:

- `daedalus/hooks/_common.py`
- `tests/test_hooks_v2.py`
- this Work Packet

Forbidden:

- hook settings, event routing, effect-policy or registry changes
- Serena, symlink, watchdog, plan, instruction, and user-settings changes
- merge, push, or promotion

## Primary claim

`read_payload` reads Claude hook JSON bytes as strict UTF-8 independently of
the Windows text-console encoding. Injected text streams remain supported and
empty, malformed, non-object, unreadable, or non-UTF-8 input still fails open
to an empty payload.

## Frozen acceptance matrix

| Case | Expected result |
| --- | --- |
| UTF-8 JSON behind a cp1252 `TextIOWrapper` | exact `München` and emoji values, without mojibake |
| subprocess with `PYTHONIOENCODING=cp1252` and UTF-8 stdin bytes | exact payload round-trip |
| injected `StringIO` | existing dictionary parsing preserved |
| valid direct `BytesIO` | exact payload parsing preserved |
| malformed UTF-8 or malformed JSON | `{}`; no exception |
| UTF-8 BOM | deliberately strict/fail-open to `{}` |
| existing hook, registry, and envelope suites | no packet-attributable regression; retained baseline drift named |

## Baseline

At the base revision, UTF-8 bytes for `C:/München🚀` read through a cp1252
`TextIOWrapper` produced
`C:/MÃ¼nchenðŸš€` (shown by `ascii()` as
`C:/M\xc3\xbcnchen\xf0\u0178\u0161\u20ac`) instead of the original value.
The reproducer exited non-zero before implementation.

## Build, faults, and review

The implementation may change only the byte/text decoding boundary inside
`read_payload`; it must not add an entrypoint or effect. Builder verification
runs the focused regression, the full hooks-v2 suite, and affected registry and
envelope tests. Fault checks cover invalid UTF-8, invalid JSON, and injected
text streams. Review questions: Does any locale-dependent decode remain? Does
binary failure stay fail-open? Did the patch alter event routing or effects?

Rollback is a revert of this packet's single commit. No data migration is
required; hook ledgers and state schemas are unchanged.

## Verification receipts

- Guard receipt: `python tools/iron_plan_guard.py verify` exited non-zero
  because `tools/iron_plan_guard.py` is absent. This is expected under the
  Revision-7 retirement note; the plan and `AGENTS.md` were read directly.
- Baseline reproducer: non-zero, with `C:/M\xc3\xbcnchen...` instead of the
  expected `C:/M\xfcnchen...`.
- Post-build reproducer: exit 0; expected and actual are byte-equivalent after
  UTF-8 decode, including the emoji.
- Focused regressions: `2 passed, 55 deselected`.
- Existing hooks plus registry: `66 passed`.
- Envelope coverage: `6 passed, 1 failed`; the retained failure reports eight
  pre-existing undeclared record producers outside this packet's three-file
  scope. The same combined run completed `72 passed, 1 failed`.
- `py_compile` for `_common.py`, JSON parse of project settings, and
  `git diff --check`: passed.
- Independent read-only review: `SHIP`, with no P0-P2 findings. Its P3 test
  hardenings (real Unicode `StringIO`, direct bytes, empty/non-object JSON, and
  explicit BOM semantics) are included.

## Residual risk

The production dispatcher reads fresh stdin exactly once. A caller that first
partially reads a buffered `TextIOWrapper` and then passes that same wrapper to
`read_payload` can leave the wrapper and its underlying buffer at different
logical offsets; that unsupported test-only pattern is not repaired here.
UTF-8 with a BOM is intentionally rejected to `{}` rather than accepted as
`utf-8-sig`; Claude's hook protocol emits plain UTF-8 JSON bytes.
