# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Deterministic verification of a generated project wiki.

A model may write documentation. Whether that documentation is true about the
repository is not the model's call -- this module decides it, by looking at the
tree. Same boundary as everywhere else in Daedalus: models propose, independent
evidence verifies.

Five checks, each of which can only fail loudly:

``unknown_symbol``   a backticked identifier that exists nowhere in the source
``broken_link``      a relative link whose target is not in the tree
``unsourced_claim``  a paragraph marked as external knowledge with no URL
``uncovered_module`` a source module no wiki page mentions
``thin_concept``     a concept mentioned exactly once -- it carries no structure
                     and dies in any k-core, so it buys the knowledge plane
                     nothing (measured 2026-08-25: modelling mentions per file
                     instead of per concept put cross-plane survival at 0%;
                     per concept it is 26-28%)

The module reads the tree and nothing else. No network, no model, no writes.
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


def exclusions(root: pathlib.Path, wiki_dir: pathlib.Path | None) -> list[pathlib.Path]:
    """The trees that may not supply evidence about the wiki under test.

    Two of them: the wiki itself, and ``<root>/runs`` where the checker writes
    its own report. Computed once in ``verify`` and passed to every evidence
    source, because a rule enforced in one of three sources is not a rule -- it
    is a hole with a docstring. Measured on fixtures 2026-08-25: a name invented
    by a page and then "supported" by a ``.py``, ``.json``, ``.yaml`` or
    ``.toml`` file placed under either tree was acquitted in 8 of 8 placements
    while the same name over the already-fixed source stayed caught.
    """
    excluded = [(root / "runs").resolve()]
    if wiki_dir is not None:
        excluded.append(wiki_dir.resolve())
    # A THIRD TREE, and the one nobody declared: a git worktree or clone
    # checked out BELOW root is a different repository, so every module in it
    # is a second copy of a module this checker has already counted. It cannot
    # create a false acquittal -- the names are the same names -- but it halves
    # `module_coverage` by doubling `source_modules`, and it asks for wiki
    # pages about a duplicate. Structural, not a name in a list: `.claude/
    # worktrees/` would never have been in one. MEASURED 2026-08-26: the
    # sibling planner's survey drew 480 of 983 files from exactly such a copy.
    for marker in root.rglob(".git"):
        if marker.parent != root:
            excluded.append(marker.parent.resolve())
    return excluded


def _in_excluded(path: pathlib.Path, excluded: list[pathlib.Path]) -> bool:
    return any(path.is_relative_to(d) for d in excluded)


def index_symbols(root: pathlib.Path,
                  exclude_dirs: list[pathlib.Path]) -> tuple[set[str], set[str]]:
    """Every defined name in the tree, and every module path.

    ``exclude_dirs`` comes from ``exclusions``; a ``.py`` file under the wiki or
    under ``runs`` neither defines a name that counts as evidence nor counts as
    a project module, which is also the right answer for ``uncovered_module``:
    an artefact is not a module somebody forgot to document.
    """
    root = root.resolve()
    names: set[str] = set()
    modules: set[str] = set()
    for path in root.rglob("*.py"):
        if not _usable(path) or _in_excluded(path, exclude_dirs):
            continue
        if path.stat().st_size > 400_000:
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


