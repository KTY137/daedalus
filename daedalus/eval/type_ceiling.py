"""
Type ceiling experiment: how many symbols missed by import+call retrieval
are reachable via type edges, indicating the potential benefit of the type layer.
"""

import logging
from typing import Set, Any, Optional

logger = logging.getLogger(__name__)


def compute_type_ceiling(
    graph,
    missed_symbols: Set[Any],
    start_nodes: Set[Any],
    import_edge_types: Set[str] = {"imports", "calls"},
    type_edge_type: str = "type",
) -> Optional[float]:
    """
    Compute the fraction of missed symbols that are reachable via type edges
    but NOT via import/call edges from the start nodes.

    Returns None if type edges are not present or data insufficient.
    """
    # Check if graph has edges with the type_edge_type attribute
    type_edges_present = False
    for u, v, data in graph.edges(data=True):
        if data.get("edge_type") == type_edge_type:
            type_edges_present = True
            break
    if not type_edges_present:
        logger.warning("No type edges found in graph. Cannot compute type ceiling.")
        return None

    # Compute reachable via import/call
    def reachable(g, start, edge_types):
        visited = set()
        stack = list(start)
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            for _, neighbor, data in g.edges(node, data=True):
                if data.get("edge_type") in edge_types and neighbor not in visited:
                    stack.append(neighbor)
        return visited

    reachable_import_call = reachable(graph, start_nodes, import_edge_types)
    reachable_all = reachable(graph, start_nodes, import_edge_types | {type_edge_type})
    only_type_reachable = reachable_all - reachable_import_call

    missed_reachable_via_type = missed_symbols.intersection(only_type_reachable)
    total_missed = len(missed_symbols)
    if total_missed == 0:
        logger.info("No missed symbols, ceiling undefined.")
        return 0.0
    return len(missed_reachable_via_type) / total_missed


def main():
    """
    Run the type ceiling experiment using default data.
    """
    # Example: load graph, missed symbols, start nodes from data files
    # Placeholder: integrate with Daedalus evaluation harness.
    logging.basicConfig(level=logging.INFO)
    logger.info("Type ceiling experiment not yet integrated with data loading.")
    # In practice, you would load the graph and symbols here.
    # e.g.:
    # from daedalus.eval.loaders import load_graph, load_missed_symbols, load_start_nodes
    # graph = load_graph()
    # missed = set(load_missed_symbols())
    # starts = set(load_start_nodes())
    # ceiling = compute_type_ceiling(graph, missed, starts)
    # logger.info(f"Type ceiling: {ceiling:.2%}")


if __name__ == "__main__":
    main()
