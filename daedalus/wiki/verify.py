"""Deterministic verification of a generated project wiki.

A model may write documentation. Whether that documentation is true about the
repository is not the model's call -- this module decides it, by looking at the
tree. Same boundary as everywhere else in Daedalus: models propose, independent
evidence verifies.

Six checks, each of which can only fail loudly. The first three decide the
verdict; the last three are reported but do not fail a page on their own:

``unknown_symbol``   a backticked identifier that exists nowhere in the source
``broken_link``      a relative link whose target is not in the tree
``unsourced_claim``  a paragraph marked as external knowledge with no URL
``missing_file_reference``  a backticked filename no file in the tree carries
``uncovered_module`` a source module no wiki page mentions
``thin_concept``     a concept mentioned exactly once -- it carries no structure
                     and dies in any k-core, so it buys the knowledge plane
                     nothing (measured 2026-08-25: modelling mentions per file
                     instead of per concept put cross-plane survival at 0%;
                     per concept it is 26-28%)

The module reads the tree and nothing else. No network, no model, no writes.
The wiki under verification is excluded from the vocabulary the checks consult
-- see ``tree_vocabulary`` for why that exclusion is a boundary, not a filter.
"""

from __future__ import annotations

import ast
import builtins
import collections
import dataclasses
import json
import pathlib
import re
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages",
             ".mypy_cache", ".pytest_cache", "reference", "lab_assets"}

MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
MD_CODE = re.compile(r"`([^`\n]{2,80})`")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
SOURCE_MARK = re.compile(r"(?im)^\s*(?:quelle|source|ref)\s*:", re.MULTILINE)
URL = re.compile(r"https?://[^\s)>\]]+")
EXTERNAL_MARK = re.compile(r"(?im)^\s*>\s*\*\*extern")


BUILTIN_NAMES = set(dir(builtins)) | {"self", "cls", "args", "kwargs"}
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A span is a SYMBOL CLAIM only if it is shaped like one: it carries an
# underscore or a case transition. A single lowercase word in backticks is
# prose or a value (`und`, `positive`, `NaN`) and claiming it is a defect
# would drown the real findings -- measured on project_tct, where 412 of the
# first pass were prose and data-field names.
SYMBOL_SHAPE = re.compile(r"(?:.*_.*)|(?:.*[a-z].*[A-Z].*)|(?:^[A-Z][a-z]+[A-Z])")
FILE_SUFFIXES = {"py", "md", "json", "yaml", "yml", "toml", "csv", "txt", "ini",
                 "cfg", "qml", "ps1", "sh", "png", "svg", "ipynb", "log", "lock"}


def _usable(path: pathlib.Path) -> bool:
    return not any(part in SKIP_DIRS for part in path.parts)


@dataclasses.dataclass(frozen=True)
class Finding:
    kind: str
    page: str
    detail: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "page": self.page, "detail": self.detail}


def index_symbols(root: pathlib.Path) -> tuple[set[str], set[str]]:
    """Every defined name in the tree, and every module path."""
    names: set[str] = set()
    modules: set[str] = set()
    for path in root.rglob("*.py"):
        if not _usable(path) or path.stat().st_size > 400_000:
            continue
        modules.add(path.relative_to(root).as_posix())
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.Attribute):
                # `self.io_lock = ...` and every other attribute the code uses.
                # Without this the checker flags real members as unknown; a
                # sample of its first findings was 4 of 4 false-positive classes
                # (2026-08-25), which is why they are all handled here.
                names.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    names.add(alias.asname or alias.name.rsplit(".", 1)[-1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[0])
                    names.add(alias.name.rsplit(".", 1)[-1])
    return names, modules


def tree_vocabulary(root: pathlib.Path,
                    exclude: tuple[pathlib.Path, ...] = ()) -> set[str]:
    """Every identifier-shaped token that occurs anywhere in the project.

    The check this feeds is deliberately narrow: "you wrote a name that appears
    NOWHERE in this project". A data field documented in a format spec, a YAML
    key, an HDF5 dataset name and a QML id are all real names even though none
    of them is a Python identifier. Restricting the vocabulary to Python
    definitions flagged 412 such names on project_tct, and the two genuine
    findings (`SurveyPlan`, `AppComposition`) were buried in them.

    ``exclude`` is not an optimisation. The wiki normally lives inside the tree
    it describes, so without it the pages under verification are themselves
    read into the vocabulary that judges them: a model invents a symbol, the
    invented name occurs in the page, the page therefore proves the name real
    and ``unknown_symbol`` can never fire. The candidate would be supplying its
    own evidence, which is the boundary invariant 4 draws. Measured 2026-08-25:
    with the wiki inside ``root`` and not excluded, a page claiming
    ``absent_helper`` about a tree that contains no such name passed.
    """
    excluded = tuple(d.resolve() for d in exclude)
    vocabulary: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or not _usable(path):
            continue
        if any(path.resolve().is_relative_to(d) for d in excluded):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip",
                                   ".h5", ".hdf5", ".npy", ".npz", ".bin", ".exe",
                                   ".dll", ".pyd", ".so", ".whl"}:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        vocabulary.update(WORD.findall(text))
    return vocabulary


