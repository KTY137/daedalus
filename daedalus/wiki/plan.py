"""Plan a project wiki: survey the tree, partition topics, emit agent tasks.

This is the deterministic half of automatic wiki generation. It reads a
repository and produces a `WikiPlan`: a set of topic buckets, each with the
files it covers, the symbols that must be named, and a ready-to-dispatch task
prompt. It performs no effects -- no model call, no network, no write outside
the plan it returns.

The effectful half (fan out the tasks, search the web, write pages) is a
separate step so that spend, egress and write roots stay at one boundary rather
than being buried inside a docs generator.

Why the constraints in the emitted prompt are what they are, measured
2026-08-25 on this repository and on project_tct:

* A page must name real symbols in backticks and link real files, because those
  are the only two things that become cross-plane edges. Prose alone adds
  nodes to the knowledge plane that connect to nothing.
* A concept must appear on more than one page. Modelling mentions per file
  rather than per concept put cross-plane survival in a 3-core at 0%; per
  concept it is 26-28%. A concept named once still dies.
* Anything from outside the repository must carry its URL, because
  ``verify.unsourced_claim`` fails the page otherwise.
"""

from __future__ import annotations

import ast
import collections
import dataclasses
import json
import pathlib
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages",
             ".mypy_cache", ".pytest_cache", "reference", "lab_assets", "docs",
             # Artefact and output trees. Without these the planner treats every
             # experiment output directory as a topic: on this repository it
             # produced 602 "topics", one per run directory under `runs/`.
             "runs", "artifacts", "artifacts_claude", "artifacts_codex",
             "scratchpad", "build", "dist", "htmlcov", ".tox", "spikes"}
MIN_BUCKET_FILES = 2
MIN_BUCKET_LOC = 200


def _venv_roots(root: pathlib.Path) -> set[pathlib.Path]:
    """Directories that are virtual environments, whatever they are called.

    A venv is identified by its own marker file, not by being named `venv`.
    project_tct's environment put `Scripts/` and `bin/` into the topic list
    until this was added.
    """
    return {cfg.parent for cfg in root.rglob("pyvenv.cfg")}


def _usable(path: pathlib.Path, venvs: frozenset[pathlib.Path] = frozenset()) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return not any(venv in path.parents for venv in venvs)


@dataclasses.dataclass(frozen=True)
class Topic:
    """One bucket of the repository, and what a page about it must contain."""

    name: str
    directory: str
    files: tuple[str, ...]
    symbols: tuple[str, ...]
    loc: int

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def survey(root: pathlib.Path) -> list[Topic]:
    """Partition the tree into topics by directory, ranked by weight."""
    venvs = frozenset(_venv_roots(root))
    by_dir: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
    for path in root.rglob("*.py"):
        if not _usable(path, venvs) or path.stat().st_size > 400_000:
            continue
        rel = path.relative_to(root)
        if rel.name.startswith("test_") or "tests" in rel.parts:
            continue
        by_dir[rel.parent.as_posix()].append(path)

    topics: list[Topic] = []
    for directory, paths in sorted(by_dir.items()):
        if len(paths) < MIN_BUCKET_FILES:
            continue
        symbols: list[str] = []
        loc = 0
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            loc += text.count("\n")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("_"):
                        symbols.append(node.name)
        topics.append(
            Topic(
                name=directory.rsplit("/", 1)[-1] or root.name,
                directory=directory,
                files=tuple(sorted(p.relative_to(root).as_posix() for p in paths)),
                symbols=tuple(sorted(set(symbols))),
                loc=loc,
            )
        )
    topics = [t for t in topics if t.loc >= MIN_BUCKET_LOC]
    topics.sort(key=lambda t: -t.loc)
    return topics


def assign(topics: list[Topic], authors: int) -> list[list[Topic]]:
    """Greedy balanced partition by lines of code, so no author gets the tail."""
    buckets: list[list[Topic]] = [[] for _ in range(max(1, authors))]
    weight = [0] * max(1, authors)
    for topic in topics:
        i = weight.index(min(weight))
        buckets[i].append(topic)
        weight[i] += topic.loc
    return buckets


