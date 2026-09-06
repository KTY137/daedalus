"""Frozen gate G1-SELF-01: docstring symbol references in ONE .py file must resolve.

The repository already owns this defect class.  ``daedalus/spine/docrefs.py``
defines it exactly -- "a reference in the documentation to a code symbol that
does not exist" -- and judges a reference only when THE MODULE EXISTS AND THE
SYMBOL DOES NOT, which is its whole false-positive filter.  Its corpus is
``DOC_GLOBS = ("docs/**/*.md", "README.md")``, so a docstring, which is also
prose, is outside it.

This gate applies the repository's OWN resolver -- ``docrefs.resolve_reference``
-- to the Sphinx cross-references written inside one Python file.  Extraction is
deliberately narrow: only ``:class:``/``:func:``/``:meth:``/``:mod:``/``:data:``/
``:attr:``/``:exc:`` roles whose target starts with ``daedalus.``, i.e. only
first-party references the tree can actually settle.

Exit 0 when every such reference resolves, 1 when any is broken.  Read-only:
it parses files with ``ast`` and imports nothing it inspects.

Usage: python gate_docstring_symbol_refs.py <repo_root> <relative/target.py>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROLE_REF = re.compile(
    r":(?:class|func|meth|mod|data|attr|exc):`~?(daedalus\.[A-Za-z0-9_.]+)`"
)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: gate_docstring_symbol_refs.py <repo_root> <relative.py>")
        return 2
    root = Path(argv[1]).resolve()
    rel = argv[2].replace("\\", "/")
    sys.path.insert(0, str(root))
    from daedalus.spine.docrefs import Reference, resolve_reference  # noqa: E402

    text = (root / rel).read_text(encoding="utf-8")
    cache: dict = {}
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in _ROLE_REF.finditer(line):
            raw = m.group(1)
            out = resolve_reference(Reference(doc_path=rel, line=lineno, raw=raw), root, cache)
            findings.append(out)

    broken = [f for f in findings if f.state == "broken"]
    resolving = [f for f in findings if f.state == "resolving"]
    report = {
        "gate": "G1-SELF-01/docstring-symbol-refs",
        "target": rel,
        "n_references": len(findings),
        "n_resolving": len(resolving),
        "n_broken": len(broken),
        "broken": [
            {"line": f.line, "raw": f.raw, "module_path": f.module_path,
             "symbol": f.symbol, "why": f.why}
            for f in broken
        ],
        "passed": not broken,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not broken else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
