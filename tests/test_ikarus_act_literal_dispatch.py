"""Literal intent through the imported production shell, not AST copies.

Only conversation lookup and eventual dispatch/voice endpoints are controlled.
The real package, computer-command predicate and shell routing are imported.
These tests do not claim a live vendor or desktop session.
"""
from types import SimpleNamespace

import pytest

from daedalus.orchestration.ikarus import shell


@pytest.fixture
def shell_seam(monkeypatch):
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

    monkeypatch.setattr(shell, "_prior_turn", prior_turn)
    # A wrong affordance must not overrule the actual action predicate.
    monkeypatch.setattr(shell, "classify", lambda message: "enqueue")
    monkeypatch.setattr(shell, "_confirmed_computer_run", lambda *a: (None, ""))
    for name, kind in (("_enqueue", "enqueue"), ("_chat", "chat"), ("_act_offer", "offer")):
        monkeypatch.setattr(shell, name, record(kind))
    return SimpleNamespace(calls=calls, lookups=lookups, objective=objective)


@pytest.mark.parametrize("message", [
    '"yes"', '`yes`', "yes?!", '"build a dialog"', '> run tests',
    'please "build a dialog"', "run tests?!",
])
def test_literal_or_question_cannot_reach_hand_even_with_enqueue_intent(shell_seam, message):
    result = shell._ask_inner("project", message, conversation_id="conversation")
    assert result["kind"] in {"chat", "offer"}
    assert len(shell_seam.calls) == 1
    assert shell_seam.calls[0][0] != "enqueue"
    assert shell_seam.lookups == ["conversation"]


@pytest.mark.parametrize("message", ["yes", "ja!", "do it", "Confirm."])
def test_confirmation_hands_off_the_original_objective(shell_seam, message):
    result = shell._ask_inner("project", message, provider="not-the-executor",
                              conversation_id="conversation")
    assert result == {"kind": "enqueue"}
    assert len(shell_seam.calls) == 1
    _, args, kwargs = shell_seam.calls[0]
    assert args == ("project", shell_seam.objective)
    assert kwargs["act"].confirmation_of == shell_seam.objective
    assert "provider" not in kwargs
    assert shell_seam.lookups == ["conversation"]


@pytest.mark.parametrize("message", ["run tests", 'build a "settings" dialog', "please fix the parser"])
def test_direct_command_preserves_its_own_objective(shell_seam, message):
    assert shell._ask_inner("project", message) == {"kind": "enqueue"}
    assert len(shell_seam.calls) == 1
    assert shell_seam.calls[0][1] == ("project", message)
    assert shell_seam.calls[0][2]["act"].confirmation_of == ""


def test_failed_conversation_lookup_does_not_authorize_dispatch(shell_seam, monkeypatch):
    def unavailable(_):
        raise OSError("conversation store unavailable")
    monkeypatch.setattr(shell, "_prior_turn", unavailable)
    assert shell._ask_inner("project", "yes", conversation_id="conversation") == {"kind": "chat"}
    assert len(shell_seam.calls) == 1
    assert shell_seam.calls[0][0] == "chat"
