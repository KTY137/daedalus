"""The one hook entrypoint: ``python -m daedalus.hooks <event>``.

``<event>`` is one of ``session``, ``turn``, ``pre_tool``, ``post_tool``,
``subagent_start``, ``subagent_stop``, ``config_change``, ``pre_compact``. The
harness payload arrives on stdin as JSON; the answer goes to stdout (plain text
for the context-carrying events, a JSON object for the tool/subagent events).
Exit code is always 0: a hook that raises would cost the turn, and nothing here
is worth a turn.

Registered as ``daedalus.hooks`` in the effect-boundary registry; the first
thing ``main`` does is ``begin_effect``. Every invocation appends one ledger
row (``runs/hooks/ledger.jsonl``): event, chars injected, milliseconds, note.
That row is the instrument the design is measured with.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # invoked by path rather than as a module
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from daedalus.hooks import events, tools  # noqa: E402
from daedalus.hooks._common import (  # noqa: E402
    HookResult,
    Timing,
    ledger_append,
    now_iso,
    payload_is_usable,
    read_payload,
    repo_root,
    safe_session_id,
)

HANDLERS = {
    "session": events.session_start,
    "turn": events.user_prompt,
    "pre_tool": tools.pre_tool,
    "post_tool": tools.post_tool,
    "subagent_start": events.subagent_start,
    "subagent_stop": events.subagent_stop,
    "config_change": events.config_change,
    "pre_compact": events.pre_compact,
}

ENTRYPOINT_ID = "daedalus.hooks"
NL = chr(10)


def _refused(prefix: str, exc: BaseException) -> None:
    print(f"[hooks] {prefix}: {type(exc).__name__}: {exc}", file=sys.stderr)


def dispatch(event: str, payload: dict, receipt, *, stdout=None) -> HookResult:
    """Dispatch one event and write its answer. ``receipt`` must be the
    :class:`EffectStartReceipt` that ``begin_effect`` returned for this
    entrypoint: the dispatcher is not callable without an effect start (Codex
    round 2: a bare ``run()`` was a production-callable seam around the
    boundary). Tests obtain a real receipt through ``start_effect``."""
    if getattr(receipt, "entrypoint_id", None) != ENTRYPOINT_ID:
        raise PermissionError("daedalus.hooks.dispatch requires the daedalus.hooks effect receipt")
    stdout = sys.stdout if stdout is None else stdout
    timing = Timing()
    if not payload_is_usable(payload):
        return HookResult(note="unusable-payload")
    handler = HANDLERS.get(event)
    root = repo_root(payload)
    sid = safe_session_id(payload.get("session_id"))
    if handler is None:
        result = HookResult(note=f"unknown-event:{event}")
    else:
        try:
            result = handler(payload, root, sid)
        except Exception as exc:  # noqa: BLE001 - a handler bug must not cost the turn
            result = HookResult(note=f"error:{type(exc).__name__}:{exc}"[:200])
    if result.payload is not None:
        stdout.write(json.dumps(result.payload))
        stdout.write(NL)
    elif result.text:
        stdout.write(result.text)
        if not result.text.endswith(NL):
            stdout.write(NL)
    ledger_append(
        root,
        {
            "ts": now_iso(),
            "session": sid,
            "prompt": str(payload.get("prompt_id") or "")[:36],
            "event": event,
            "chars": result.chars,
            "ms": timing.ms,
            "note": result.note,
        },
    )
    return result


def start_effect():
    """``begin_effect`` for this entrypoint: the receipt, or None after printing
    the refusal to stderr. Imports live inside the try so that an import
    failure is reported like a refusal instead of escaping."""
    try:
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        return begin_effect(
            ENTRYPOINT_ID,
            REGISTRY_BY_ID[ENTRYPOINT_ID].effects,
            (process_guard_boundary_decision(),),
        )
    except Exception as exc:  # noqa: BLE001 - refusal, unknown row, import failure: all reported
        _refused("effect boundary refused or unavailable", exc)
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    event = argv[1] if len(argv) > 1 else ""
    # The effect start is a direct ``begin_effect`` call in THIS function: the
    # conformance scanner anchors on it here; ``start_effect`` is the same
    # call packaged for tests, which must not bypass the boundary either.
    try:
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        receipt = begin_effect(
            ENTRYPOINT_ID,
            REGISTRY_BY_ID[ENTRYPOINT_ID].effects,
            (process_guard_boundary_decision(),),
        )
    except Exception as exc:  # noqa: BLE001 - refusal, unknown row, or import failure: all exit 0
        _refused("effect boundary refused or unavailable", exc)
        return 0
    try:
        payload = read_payload()
        dispatch(event, payload, receipt)
    except Exception as exc:  # noqa: BLE001
        _refused("handler", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