def _config_keys(root: pathlib.Path) -> set[str]:
    """Keys from json/yaml/toml configs count as real names too."""
    keys: set[str] = set()
    for suffix in ("*.json", "*.yaml", "*.yml", "*.toml"):
        for path in root.rglob(suffix):
            if not _usable(path) or path.stat().st_size > 200_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".json":
                try:
                    doc = json.loads(text)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                def walk(value):
                    if isinstance(value, dict):
                        for key, sub in value.items():
                            keys.add(str(key))
                            walk(sub)
                    elif isinstance(value, list):
                        for sub in value[:200]:
                            walk(sub)

                walk(doc)
            else:
                for match in re.finditer(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]", text):
                    keys.add(match.group(1))
    return keys


def verify(root: pathlib.Path, wiki_dir: pathlib.Path) -> dict:
    """Check every claim a wiki makes against the tree it claims to describe."""
    names, modules = index_symbols(root)
    wiki_own = {p.stem for p in wiki_dir.rglob("*.md")}
    known = names | _config_keys(root) | tree_vocabulary(root, exclude=(wiki_dir,))
    known |= {pathlib.Path(m).stem for m in modules}
    known -= wiki_own          # a name that only the wiki itself introduces is not evidence

    tree_files = [p for p in root.rglob("*") if p.is_file() and _usable(p)]
    pages = sorted(p for p in wiki_dir.rglob("*.md") if _usable(p))
    findings: list[Finding] = []
    concept_pages: dict[str, set[str]] = collections.defaultdict(set)
    mentioned_modules: set[str] = set()
    link_targets = 0
    symbol_spans = 0

    for path in pages:
        page = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        for _, href in MD_LINK.findall(text):
            if href.startswith(("http", "#", "mailto")):
                continue
            link_targets += 1
            target = (path.parent / href.split("#")[0])
            if not target.exists():
                findings.append(Finding("broken_link", page, href))
                continue
            try:
                rel = target.resolve().relative_to(root).as_posix()
            except ValueError:
                findings.append(Finding("broken_link", page, f"{href} (outside the tree)"))
                continue
            if rel in modules:
                mentioned_modules.add(rel)

        for span in MD_CODE.findall(text):
            span = span.strip()
            if not IDENTIFIER.match(span):
                continue          # prose in backticks, a path, a command -- not a claim
            symbol_spans += 1
            if "." in span and span.rsplit(".", 1)[-1].lower() in FILE_SUFFIXES:
                # A filename, not a symbol. Whether the file exists is its own
                # question, and a different finding.
                if not any(f.name == span for f in tree_files):
                    findings.append(Finding("missing_file_reference", page, span))
                continue
            leaf = span.rsplit(".", 1)[-1]
            concept_pages[leaf].add(page)
            if not SYMBOL_SHAPE.match(leaf):
                continue          # prose or a value in backticks, not a claim
            if leaf not in known and leaf not in BUILTIN_NAMES:
                findings.append(Finding("unknown_symbol", page, span))

        for block in EXTERNAL_MARK.split(text)[1:]:
            head = block[:600]
            if not URL.search(head):
                findings.append(Finding("unsourced_claim", page, head.strip()[:120]))

    for module in sorted(modules):
        if module not in mentioned_modules:
            findings.append(Finding("uncovered_module", "-", module))

    for concept, where in sorted(concept_pages.items()):
        if len(where) == 1:
            findings.append(Finding("thin_concept", next(iter(where)), concept))

    by_kind = collections.Counter(f.kind for f in findings)
    total_symbols = len(concept_pages)
    return {
        "root": str(root),
        "wiki_dir": str(wiki_dir.relative_to(root)) if wiki_dir.is_relative_to(root) else str(wiki_dir),
        "pages": len(pages),
        "source_modules": len(modules),
        "modules_linked_from_wiki": len(mentioned_modules),
        "module_coverage": round(len(mentioned_modules) / max(1, len(modules)), 4),
        "relative_links": link_targets,
        "symbol_spans": symbol_spans,
        "distinct_concepts": total_symbols,
        "concepts_on_multiple_pages": sum(1 for w in concept_pages.values() if len(w) > 1),
        "multi_page_concept_share": round(
            sum(1 for w in concept_pages.values() if len(w) > 1) / max(1, total_symbols), 4),
        "findings_by_kind": dict(by_kind),
        "findings": {
            kind: [f.as_dict() for f in findings if f.kind == kind][:80]
            for kind in sorted(by_kind)
        },
        "findings_per_kind_truncated": {
            kind: max(0, by_kind[kind] - 80) for kind in sorted(by_kind)
        },
        "verdict": "PASS" if not (by_kind["unknown_symbol"] or by_kind["broken_link"]
                                  or by_kind["unsourced_claim"]) else "FAIL",
    }


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("usage: python -m daedalus.wiki.verify <repo-root> [wiki-dir]")
        return 2
    if args[0].startswith("-"):
        print(f"unknown option: {args[0]}")
        print("usage: python -m daedalus.wiki.verify <repo-root> [wiki-dir]")
        return 2
    root = pathlib.Path(args[0]).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}")
        return 2
    wiki = pathlib.Path(args[1]).resolve() if len(args) > 1 else root / "docs" / "wiki"
    if not wiki.exists():
        print(f"no wiki at {wiki}")
        return 1
    report = verify(root, wiki)
    print(f"pages={report['pages']}  module coverage={report['module_coverage']:.1%} "
          f"({report['modules_linked_from_wiki']}/{report['source_modules']})")
    print(f"concepts={report['distinct_concepts']}  auf mehreren Seiten="
          f"{report['concepts_on_multiple_pages']} ({report['multi_page_concept_share']:.1%})")
    print(f"findings: {report['findings_by_kind']}")
    print(f"VERDICT: {report['verdict']}")
    out = root / "runs" / "wiki_verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
