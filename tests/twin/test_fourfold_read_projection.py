from __future__ import annotations

from daedalus.twin.read_projection import fourfold_read_projection


def _index() -> dict:
    return {
        "root": "/repo",
        "backend": {"tree_sitter": False, "lizard": False},
        "scope_key": "/repo+docs+types+wiki",
        "ignored": {"count": 0},
        "tokenizer": "heuristic:chars/4",
        "modules": {
            "app/a.py": {"language": "python", "loc": 12},
            "app/b.py": {"language": "python", "loc": 8},
            "README.md": {"kind": "document", "language": "markdown", "loc": 5},
        },
        "fan_in": {"app/a.py": 1},
        "module_heat": [
            {"module": "app/a.py", "score": 4.0, "churn": 2, "loc": 12},
            {"module": "app/b.py", "score": 1.0, "churn": 0, "loc": 8},
        ],
        "import_edges": {"app/b.py": ["app/a.py"]},
        "document_links": {"README.md": ["app/a.py"]},
        "type_nodes": [
            {"id": "type:app/a.py#Event", "kind": "type", "module": "app/a.py"},
            {"id": "field:app/a.py#Event.value", "kind": "field", "module": "app/a.py"},
        ],
        "type_edges": {
            "consumes": [
                {"source": "app/a.py", "target": "type:app/a.py#Event"},
            ],
            "has_field": [
                {
                    "source": "type:app/a.py#Event",
                    "target": "field:app/a.py#Event.value",
                },
            ],
        },
        "duplication": {
            "unit_clusters": [
                {
                    "name": "pair",
                    "count": 2,
                    "sites": [
                        {"module": "app/a.py", "line": 1},
                        {"module": "app/b.py", "line": 1},
                    ],
                }
            ],
            "renamed_clusters": [],
            "near_clusters": [],
            "window_clusters": [],
        },
    }


def test_bounded_projection_keeps_each_observed_plane_and_names_absence() -> None:
    payload = fourfold_read_projection(
        _index(),
        repository_id="atlas",
        created_at="2026-09-04T10:00:00+00:00",
        max_nodes=3,
    )

    assert payload["schema"] == "daedalus-fourfold-read/1"
    assert payload["revision_basis"] == "forest-content"
    assert payload["graph"]["truncated"] is True
    assert {node["plane"] for node in payload["graph"]["nodes"]} == {
        "code",
        "type",
        "knowledge",
    }
    planes = {plane["plane"]: plane for plane in payload["planes"]}
    assert planes["code"]["status"] == "partial"
    assert planes["type"]["status"] == "partial"
    assert planes["knowledge"]["status"] == "partial"
    assert planes["data"]["status"] == "absent"
    assert "no canonical Data Plane" in planes["data"]["reason"]


def test_all_projection_keeps_every_module_and_does_not_invent_hyperedges() -> None:
    payload = fourfold_read_projection(
        _index(),
        repository_id="atlas",
        created_at="2026-09-04T10:00:00+00:00",
        max_nodes=None,
    )
    graph = payload["graph"]

    assert graph["scope"] == "all"
    assert graph["truncated"] is False
    assert graph["n_nodes_shown"] == graph["n_nodes_total"] == 5
    assert graph["n_modules_shown"] == graph["n_modules_total"] == 2
    assert graph["n_edges_eligible"] == graph["n_edges_total"] == 4
    assert graph["n_edges_offmap"] == 0
    assert graph["n_hyperedges_total"] == 1
    assert all(edge["relation"] != "clone_exact" for edge in graph["edges"])
    assert any(edge["cross_plane"] for edge in graph["edges"])
