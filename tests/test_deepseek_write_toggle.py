# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import json
import re
from unittest import mock

import pytest

from daedalus.config import (
    external_write_lanes_for_repo,
    resolve_external_write_lanes,
)
from daedalus.providers.deepseek import DeepSeekProvider
from daedalus.provider_router import select_provider
from daedalus.sensitivity import DEFAULT_POLICY


AGENT = {"name": "minos", "call_name": "Minos"}


def _response(content: str) -> str:
    return json.dumps({"content": content})


def _run(provider: DeepSeekProvider, root, paths, **kwargs):
    return provider.run(
        objective=kwargs.pop("objective", "Add the requested note."),
        repo_root=str(root),
        paths=paths,
        agent=AGENT,
        policy=kwargs.pop("policy", DEFAULT_POLICY),
        **kwargs,
    )


@pytest.mark.parametrize(
    "payload, expected",
    [
        (None, ()),
        ({}, ()),
        ({"policy": None}, ()),
        ({"policy": []}, ()),
        ({"policy": {"external_write_lanes": True}}, ()),
        ({"policy": {"external_write_lanes": "deepseek"}}, ()),
        ({"policy": {"external_write_lanes": ["unknown"]}}, ()),
        ({"policy": {"external_write_lanes": [" DeepSeek ", "unknown"]}},
         ("deepseek",)),
    ],
)
def test_external_write_lane_toggle_is_named_and_fail_closed(payload, expected):
    assert resolve_external_write_lanes(payload) == expected


def test_repo_toggle_fails_closed_for_structurally_malformed_json(tmp_path):
    cfg = tmp_path / ".agentenv"
    cfg.mkdir()
    path = cfg / "agentenv.json"

    for malformed in ("[]", '{"policy": []}', "\udcff"):
        path.write_text(malformed, encoding="utf-8", errors="surrogatepass")
        assert external_write_lanes_for_repo(str(tmp_path)) == ()

    path.write_text(
        json.dumps({"policy": {"external_write_lanes": ["deepseek"]}}),
        encoding="utf-8",
    )
    assert external_write_lanes_for_repo(str(tmp_path)) == ("deepseek",)


def test_router_only_grants_deepseek_write_for_explicit_low_risk_opt_in(
    tmp_path,
):
    cfg = tmp_path / ".agentenv"
    cfg.mkdir()
    config_path = cfg / "agentenv.json"
    availability = {
        "claude_cli": True,
        "ollama": False,
        "deepseek": True,
        "codex_cli": False,
    }
    agent = {"name": "minos", "external_ok": True}

    config_path.write_text(
        json.dumps({"policy": {"external_write_lanes": []}}),
        encoding="utf-8",
    )
    default = select_provider(
        agent,
        "Update the note.",
        ["docs/notes.md"],
        availability=availability,
        policy=DEFAULT_POLICY,
        repo_root=str(tmp_path),
    )
    assert (default.provider, default.mode) == ("deepseek", "advisory")

    config_path.write_text(
        json.dumps({"policy": {"external_write_lanes": ["deepseek"]}}),
        encoding="utf-8",
    )
    opted_in = select_provider(
        agent,
        "Update the note.",
        ["docs/notes.md"],
        availability=availability,
        policy=DEFAULT_POLICY,
        repo_root=str(tmp_path),
    )
    mid_risk = select_provider(
        agent,
        "Refactor the note parser.",
        ["docs/notes.md"],
        availability=availability,
        policy=DEFAULT_POLICY,
        repo_root=str(tmp_path),
    )
    review = select_provider(
        agent,
        "Review the note.",
        ["docs/notes.md"],
        availability=availability,
        policy=DEFAULT_POLICY,
        repo_root=str(tmp_path),
    )

    assert (opted_in.provider, opted_in.mode) == ("deepseek", "write")
    assert (mid_risk.provider, mid_risk.mode) == ("deepseek", "advisory")
    assert (review.provider, review.mode) == ("deepseek", "advisory")


