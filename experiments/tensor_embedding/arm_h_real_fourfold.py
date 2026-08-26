"""EXPERIMENT ``tensor-embedding-v3``, Arm H: the real fourfold graph.

Every earlier arm measured a synthetic substrate and, in the end, measured the
substrate rather than the question. Arm D showed the density gap: the real
import graph of this repository has average degree 9.98 where the synthetic
corpus had 2.7. Arm G then ran ComplEx on that real import graph and got a 5x
lift over chance -- learning, but far below what the same model reaches on
standard benchmarks.

The most likely reason is relation poverty: the import graph carries TWO
relation types and ONE plane. This arm builds the thing the research is actually
about -- a four-plane graph extracted from this repository, with cross-plane
edges -- and measures whether relation diversity is what was missing.

Extraction is deliberately shallow and deterministic (ast, json, regex over
markdown). It is not a Forest; it is the cheapest honest stand-in for one.

Run:  <venv>/Scripts/python.exe experiments/tensor_embedding/arm_h_real_fourfold.py
"""

from __future__ import annotations

import ast
import collections
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
# The graph can be extracted from any repository: pass a root as argv[1].
ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO
TAG = sys.argv[2] if len(sys.argv) > 2 else "self"
OUT = REPO / "runs" / "tensor_embedding_v3"
SKIP = {".git", "node_modules", "venv-tensor", ".venv", "venv", "__pycache__",
        "site-packages", "reference", "lab_assets", ".mypy_cache", ".pytest_cache"}

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MD_CODE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{2,60})`")


def usable(path: pathlib.Path) -> bool:
    return not any(part in SKIP for part in path.parts)


def build_graph() -> tuple[list[tuple[str, str, str]], dict]:
    triples: set[tuple[str, str, str]] = set()
    defined_symbols: dict[str, str] = {}          # bare name -> node id
    stats = collections.Counter()

    py_files = [p for p in ROOT.rglob("*.py") if usable(p)]
    py_relpaths = {p.relative_to(ROOT).as_posix() for p in py_files}
    for path in py_files:
        rel = path.relative_to(ROOT).as_posix()
        module = f"code:module:{rel}"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            stats["unparsable"] += 1
            continue
        stats["py_files"] += 1

        for node in ast.walk(tree):
            # --- code plane -------------------------------------------------
            if isinstance(node, ast.ImportFrom) and node.module:
                triples.add((module, "imports_from", f"code:module:{node.module}"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    triples.add((module, "imports", f"code:module:{alias.name}"))
            elif isinstance(node, ast.ClassDef):
                cls = f"code:class:{rel}#{node.name}"
                triples.add((module, "defines_class", cls))
                defined_symbols.setdefault(node.name, cls)
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        triples.add((cls, "inherits", f"code:symbol:{base.id}"))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        triples.add((cls, "has_method", f"code:func:{rel}#{node.name}.{item.name}"))
                    # --- type plane: annotated class fields ------------------
                    elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field = f"type:field:{rel}#{node.name}.{item.target.id}"
                        triples.add((cls, "has_field", field))
                        if isinstance(item.annotation, ast.Name):
                            triples.add((field, "has_type", f"type:name:{item.annotation.id}"))
                        defined_symbols.setdefault(item.target.id, field)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = f"code:func:{rel}#{node.name}"
                triples.add((module, "defines_func", fn))
                defined_symbols.setdefault(node.name, fn)
                # --- type plane: signature -------------------------------
                for arg in node.args.args:
                    if arg.annotation is not None and isinstance(arg.annotation, ast.Name):
                        triples.add((fn, "param_type", f"type:name:{arg.annotation.id}"))
                if node.returns is not None and isinstance(node.returns, ast.Name):
                    triples.add((fn, "returns_type", f"type:name:{node.returns.id}"))

    # --- data plane -------------------------------------------------------
    for path in list(ROOT.rglob("*.json")) + list(ROOT.rglob("*.csv")):
        if not usable(path) or path.stat().st_size > 400_000:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix == ".csv":
            try:
                header = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            except IndexError:
                continue
            table = f"data:table:{rel}"
            stats["csv"] += 1
            for col in header.split(",")[:40]:
                col = col.strip().strip('"')
                if col and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", col):
                    triples.add((table, "has_column", f"data:column:{rel}#{col}"))
        else:
            try:
                doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(doc, dict) and isinstance(doc.get("properties"), dict):
                schema = f"data:schema:{rel}"
                stats["schema"] += 1
                for prop in list(doc["properties"])[:60]:
                    triples.add((schema, "has_property", f"data:property:{rel}#{prop}"))

    # --- knowledge plane and cross-plane edges ----------------------------
    for path in ROOT.rglob("*.md"):
        if not usable(path) or path.stat().st_size > 400_000:
            continue
        rel = path.relative_to(ROOT).as_posix()
        doc_node = f"knowledge:doc:{rel}"
        text = path.read_text(encoding="utf-8", errors="replace")
        stats["md"] += 1
        for target in MD_LINK.findall(text)[:80]:
            if target.startswith(("http", "#", "mailto")):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            try:
                rel_target = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                continue
            # A link to a source file must point at the CODE node, not at a
            # parallel `knowledge:file:` node. The first draft minted a separate
            # node per linked file, so a documentation link -- the most
            # deliberate cross-plane statement an author can make -- connected
            # the planes not at all. Same class of defect as the per-file
            # mention node (both found 2026-08-25).
            if rel_target in py_relpaths:
                triples.add((doc_node, "documents_file", f"code:module:{rel_target}"))
            else:
                triples.add((doc_node, "links_to", f"knowledge:file:{rel_target}"))
        for span in set(MD_CODE.findall(text)):
            # A concept is ONE thing mentioned in many places. The first draft
            # made a separate mention node per document
            # (`knowledge:mention:DOC#danger_gate`), which gave every mention
            # exactly two edges -- one in, one out -- so every cross-plane edge
            # died in a 3-core BY CONSTRUCTION, whatever the corpus looked like.
            # That was a modelling artefact, not a property of the repository.
            concept = f"knowledge:concept:{span}"
            triples.add((doc_node, "mentions", concept))
            # CROSS-PLANE: the documented span names a symbol that exists in code
            if span in defined_symbols:
                triples.add((concept, "documents", defined_symbols[span]))
                stats["crossplane_doc_symbol"] += 1

    # CROSS-PLANE: a schema property / csv column whose name matches a field
    for triple in list(triples):
        head, rel_name, tail = triple
        if rel_name in ("has_property", "has_column"):
            name = tail.rsplit("#", 1)[-1]
            if name in defined_symbols and defined_symbols[name].startswith("type:field:"):
                triples.add((tail, "realises_field", defined_symbols[name]))
                stats["crossplane_data_type"] += 1

    return sorted(triples), stats


