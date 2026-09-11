"""Literal intent regression tests for the existing Ikarus action predicate.

No model, tools, policy, repository mutation or second dispatcher is introduced.
The vocabulary is unchanged; only accidentally cleared input is narrowed.
"""
from copy import deepcopy

import pytest

from daedalus.ikarus_act import may_act


OBJECTIVE = "build a settings dialog"


def offer(objective=OBJECTIVE):
    return {"envelope": {"act_offer": {"objective": objective}}}


@pytest.mark.parametrize("text", ["yes", "ja", "do it", "mach das", "confirm"])
@pytest.mark.parametrize("punctuation", ["?", "?!", "? ! .", "？!", "‽"])
def test_interrogative_affirmative_never_confirms(text, punctuation):
    decision = may_act(text + punctuation, "enqueue", [offer()])
    assert not decision.allowed
    assert decision.confirmation_of == ""


@pytest.mark.parametrize("literal", [
    '"yes"', "'yes'", '“ja”', '„ja“', '«yes»', '»ja«', '‘yes’',
    '`yes`', '```yes```', '> yes', '~~~\nyes\n~~~',
    '"build a settings dialog"', "'run tests'", '“build a settings dialog”',
    '„run tests“', '`run tests`', '```\nrun tests\n```', '> run tests',
    '~~~\nrun tests\n~~~', 'please "build a settings dialog"',
    'hey, just `run tests`', 'bitte „mach das“', '"please run tests"',
    '"build a settings dialog', "'run tests", 'please > run tests',
])
@pytest.mark.parametrize("conversation", [None, [offer()]])
def test_quoted_command_neither_executes_nor_creates_an_offer(literal, conversation):
    decision = may_act(literal, "enqueue", conversation)
    assert not decision.allowed
    assert not decision.suspected
    assert decision.signal == "quoted"
    assert decision.objective == ""
    assert decision.confirmation_of == ""


@pytest.mark.parametrize("text", [
    "yes", "YES!", "ja.", "  Ja   bitte! \n", "Confirm.",
    "do it", "mach das", "yes please", "please do", "go ahead",
])
def test_explicit_confirmation_still_binds_original_objective(text):
    conversation = [offer()]
    original = deepcopy(conversation)
    decision = may_act(text, "chat", conversation)
    assert decision.allowed
    assert not decision.suspected
    assert decision.objective == OBJECTIVE
    assert decision.confirmation_of == OBJECTIVE
    assert conversation == original


@pytest.mark.parametrize("text", [
    "run tests", "please build a dialog", 'build a "settings" dialog',
    "write the user's documentation", "run tests for don't-retry behavior",
    "hey just fix the parser", "**build** a dialog", 'run tests and print "yes"',
])
def test_direct_imperatives_and_quoted_arguments_are_preserved(text):
    decision = may_act(text, "enqueue", [offer("different task")])
    assert decision.allowed
    assert decision.objective == text
    assert decision.confirmation_of == ""


@pytest.mark.parametrize("text", [
    "run tests?", "run tests?!", "please build a dialog? ! .",
    "run tests？", "build a dialog‽", "can you build a dialog",
])
def test_question_is_not_an_imperative(text):
    assert not may_act(text, "enqueue").allowed


@pytest.mark.parametrize("text", ["no", "NO!", "nein.", "don't", "cancel", "lass es"])
def test_plain_declines_remain_declines(text):
    decision = may_act(text, "enqueue", [offer()])
    assert not decision.allowed
    assert not decision.suspected
    assert decision.signal == "declined"


@pytest.mark.parametrize("text", ['"no"', '`cancel`', '> nein', "no?", "nein?!"])
def test_quoted_or_questioning_no_does_not_decline_an_offer(text):
    decision = may_act(text, "chat", [offer()])
    assert not decision.allowed
    assert decision.signal != "declined"


@pytest.mark.parametrize("conversation", [
    None, [], {"envelope": {}}, [offer(), {"envelope": {}}],
    {"envelope": {"act_offer": {"objective": ""}}},
    {"envelope": {"act_offer": "run tests"}},
])
def test_confirmation_does_not_reuse_an_absent_or_older_offer(conversation):
    decision = may_act("yes!", "enqueue", conversation)
    assert not decision.allowed
    assert decision.confirmation_of == ""


@pytest.mark.parametrize("text", ['"yes"', "yes?", "run tests?!", "run tests", "yes"])
def test_intent_label_cannot_override_input_boundary(text):
    decisions = [may_act(text, label, [offer()]) for label in ("chat", "enqueue", "status")]
    assert len({(d.allowed, d.suspected, d.objective, d.confirmation_of) for d in decisions}) == 1
    assert [d.to_dict()["intent"] for d in decisions] == ["chat", "enqueue", "status"]


def test_input_remains_an_exact_objective_not_a_rewritten_command():
    objective = 'build a dialog with label "yes?"'
    decision = may_act(objective, "enqueue")
    assert decision.allowed
    assert decision.objective == objective