def test_advisory_is_still_read_only_even_though_provider_can_write(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("old\n", encoding="utf-8")
    claimed = json.dumps({
        "status": "done",
        "summary": "changed it",
        "files_changed": ["notes.md"],
        "tests_run": ["pytest"],
        "risks": [],
        "todos": [],
        "handoff": {},
    })
    provider = DeepSeekProvider()

    with mock.patch(
        "daedalus.providers.deepseek.chat_completion", return_value=claimed
    ):
        result = _run(provider, tmp_path, ["notes.md"], writable=False)

    assert doc.read_text(encoding="utf-8") == "old\n"
    assert result["report"]["status"] == "needs_review"
    assert result["report"]["files_changed"] == []
    assert result["report"]["tests_run"] == []
    assert result["report"]["handoff"]["suggested_files"] == ["notes.md"]


def test_write_and_rollback_restore_the_exact_original_bytes(tmp_path):
    doc = tmp_path / "notes.md"
    before = b"alpha\r\n\xffomega\r\n"
    doc.write_bytes(before)
    provider = DeepSeekProvider()

    def changed(**kwargs):
        prompt = kwargs["user"]
        current = prompt.split("(current contents):\n", 1)[1]
        return _response(current + "tail\n")

    with mock.patch(
        "daedalus.providers.deepseek.chat_completion", side_effect=changed
    ):
        result = _run(provider, tmp_path, ["notes.md"], writable=True)

    assert result["report"]["files_changed"] == ["notes.md"]
    assert doc.read_bytes() != before
    restored = provider.rollback()
    assert str(doc.resolve()) in restored
    assert doc.read_bytes() == before
    assert provider.rollback_failures == []


def test_new_file_and_new_directories_are_removed_by_rollback(tmp_path):
    target = tmp_path / "docs" / "nested" / "new.md"
    provider = DeepSeekProvider()
    with mock.patch(
        "daedalus.providers.deepseek.chat_completion",
        return_value=_response("# new\n"),
    ):
        result = _run(
            provider, tmp_path, ["docs/nested/new.md"], writable=True)

    assert result["report"]["files_changed"] == ["docs/nested/new.md"]
    assert target.read_text(encoding="utf-8") == "# new\n"
    provider.rollback()
    assert not target.exists()
    assert not target.parent.exists()


def test_secret_in_allowed_file_never_reaches_deepseek(tmp_path):
    secret = "AKIAIOSFODNN7EXAMPLE"
    doc = tmp_path / "notes.md"
    doc.write_text(f"Use `{secret}` for the demo.\n", encoding="utf-8")
    provider = DeepSeekProvider()

    with mock.patch(
        "daedalus.providers.deepseek.chat_completion"
    ) as call:
        result = _run(provider, tmp_path, ["notes.md"], writable=True)

    call.assert_not_called()
    assert secret in doc.read_text(encoding="utf-8")
    assert result["report"]["files_changed"] == []
    assert "refused egress" in result["report"]["summary"]


def test_project_deny_content_never_reaches_deepseek(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("PROJECT-CONFIDENTIAL plan\n", encoding="utf-8")
    policy = dataclasses.replace(
        DEFAULT_POLICY,
        deny_content=tuple(DEFAULT_POLICY.deny_content)
        + (re.compile("PROJECT-CONFIDENTIAL"),),
    )
    provider = DeepSeekProvider()

    with mock.patch(
        "daedalus.providers.deepseek.chat_completion"
    ) as call:
        result = _run(
            provider, tmp_path, ["notes.md"], writable=True, policy=policy)

    call.assert_not_called()
    assert result["report"]["files_changed"] == []
    assert "refused egress" in result["report"]["summary"]


def test_secret_in_objective_blocks_before_any_provider_call(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("ordinary\n", encoding="utf-8")
    provider = DeepSeekProvider()

    with mock.patch(
        "daedalus.providers.deepseek.chat_completion"
    ) as call:
        result = _run(
            provider,
            tmp_path,
            ["notes.md"],
            writable=True,
            objective="Put AKIAIOSFODNN7EXAMPLE in the notes.",
        )

    call.assert_not_called()
    assert result["report"]["status"] == "blocked"
    assert doc.read_text(encoding="utf-8") == "ordinary\n"


def test_secret_in_path_blocks_before_any_provider_call(tmp_path):
    path = "docs/AKIAIOSFODNN7EXAMPLE.md"
    provider = DeepSeekProvider()

    with mock.patch(
        "daedalus.providers.deepseek.chat_completion"
    ) as call:
        result = _run(provider, tmp_path, [path], writable=True)

    call.assert_not_called()
    assert result["report"]["status"] == "blocked"
    assert path in result["report"]["handoff"]["offending"]
    assert not (tmp_path / path).exists()


def test_traversal_and_write_confinement_do_not_call_provider(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    allowed = docs / "notes.md"
    allowed.write_text("old\n", encoding="utf-8")
    confined = dataclasses.replace(DEFAULT_POLICY, write_allow=("tests/",))
    provider = DeepSeekProvider()

    with mock.patch(
        "daedalus.providers.deepseek.chat_completion"
    ) as call:
        escaped = _run(
            provider, tmp_path, ["../escape.md"], writable=True)
        blocked = _run(
            provider,
            tmp_path,
            ["docs/notes.md"],
            writable=True,
            policy=confined,
        )

    call.assert_not_called()
    assert escaped["report"]["files_changed"] == []
    assert blocked["report"]["files_changed"] == []
    assert allowed.read_text(encoding="utf-8") == "old\n"