def describe(triples) -> dict:
    deg = collections.Counter()
    planes = collections.Counter()
    rels = collections.Counter()
    for head, rel, tail in triples:
        deg[head] += 1
        deg[tail] += 1
        rels[rel] += 1
        for node in (head, tail):
            planes[node.split(":", 1)[0]] += 1
    degs = sorted(deg.values())
    n = len(deg)
    return {
        "entities": n,
        "triples": len(triples),
        "relations": len(rels),
        "average_degree": round(2 * len(triples) / n, 2),
        "median_degree": degs[len(degs) // 2],
        "degree_1_share": round(sum(1 for d in degs if d == 1) / n, 4),
        "degree_ge_5_share": round(sum(1 for d in degs if d >= 5) / n, 4),
        "relation_counts": dict(rels.most_common()),
        "plane_node_mentions": dict(planes),
    }


def k_core(triples, k: int):
    """The learnable core: iteratively drop everything below degree k."""
    cur = list(triples)
    while True:
        deg = collections.Counter()
        for h, _, t in cur:
            deg[h] += 1
            deg[t] += 1
        keep = {n for n, d in deg.items() if d >= k}
        nxt = [x for x in cur if x[0] in keep and x[2] in keep]
        if len(nxt) == len(cur):
            return nxt, keep
        cur = nxt


CROSS_PLANE_RELATIONS = ("documents", "realises_field", "documents_file")


def main() -> int:
    triples, stats = build_graph()
    summary = describe(triples)
    core, keep = k_core(triples, 3)
    core_rels = collections.Counter(r for _, r, _ in core)
    all_rels = collections.Counter(r for _, r, _ in triples)
    summary["core_3"] = {
        "entities": len(keep),
        "triples": len(core),
        "entity_share": round(len(keep) / summary["entities"], 4),
        "planes": dict(collections.Counter(n.split(":", 1)[0] for n in keep)),
        "crossplane_full": {r: all_rels.get(r, 0) for r in CROSS_PLANE_RELATIONS},
        "crossplane_surviving": {r: core_rels.get(r, 0) for r in CROSS_PLANE_RELATIONS},
        "crossplane_survival_rate": round(
            sum(core_rels.get(r, 0) for r in CROSS_PLANE_RELATIONS)
            / max(1, sum(all_rels.get(r, 0) for r in CROSS_PLANE_RELATIONS)), 4),
    }
    summary["extraction_stats"] = dict(stats)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"graph_{TAG}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with (OUT / f"triples_{TAG}.tsv").open("w", encoding="utf-8", newline="\n") as fh:
        for head, rel, tail in triples:
            fh.write(f"{head}\t{rel}\t{tail}\n")

    print(f"entities={summary['entities']}  triples={summary['triples']}  "
          f"relations={summary['relations']}  avg_degree={summary['average_degree']}")
    print(f"median_degree={summary['median_degree']}  seen-once={summary['degree_1_share']:.1%}  "
          f"degree>=5={summary['degree_ge_5_share']:.1%}")
    print("relations:", ", ".join(f"{k}={v}" for k, v in summary["relation_counts"].items()))
    print("cross-plane (voll):", summary["core_3"]["crossplane_full"])
    c = summary["core_3"]
    print(f"3-KERN: {c['entities']} Entitaeten ({c['entity_share']:.1%}), {c['triples']} Tripel")
    print(f"3-KERN Ebenen: {c['planes']}")
    print(f"3-KERN Cross-Plane ueberlebend: {c['crossplane_surviving']}  "
          f"-> Ueberlebensrate {c['crossplane_survival_rate']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
