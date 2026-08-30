# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The one hook entrypoint: ``python -m daedalus.hooks <event>``.

``<event>`` is one of ``session``, ``turn``, ``pre_tool``, ``post_tool``,
``subagent_start``, ``subagent_stop``, ``config_change``, ``pre_compact``. The
harness payload arrives on stdin as JSON; the answer goes to stdout (plain text
for the context-carrying events, a JSON object for the tool/subagent events).
Exit code is always 0: a hook that raises would cost the turn, and nothing here
is worth a turn.

Registered as ``daedalus.hooks`` in the effect-boundary registry; the first
thing ``main`` does is ``begin_effect``. Every DISPATCHED invocation appends one
ledger row (``runs/hooks/ledger.jsonl``): event, chars injected, milliseconds,
note. That row is the instrument the design is measured with.

The one invocation that cannot leave a row is a boundary REFUSAL, and that is
not an oversight: writing the row is itself ``filesystem_write``, the effect
that was just refused. A refusal reports to stderr and nowhere else, because
the alternative is a hook that performs the effect it was denied in order to
record being denied it. An unusable payload does get a row -- see ``dispatch``.
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
    hooks_dir,
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
    usable = payload_is_usable(payload)
    known = payload if isinstance(payload, dict) else {}
    root = repo_root(known)
    sid = safe_session_id(known.get("session_id"))
    if not usable:
        result = HookResult(note="unusable-payload")
    else:
        handler = HANDLERS.get(event)
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
    # An unusable payload gets a row TOO -- but only where the hooks already
    # keep state. It used to return before the ledger and leave no trace at
    # all, so "the dispatcher is being fed garbage" and "the dispatcher was
    # never called" looked identical from the only instrument there is. The
    # directory test is the limit on the fix: creating ``runs/hooks/`` in
    # whatever directory a non-harness process happened to start in would be
    # the hook inventing state outside its own repository.
    if usable or hooks_dir(root).is_dir():
        ledger_append(
            root,
            {
                "ts": now_iso(),
                "session": sid,
                "prompt": str(known.get("prompt_id") or "")[:36],
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


def _utf8_streams() -> None:
    """Answer in UTF-8, whatever the console's legacy codec is.

    [MEASURED 2026-08-25] the turn hook's real stdout was NOT valid UTF-8. The
    architecture delta carries U+00B7 and Windows encoded it as the single
    cp1252 byte 0xB7, which the harness -- which writes its payload as UTF-8
    and reads the answer back the same way -- cannot decode. ``_tree`` had
    already learned this and keeps its own lines ASCII-only, but the delta
    comes from another module and never got that treatment.

    Declaring the encoding fixes every producer at once instead of policing
    each one, and it is the same direction the stdin side was moved on
    2026-08-23. ``errors="replace"`` so an unencodable character degrades to a
    marker rather than raising: nothing here is worth a turn.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    event = argv[1] if len(argv) > 1 else ""
    _utf8_streams()
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
