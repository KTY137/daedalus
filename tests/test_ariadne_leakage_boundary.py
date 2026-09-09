"""Master plan section 8.1's self-Renovation leakage boundary is code, not prose.

Before G1-ARIADNE-10 the only target admission an Ariadne campaign performed
was shape plus the mandatory ignored roots (``.git``, ``.daedalus``); a
candidate could have named ``daedalus/spine/...`` or the master plan itself.
The boundary is a pure refusal inside :func:`_admit_target_path`, so it fires
before the repository, HEAD or any effect lease is observed -- the same
discipline the ignored-root refusal already has.
"""
from __future__ import annotations

import pytest

import daedalus.ariadne.campaign as module
from daedalus.ariadne.campaign import (
    SELF_RENOVATION_PROTECTED_PREFIXES,
    AriadneRequestError,
    _admit_target_path,
    protected_prefix_for,
)

REV = "a" * 40

PROTECTED = (
    "daedalus/spine/effect_boundary.py",
    "daedalus/kernel/policy/pricing.py",
    "daedalus/kernel/promotion.py",
    "daedalus/kernel/promotion_trust_root.py",
    "daedalus/kernel/promotion_execution.py",
    "daedalus/kernel/approvals.py",
    "daedalus/kernel/contracts/security.py",
    "daedalus/ariadne/campaign.py",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
    "AGENTS.md",
    "CLAUDE.md",
    ".agentenv/agentenv.json",
    ".agentenv/tool-allowances.json",
    "tests/test_ariadne_campaign_v0.py",
    "tests/test_ariadne_cli_exit_codes.py",
    "tests/test_ariadne_leakage_boundary.py",
    "DAEDALUS/SPINE/ledger.py",
    "Docs/IKARUS_ARIADNE_MASTER_PLAN.md",
)

ADMITTED = (
    "daedalus/providers/codex_cli.py",
    "daedalus/orchestration/ikarus/shell.py",
    "daedalus/ariadne/__init__.py",
    "daedalus/kernel/artifacts.py",
    "docs/STATUS.md",
    "docs/work-packets/G1-SELF-01_DOCSTRING_SYMBOL_DRIFT.md",
    "tests/test_eval.py",
    "README.md",
)


@pytest.mark.parametrize("target_path", PROTECTED)
def test_protected_target_is_refused_before_read_or_effect(
    tmp_path, monkeypatch, target_path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        module,
        "read_repository_source",
        lambda *_args: pytest.fail("protected target reached repository read"),
    )
    monkeypatch.setattr(
        module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: pytest.fail("protected target reached effect admission"),
    )

    with pytest.raises(AriadneRequestError, match="leakage boundary"):
        module.run_campaign(
            repo_root=root,
            source_revision=REV,
            campaign_id="protected-target",
            target_path=target_path,
            before="before",
            after="after",
        )
    # A refused request leaves no trace: no clone, no receipt, no state.
    assert list(root.iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["repo"]


@pytest.mark.parametrize("target_path", PROTECTED)
def test_protected_prefix_is_named_in_the_refusal(target_path) -> None:
    with pytest.raises(AriadneRequestError) as caught:
        _admit_target_path(target_path)
    named = protected_prefix_for(target_path)
    assert named is not None
    assert named in str(caught.value)
    assert named in SELF_RENOVATION_PROTECTED_PREFIXES


@pytest.mark.parametrize("target_path", ADMITTED)
def test_ordinary_source_is_still_admitted(target_path) -> None:
    assert protected_prefix_for(target_path) is None
    assert _admit_target_path(target_path) == target_path


def test_ignored_roots_keep_their_own_refusal_and_precedence() -> None:
    # The ignored-root refusal stays first and keeps its wording.
    with pytest.raises(AriadneRequestError, match="mandatory ignored root"):
        _admit_target_path(".git/HEAD")


def test_the_tuple_covers_every_class_the_plan_names() -> None:
    joined = "\n".join(SELF_RENOVATION_PROTECTED_PREFIXES)
    for needle in (
        "daedalus/spine/",
        "daedalus/kernel/policy/",
        "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
        "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
        "AGENTS.md",
        "tests/test_ariadne",
        "daedalus/ariadne/campaign.py",
    ):
        assert needle in joined
