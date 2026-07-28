from daedalus.structcore.forest import build_knowledge_forest


def _index():
    return {
        "root": "/repo",
        "backend": {"tree_sitter": False, "lizard": False},
        "scope_key": "/repo#scope",
        "ignored": {"count": 1, "sample": ["vendor/x.py"]},
        "tokenizer": "heuristic:chars/4",
        "modules": {
            "app/a.py": {"language": "python", "loc": 10},
            "app/b.py": {"language": "python", "loc": 20},
            "tests/test_a.py": {"language": "python", "loc": 12},
        },
        "fan_in": {"app/b.py": 1},
        "module_heat": [
            {"module": "app/a.py", "score": 2.0, "churn": 4},
            {"module": "app/b.py", "score": 1.0, "churn": 2},
        ],
        "import_edges": {
            "app/a.py": ["app/b.py", "external/not-indexed.py"],
            "tests/test_a.py": ["app/a.py"],
        },
        "duplication": {
            "unit_clusters": [{
                "name": "same",
                "count": 2,
                "sites": [
                    {"module": "app/a.py", "line": 2},
                    {"module": "app/b.py", "line": 3},
                ],
            }],
            "renamed_clusters": [],
            "near_clusters": [],
            "window_clusters": [{
                "files": ["app/a.py", "tests/test_a.py"],
                "shared_runs": 3,
            }],
        },
    }


def test_snapshot_is_deterministic_and_content_addressed():
    first = build_knowledge_forest(_index())
    second = build_knowledge_forest(_index())

    assert first.to_dict() == second.to_dict()
    assert first.content_sha256 == second.content_sha256
    assert len(first.content_sha256) == 64
    assert [node.id for node in first.nodes] == [
        "app/a.py", "app/b.py", "tests/test_a.py"
    ]
    assert first.nodes[0].attributes["heat_score"] == 2.0


def test_relation_layers_remain_separate_and_keep_provenance():
    forest = build_knowledge_forest(_index(), temporal_pairs=[{
        "a": "app/a.py",
        "b": "tests/test_a.py",
        "count": 3,
        "count_a": 5,
        "count_b": 4,
        "commits_considered": 10,
        "pmi": 0.4,
        "lift": 1.5,
    }])

    assert forest.layer_counts == {
        "clone_exact": 1,
        "clone_window": 1,
        "co_change": 1,
        "imports": 2,
    }
    temporal = next(edge for edge in forest.edges if edge.relation == "co_change")
    assert temporal.directed is False
    assert temporal.weight == 1.5
    assert temporal.evidence == ("git.co_change",)
    assert temporal.attributes["commits_considered"] == 10


def test_clone_groups_are_hyperedges_not_pairwise_cliques():
    forest = build_knowledge_forest(_index())

    clones = {edge.relation: edge for edge in forest.hyperedges}
    assert clones["clone_exact"].members == ("app/a.py", "app/b.py")
    assert clones["clone_window"].members == ("app/a.py", "tests/test_a.py")
    assert all(edge.relation != "clone_exact" for edge in forest.edges)


def test_distinct_clone_groups_with_same_files_get_distinct_ids():
    idx = _index()
    idx["duplication"]["unit_clusters"].append({
        "name": "another",
        "count": 2,
        "sites": [
            {"module": "app/a.py", "line": 20},
            {"module": "app/b.py", "line": 30},
        ],
    })
    forest = build_knowledge_forest(idx)
    exact = [edge for edge in forest.hyperedges if edge.relation == "clone_exact"]

    assert len(exact) == 2
    assert len({edge.id for edge in exact}) == 2


def test_out_of_scope_evidence_does_not_manufacture_nodes():
    idx = _index()
    idx["duplication"]["near_clusters"] = [{
        "similarity": 0.95,
        "sites": [
            {"module": "app/a.py"},
            {"module": "vendor/x.py"},
        ],
    }]
    forest = build_knowledge_forest(
        idx,
        temporal_pairs=[{"a": "app/a.py", "b": "vendor/x.py", "lift": 5}],
    )

    assert "vendor/x.py" not in {node.id for node in forest.nodes}
    assert "clone_near" not in forest.layer_counts
    assert "co_change" not in forest.layer_counts
