import pytest

from daedalus.structcore.dss import (
    DSSConfig,
    build_forest_hierarchy,
    carry_temporal_scores,
    diffuse_relation_scores,
    prolongate_scores,
    restrict_scores,
    semantic_super_sample,
)
from daedalus.structcore.forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)


def _forest():
    return KnowledgeForest(
        root="/repo",
        nodes=(
            ForestNode("app/api.py", "source_file", {"loc": 10}),
            ForestNode("app/core.py", "source_file", {"loc": 20}),
            ForestNode("docs/guide.md", "source_file", {"loc": 8}),
            ForestNode("tests/test_core.py", "source_file", {"loc": 12}),
            ForestNode("tools/migrate.py", "source_file", {"loc": 15}),
        ),
        edges=(
            ForestEdge("app/api.py", "app/core.py", "imports", True),
            ForestEdge(
                "app/core.py", "tests/test_core.py", "co_change", False, 2.0
            ),
        ),
        hyperedges=(
            ForestHyperedge(
                "clone:1",
                "clone_exact",
                ("app/core.py", "tools/migrate.py"),
            ),
        ),
        provenance={"source": "test"},
    )


def test_hierarchy_restriction_and_bounded_prolongation_are_deterministic():
    hierarchy = build_forest_hierarchy(_forest())
    assert [node.id for node in hierarchy.nodes] == [
        "repo:.",
        "dir:app",
        "dir:docs",
        "dir:tests",
        "dir:tools",
        "file:app/api.py",
        "file:app/core.py",
        "file:docs/guide.md",
        "file:tests/test_core.py",
        "file:tools/migrate.py",
    ]

    restricted = restrict_scores(
        hierarchy,
        {"app/api.py": 0.6, "app/core.py": 0.4, "docs/guide.md": 0.8},
    )
    assert restricted["repo:."] == pytest.approx(1.8)
    assert restricted["dir:app"] == pytest.approx(1.0)

    result = prolongate_scores(hierarchy, restricted, branch_limit=1)
    # app outranks docs at the root; api outranks core inside app.
    assert dict(result.file_scores) == {"app/api.py": pytest.approx(0.6 / 1.8)}
    assert result.pruned_hierarchy_nodes == (
        "dir:docs",
        "file:app/core.py",
    )


def test_temporal_carry_uses_exact_ids_and_explicit_rename_confidence():
    carry = carry_temporal_scores(
        _forest(),
        {"app/core.py": 0.8, "old/guide.md": 0.6, "gone.py": 1.0},
        rename_map={"old/guide.md": "docs/guide.md"},
        rename_confidence={"old/guide.md": 0.5},
    )

    assert dict(carry.scores) == {
        "app/core.py": 0.8,
        "docs/guide.md": 0.3,
    }
    assert [(row.kind, row.previous_id, row.current_id) for row in carry.evidence] == [
        ("exact_id", "app/core.py", "app/core.py"),
        ("rename", "old/guide.md", "docs/guide.md"),
    ]


def test_relation_diffusion_keeps_import_cochange_and_clone_channels_separate():
    channels = diffuse_relation_scores(
        _forest(),
        {"app/api.py": 1.0, "app/core.py": 0.5},
        steps=1,
        decay=1.0,
    )
    by_relation = {
        channel.relation: dict(channel.scores) for channel in channels
    }

    assert by_relation["imports"] == {"app/core.py": 1.0}
    assert by_relation["co_change"] == {"tests/test_core.py": 0.5}
    assert by_relation["clone_exact"] == {"tools/migrate.py": 0.5}
    assert next(
        channel for channel in channels if channel.relation == "imports"
    ).directed is True
    assert next(
        channel for channel in channels
        if channel.relation == "clone_exact"
    ).source_kind == "hyperedge"


def test_end_to_end_plan_is_budgeted_ranked_and_content_addressed():
    kwargs = {
        "token_budget": 220,
        "token_costs": {
            "app/api.py": 100,
            "app/core.py": 120,
            "docs/guide.md": 80,
            "tests/test_core.py": 100,
            "tools/migrate.py": 90,
        },
        "previous_scores": {"old/core.py": 0.5},
        "rename_map": {"old/core.py": "app/core.py"},
        "rename_confidence": {"old/core.py": 0.8},
        "config": DSSConfig(branch_limit=2, diffusion_steps=1),
    }
    first = semantic_super_sample(_forest(), {"app/api.py": 1.0}, **kwargs)
    second = semantic_super_sample(_forest(), {"app/api.py": 1.0}, **kwargs)

    assert first.to_dict() == second.to_dict()
    assert first.receipt.content_sha256 == second.receipt.content_sha256
    assert len(first.receipt.content_sha256) == 64
    assert first.context_plan.tokens_used <= first.context_plan.token_budget
    assert [item.score for item in first.context_plan.selected] == sorted(
        (item.score for item in first.context_plan.selected), reverse=True
    )
    assert first.receipt.forest_sha256 == _forest().content_sha256
    assert set(first.receipt.relation_channels) == {
        "clone_exact",
        "co_change",
        "imports",
    }
    assert any(
        "relation:imports" in item.reasons
        for item in first.context_plan.selected + first.context_plan.omitted
    )


def test_receipt_changes_when_seed_or_budget_changes():
    first = semantic_super_sample(
        _forest(), {"app/api.py": 1.0}, token_budget=200
    )
    changed_seed = semantic_super_sample(
        _forest(), {"app/api.py": 0.5}, token_budget=200
    )
    changed_budget = semantic_super_sample(
        _forest(), {"app/api.py": 1.0}, token_budget=201
    )

    assert first.receipt.content_sha256 != changed_seed.receipt.content_sha256
    assert first.receipt.content_sha256 != changed_budget.receipt.content_sha256


def test_invalid_paths_and_scores_fail_closed():
    broken = KnowledgeForest(
        root="/repo",
        nodes=(ForestNode("../escape.py", "source_file"),),
        edges=(),
        hyperedges=(),
        provenance={},
    )
    with pytest.raises(ValueError, match="safe relative path"):
        build_forest_hierarchy(broken)
    with pytest.raises(ValueError, match="finite non-negative"):
        semantic_super_sample(
            _forest(), {"app/api.py": float("nan")}, token_budget=100
        )