def tree_vocabulary(root: pathlib.Path, exclude_dirs: list[pathlib.Path]) -> set[str]:
    """Every identifier-shaped token that occurs anywhere in the project.

    The check this feeds is deliberately narrow: "you wrote a name that appears
    NOWHERE in this project". A data field documented in a format spec, a YAML
    key, an HDF5 dataset name and a QML id are all real names even though none
    of them is a Python identifier. Restricting the vocabulary to Python
    definitions flagged 412 such names on project_tct, and the two genuine
    findings (`SurveyPlan`, `AppComposition`) were buried in them.

    THE CHECKED SET MAY NOT VOUCH FOR ITSELF. ``exclude_dirs`` (from
    ``exclusions``) holds the wiki under test and ``<root>/runs``, and nothing
    beneath either contributes a token. Without the first, a name a page invents
    enters the vocabulary that is supposed to judge it merely by being written
    down, and ``unknown_symbol`` becomes unreachable except by the accident of a
    page being named after the symbol; measured on project_tct (2026-08-25), the
    check reported 0 unknown symbols over 37 wiki pages while two genuine
    findings sat inside them. Without the second, ``main``'s own
    ``wiki_verify.json`` quotes every finding back as evidence and acquits it on
    the next run -- a finding that erases itself by being recorded.

    Documents OUTSIDE the checked set stay in on purpose -- a format
    specification is the only text home real field names have, and dropping
    every ``.md`` would revive the 412 false positives above.

    A Qt front-end keeps its name surface in ``.qml``, so ``qml_index`` reads
    those files structurally and its names are unioned in below, under the same
    exclusions. The union may only ever ADD names -- it suppresses no finding
    kind and lowers no count.

    Its measured marginal contribution today is ZERO, and honesty about that
    belongs next to the call. Every name the structural reader returns is also a
    token of a file this scrape already reads, over the same skip set and under
    a stricter size cap, so it cannot add anything the scrape missed: measured
    on project_tct 2026-08-25, 0 new names over 39 files of ``TCT_app/gui/qml``
    and 0 over the 418 readable files of ``TCT_app``. It is kept because it is
    the half that survives: the moment this scrape is narrowed from "every word
    of every file" to something a claim check can actually rest on, the QML
    names have to come from a reader that knows a declaration from a sentence,
    and that reader has to exist first. Until then it buys precision, not
    coverage -- and it costs one extra pass over the ``.qml``/``.js`` files.
    """
    from . import qml_index    # local import: keeps verify -> qml_index acyclic
    # Resolved on both sides, or a relative `root` against absolute exclusions
    # would never match and the exclusion would fail open in silence.
    root = root.resolve()
    vocabulary: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or not _usable(path):
            continue
        if _in_excluded(path, exclude_dirs):
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
    return vocabulary | qml_index.qml_vocabulary(root, exclude_dirs)


def _config_keys(root: pathlib.Path, exclude_dirs: list[pathlib.Path]) -> set[str]:
    """Keys from json/yaml/toml configs count as real names too.

    Under the same exclusions as every other evidence source. The ``runs`` half
    is not hypothetical: ``main`` writes ``wiki_verify.json`` there, and a
    finding recorded as a JSON key would otherwise be read back as a config key
    and acquit itself on the next run.
    """
    root = root.resolve()
    keys: set[str] = set()
    for suffix in ("*.json", "*.yaml", "*.yml", "*.toml"):
        for path in root.rglob(suffix):
            if not _usable(path) or _in_excluded(path, exclude_dirs):
                continue
            if path.stat().st_size > 200_000:
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
    excluded = exclusions(root, wiki_dir)
    names, modules = index_symbols(root, excluded)
    wiki_own = {p.stem for p in wiki_dir.rglob("*.md")}
    known = names | _config_keys(root, excluded) | tree_vocabulary(root, excluded)
    known |= {pathlib.Path(m).stem for m in modules}
    known -= wiki_own          # a name that only the wiki itself introduces is not evidence

    # Deliberately NOT under `excluded`: this list answers "does this file
    # exist", not "is this name real", and it feeds only `missing_file_reference`,
    # which never blocks the verdict. A page can therefore still point at a file
    # inside its own wiki and be believed -- a known, bounded limit, not an
    # oversight.
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
    # THE BOUNDARY COMES FIRST -- above argument handling, the c67fd116 shape.
    #
    # Same shape as cli.wiki_plan: verify() indexes symbols and reads pages,
    # and then the tail mkdirs runs/ under a caller-supplied root and writes
    # wiki_verify.json. The verdict this door prints is evidence, so the run
    # that produces it passes the same boundary as everything else that writes.
    from ..budget import process_guard_boundary_decision
    from ..spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.wiki_verify",
        REGISTRY_BY_ID["cli.wiki_verify"].effects,
        (process_guard_boundary_decision(),),
    )

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
