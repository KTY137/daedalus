"""Exercise existing shell decision/dispatch functions with dependency doubles.

The functions are compiled from repository source, not reimplemented here.
Only these three functions are loaded to avoid package startup and provider I/O.
This is a routing-seam test, not a live-provider or full HTTP/UI integration test.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus import ikarus_act


@pytest.fixture
def shell_seam():
    source = Path(__file__).resolve().parents[1] / "daedalus" / "ikarus_os.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names = {"_decide", "_route", "_ask_inner"}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in functions} == names
    assert len(functions) == len(names)
    calls = []
    lookups = []
    objective = "build the original settings dialog"

    def prior_turn(conversation_id):
        lookups.append(conversation_id)
        return {"envelope": {"act_offer": {"objective": objective}}}

    def record(kind):
        def called(*args, **kwargs):
            calls.append((kind, args, kwargs))
            return {"kind": kind}
        return called

    class Refused(RuntimeError):
        pass

    namespace = {
        "ikarus_act": ikarus_act,
        "ActDecision": ikarus_act.ActDecision,
        "_prior_turn": prior_turn,
        # Force a wrong intent label: the capability decision must still win.
        "classify": lambda message: "enqueue",
        "_enqueue": record("enqueue"),
        "_chat": record("chat"),
        "_act_offer": record("offer"),
        "core": SimpleNamespace(envelope=record("error")),
        "SHELL_DETERMINISTIC": "deterministic",
        "ProviderStartRefused": Refused,
    }
    selected = ast.Module(body=functions, type_ignores=[])
    exec(compile(selected, str(source), "exec"), namespace)
    return namespace, calls, lookups, objective


@pytest.mark.parametrize("message", [
    '"yes"', '`yes`', "yes?!", '"build a dialog"', '> run tests',
    'please "build a dialog"', "run tests?!",
])
def test_literal_or_question_cannot_reach_hand_even_with_enqueue_intent(shell_seam, message):
    namespace, calls, lookups, _ = shell_seam
    result = namespace["_ask_inner"]("project", message, conversation_id="conversation")
    assert result["kind"] in {"chat", "offer"}
    assert len(calls) == 1
    assert calls[0][0] != "enqueue"
    assert lookups == ["conversation"]


@pytest.mark.parametrize("message", ["yes", "ja!", "do it", "Confirm."])
def test_confirmation_hands_off_the_original_objective(shell_seam, message):
    namespace, calls, lookups, objective = shell_seam
    result = namespace["_ask_inner"]("project", message, provider="not-the-executor",
                                      conversation_id="conversation")
    assert result == {"kind": "enqueue"}
    assert len(calls) == 1
    kind, args, kwargs = calls[0]
    assert args == ("project", objective)
    assert kwargs["act"].confirmation_of == objective
    assert "provider" not in kwargs
    assert lookups == ["conversation"]


@pytest.mark.parametrize("message", ["run tests", 'build a "settings" dialog', "please fix the parser"])
def test_direct_command_preserves_its_own_objective(shell_seam, message):
    namespace, calls, _, _ = shell_seam
    assert namespace["_ask_inner"]("project", message) == {"kind": "enqueue"}
    assert len(calls) == 1
    assert calls[0][1] == ("project", message)
    assert calls[0][2]["act"].confirmation_of == ""


def test_failed_conversation_lookup_does_not_authorize_dispatch(shell_seam):
    namespace, calls, _, _ = shell_seam

    def unavailable(_):
        raise OSError("conversation store unavailable")

    namespace["_prior_turn"] = unavailable
    assert namespace["_ask_inner"]("project", "yes", conversation_id="conversation") == {"kind": "chat"}
    assert len(calls) == 1
    assert calls[0][0] == "chat"
