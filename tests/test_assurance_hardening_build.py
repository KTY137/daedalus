# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""A bound work item id cannot outlive the plan it was derived from.

WHAT WAS WRONG. ``BuildSession.bind_work_items`` wrote an id only into a task
that had none::

    if not task.work_item_id:
        task.work_item_id = derive_work_item_id(...)

which is correct for the case it was written for -- a snapshot reloaded from
disk keeps the ids it was persisted with -- and silently wrong for the case
that actually happens: a session whose tasks are re-planned, re-scoped, re-routed
or re-ordered in place and then bound again. Every such task kept the id derived
from a plan it no longer is. The id is a truncated hash of the task's substance,
so nothing downstream could notice: the mission's ``work_item_ids``, the wave
lease and the ``AttemptContract`` all went on naming a work item whose
objective, owner or declared paths had moved (Invariant 7, read backwards).

The binder now re-derives every time and keeps the full identity digest, so an
unchanged plan is a no-op and a changed one raises with both digests named.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.build import (  # noqa: E402
    BuildSession,
    BuildTask,
    Wave,
    WorkItemIdentityError,
)


def _task(**overrides):
    fields = dict(objective="write the docs", agent="clio", category="docs",
                  lane="local", tier="haiku", builder="ollama", frontier=False,
                  paths=["README.md"])
    fields.update(overrides)
    return BuildTask(**fields)


def _session(*tasks):
    return BuildSession(feature="a feature", repo_root=".", project=None,
                        waves=[Wave(index=0, tasks=list(tasks))],
                        slug="a-feature", created="20260822T000000Z")


def test_binding_an_unchanged_plan_is_a_no_op():
    task = _task()
    session = _session(task)
    bound = task.work_item_id
    digest = task.work_item_identity_sha256

    assert bound and digest
    session.bind_work_items()
    session.bind_work_items()

    assert task.work_item_id == bound
    assert task.work_item_identity_sha256 == digest


@pytest.mark.parametrize("change", [
    {"objective": "write the docs AND ship the release"},
    {"agent": "talos"},
    {"paths": ["README.md", "docs/GUIDE.md"]},
])
def test_a_re_planned_task_cannot_keep_a_stale_id(change):
    task = _task()
    session = _session(task)
    stale = task.work_item_id

    for name, value in change.items():
        setattr(task, name, value)

    with pytest.raises(WorkItemIdentityError) as caught:
        session.bind_work_items()

    message = str(caught.value)
    assert stale in message
    assert task.work_item_identity_sha256 in message


def test_reordering_the_plan_is_also_a_re_plan():
    """The ordinal is part of the identity, so a swap is a substance change."""
    first, second = _task(objective="one"), _task(objective="two")
    session = _session(first, second)
    ids = (first.work_item_id, second.work_item_id)

    session.waves[0].tasks = [second, first]

    with pytest.raises(WorkItemIdentityError):
        session.bind_work_items()
    assert (first.work_item_id, second.work_item_id) == ids


def test_clearing_the_id_is_how_a_caller_re_plans_deliberately():
    task = _task()
    session = _session(task)
    stale = task.work_item_id

    task.objective = "something else entirely"
    task.work_item_id = ""
    task.work_item_identity_sha256 = ""
    session.bind_work_items()

    assert task.work_item_id and task.work_item_id != stale


def test_a_task_cannot_serve_two_missions():
    task = _task()
    _session(task)
    task.mission_id = "mission-somewhere-else"

    with pytest.raises(WorkItemIdentityError, match="cannot serve two missions"):
        _session(task)


def test_a_snapshot_written_before_the_digest_existed_reloads_and_re_binds():
    """Round trip through the wire form, minus the field that did not exist."""
    task = _task()
    session = _session(task)
    wire = task.to_dict()
    assert wire["work_item_identity_sha256"] == task.work_item_identity_sha256
    wire.pop("work_item_identity_sha256")

    reloaded = BuildTask.from_dict(wire)
    assert reloaded.work_item_identity_sha256 == ""

    # Re-binding an unchanged plan derives the same id and fills the digest in,
    # rather than tripping over its absence.
    _session(reloaded)
    assert reloaded.work_item_id == task.work_item_id
    assert reloaded.work_item_identity_sha256 == task.work_item_identity_sha256
    assert session.work_item_ids() == (task.work_item_id,)