PROMPT = """Du schreibst einen Teil eines technischen Wikis für das Repository `{root}`.

DEIN THEMENBEREICH: {names}

Dateien, die du abdecken musst ({n_files}):
{files}

Symbole, die im Quelltext dieser Dateien öffentlich definiert sind — nenne die
wichtigsten davon namentlich, und erfinde keine anderen:
{symbols}

AUSGABE: neue Markdown-Dateien unter `{wiki_dir}`, eine je Themenblock, plus
eine Index-Seite `{index}`, die deine Seiten verlinkt.

HARTE ANFORDERUNGEN (sie sind maschinell geprüft, siehe daedalus.wiki.verify):
1. Jede Seite nennt echte Codesymbole in Backticks. Ein Symbol, das im Baum
   nicht existiert, ist ein Fehlschlag (`unknown_symbol`).
2. Jede Seite verlinkt die zugehörigen Quelldateien mit relativen Links. Ein
   Link, der nicht auflöst, ist ein Fehlschlag (`broken_link`).
3. Jede Seite verlinkt mindestens drei andere Wiki-Seiten.
4. Zentrale Konzepte müssen auf MEHREREN Seiten vorkommen. Ein Konzept, das nur
   einmal genannt wird, trägt nichts (`thin_concept`) — gemessen: es überlebt
   keinen 3-Kern und erzeugt keine nutzbare Verbindung.
5. Wissen von außerhalb des Repositories — Herstellerdokumentation, Normen,
   Bibliotheks-APIs, Fachliteratur — kommt in einen Block, der so beginnt:

       > **Extern:** ...
       > Quelle: https://...

   Ohne URL im Block ist es ein Fehlschlag (`unsourced_claim`). Recherchiere
   solches Wissen aktiv per Websuche, wo es dem Leser hilft, aber schreibe
   nichts Externes ohne Quelle.
6. Genauigkeit vor Umfang. Lies den Code. Was du nicht sicher weißt, markierst
   du als "**Ungeklärt:**" statt es zu erfinden.

VERBOTEN: bestehende Dateien ändern; `git add` oder `git commit`; irgendetwas
aus `reference/`, `lab_assets/` oder `sources/git_history/` lesen oder zitieren;
Zugangsdaten, Seriennummern, IP-Adressen oder Ressourcenstrings übernehmen.

Melde zurück: Seitenzahl, Dateinamen, Zahl der genannten distinkten Symbole,
und was du als "Ungeklärt" markiert hast."""


def build_plan(root: pathlib.Path, authors: int, wiki_dir: str) -> dict:
    topics = survey(root)
    buckets = assign(topics, authors)
    tasks = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        files = [f for t in bucket for f in t.files]
        symbols = sorted({s for t in bucket for s in t.symbols})
        names = ", ".join(t.name for t in bucket)
        tasks.append(
            {
                "author": i + 1,
                "topics": [t.name for t in bucket],
                "loc": sum(t.loc for t in bucket),
                "files": files,
                "index_page": f"{bucket[0].name}-index.md",
                "prompt": PROMPT.format(
                    root=root,
                    names=names,
                    n_files=len(files),
                    files="\n".join(f"  - `{f}`" for f in files[:60]),
                    symbols="\n".join(f"  - `{s}`" for s in symbols[:120]),
                    wiki_dir=wiki_dir,
                    index=f"{bucket[0].name}-index.md",
                ),
            }
        )
    return {
        "root": str(root),
        "wiki_dir": wiki_dir,
        "authors": len(tasks),
        "topics": [t.as_dict() for t in topics],
        "total_loc": sum(t.loc for t in topics),
        "tasks": tasks,
    }


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("usage: python -m daedalus.wiki.plan <repo-root> [authors] [wiki-dir]")
        return 2
    if args[0].startswith("-"):
        print(f"unknown option: {args[0]}")
        print("usage: python -m daedalus.wiki.plan <repo-root> [authors] [wiki-dir]")
        return 2
    root = pathlib.Path(args[0]).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}")
        return 2
    authors = int(args[1]) if len(args) > 1 else 3
    wiki_dir = args[2] if len(args) > 2 else "docs/wiki"
    plan = build_plan(root, authors, wiki_dir)
    print(f"{len(plan['topics'])} Themen, {plan['total_loc']} Zeilen, "
          f"auf {plan['authors']} Autoren verteilt")
    for task in plan["tasks"]:
        print(f"  Autor {task['author']}: {', '.join(task['topics'])} "
              f"({len(task['files'])} Dateien, {task['loc']} Zeilen)")
    out = root / "runs" / "wiki_plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
