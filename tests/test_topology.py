# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from daedalus.structcore.topology import spectral_partition


def test_disconnected_graph_uses_component_cut_without_fake_fiedler_vector():
    # Create a mock graph index with two disconnected components
    # Component A: a, b
    # Component B: c, d
    mock_idx = {
        "modules": {"a", "b", "c", "d"},
        "import_edges": {
            "a": ["b"],
            "b": ["a"],
            "c": ["d"],
            "d": ["c"]
        },
        "import_edges_reverse": {}
    }

    with patch("daedalus.structcore.topology.cached_index", return_value=mock_idx), \
         patch("daedalus.structcore.topology._graph_nodes", return_value={"a", "b", "c", "d"}):
        
        res = spectral_partition("/dummy")
        
        assert res["available"] is True
        assert res["method"] == "connected_components"
        assert res["cut_edges"] == 0
        assert len(res["fiedler_values"]) == 4
        assert set(res["fiedler_values"].values()) == {None}
        
        # The algebraic connectivity (Fiedler value, 2nd smallest eigenvalue) for disconnected components is 0.
        # But wait, our eigh returns eigenvalues. Let's just check it partitions correctly.
        # A and B should be on different sides of 0, or at least one is >0 and one is <= 0
        part_a = res["partition_a"]
        part_b = res["partition_b"]
        
        assert ("a" in part_a and "b" in part_a and "c" in part_b and "d" in part_b) or \
               ("a" in part_b and "b" in part_b and "c" in part_a and "d" in part_a)


def test_connected_graph_uses_sparse_compatible_sweep_cut():
    mock_idx = {
        "modules": {"a", "b", "c", "d"},
        "import_edges": {
            "a": ["b"],
            "b": ["c"],
            "c": ["d"],
            "d": [],
        },
        "import_edges_reverse": {},
    }

    with patch(
        "daedalus.structcore.topology._graph_nodes",
        return_value={"a", "b", "c", "d"},
    ):
        res = spectral_partition("/dummy", idx=mock_idx)

    assert res["available"] is True
    assert res["method"] == "normalized_laplacian_sweep"
    assert sorted(res["partition_a"] + res["partition_b"]) == ["a", "b", "c", "d"]
    assert res["partition_a"]
    assert res["partition_b"]
    assert res["algebraic_connectivity"] > 0
    assert res["cut_edges"] == 1


def test_oversized_graph_refuses_dense_or_synchronous_fallback():
    mock_idx = {
        "modules": {"a", "b", "c"},
        "import_edges": {},
        "import_edges_reverse": {},
    }

    with patch(
        "daedalus.structcore.topology._graph_nodes",
        return_value={"a", "b", "c"},
    ):
        res = spectral_partition("/dummy", idx=mock_idx, max_nodes=2)

    assert res["available"] is False
    assert "synchronous spectral limit" in res["reason"]
