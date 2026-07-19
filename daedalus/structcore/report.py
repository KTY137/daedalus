"""report.py — shape a full ``build_index`` result into a compact API payload.

The raw index carries a per-file ``modules`` dict and full clone-site lists —
far too large to ship to the UI. ``structure_summary`` trims it to the ranked,
bounded shape the cockpit's Structure sheet renders.
"""
from __future__ import annotations


def _clone_rows(clusters: list, limit: int, extra: tuple = ()) -> list:
    """Shared bounded projection for a clone-cluster list (exact/renamed/near).
    ``extra`` names optional fields to carry through (e.g. ``similarity``)."""
    rows = []
    for c in clusters[:limit]:
        row = {
            "name": c.get("name", ""),
            "language": c.get("language", ""),
            "count": c["count"],
            "loc": c["loc"],
            "safety": c.get("safety"),
            "sites": [{"module": s["module"], "line": s["line"]} for s in c["sites"][:8]],
        }
        for key in extra:
            if key in c:
                row[key] = c[key]
        rows.append(row)
    return rows


def _graph(idx: dict, max_nodes: int, max_edges: int) -> dict:
    """Module dependency graph for the code map: nodes carry the churn x
    complexity heat, edges are the unified rel->rel import edges.

    Node ids are rel paths for every language. We deliberately do NOT use the
    index's ``dependencies``/``fan_in`` here — those key Python by dotted module
    name and everything else by rel path, so they cannot be joined against
    ``modules``. ``import_edges`` is the one consistent namespace, and the map's
    fan-in is recomputed from it for the same reason.

    Truncation keeps the highest-heat nodes and is reported, never silent.
    """
    heat = idx.get("module_heat") or []
    modules = idx.get("modules") or {}
    edge_map = idx.get("import_edges") or {}

    graph_fan_in: dict[str, int] = {}
    all_edges: list[tuple[str, str]] = []
    for src, targets in edge_map.items():
        for tgt in targets:
            all_edges.append((src, tgt))
            graph_fan_in[tgt] = graph_fan_in.get(tgt, 0) + 1

    kept = {h["module"] for h in heat[:max_nodes]}
    nodes = [{
        "module": h["module"],
        "language": (modules.get(h["module"]) or {}).get("language", ""),
        "loc": h["loc"],
        "score": h["score"],
        "churn": h["churn"],
        "fan_in": graph_fan_in.get(h["module"], 0),
    } for h in heat[:max_nodes]]

    visible = [(s, t) for s, t in all_edges if s in kept and t in kept]
    edges = [{"source": s, "target": t} for s, t in visible[:max_edges]]

    return {
        "nodes": nodes,
        "edges": edges,
        "n_nodes_total": len(heat),
        "n_edges_total": len(all_edges),
        "truncated": len(nodes) < len(heat) or len(edges) < len(all_edges),
    }


def structure_summary(idx: dict, *, top_hotspots: int = 25, top_clones: int = 40,
                      top_windows: int = 25, top_fanin: int = 20,
                      top_renamed: int = 25, top_near: int = 25,
                      max_graph_nodes: int = 2000, max_graph_edges: int = 8000) -> dict:
    dup = idx.get("duplication", {})
    units = dup.get("unit_clusters", [])
    renamed = dup.get("renamed_clusters", [])
    near = dup.get("near_clusters", [])
    windows = dup.get("window_clusters", [])
    fenced = sum(1 for c in (*units, *renamed, *near, *windows) if c.get("safety"))

    clones = _clone_rows(units, top_clones)
    renamed_clones = _clone_rows(renamed, top_renamed, extra=("names",))
    near_clones = _clone_rows(near, top_near, extra=("names", "similarity", "similarity_max"))

    window_clones = [{
        "files": c["files"][:6],
        "shared_runs": c["shared_runs"],
        "safety": c.get("safety"),
    } for c in windows[:top_windows]]

    fan_in = [{"module": m, "count": n}
              for m, n in list(idx.get("fan_in", {}).items())[:top_fanin]]

    return {
        "backend": idx.get("backend", {}),
        "repo_root": idx.get("root", ""),
        "n_files": idx.get("n_files", 0),
        "languages": idx.get("languages", {}),
        "totals": {
            "unit_clusters": len(units),
            "renamed_clusters": len(renamed),
            "near_clusters": len(near),
            "window_clusters": len(windows),
            "safety_fenced": fenced,
        },
        "hotspots": idx.get("hotspots", [])[:top_hotspots],
        "clones": clones,
        "renamed_clones": renamed_clones,
        "near_clones": near_clones,
        "window_clones": window_clones,
        "fan_in": fan_in,
        "graph": _graph(idx, max_graph_nodes, max_graph_edges),
    }
