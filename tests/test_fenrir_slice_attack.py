"""FENRIR round: two CONFIRMED defects on the S2 slice path.

Both are failing tests against the current tree. They are written to fail for
exactly one reason each; see the docstrings for the mechanism.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from daedalus.structcore import index as index_mod
from daedalus.structcore.index import build_index, cached_index
from daedalus.structcore.slice import semantic_slice


@pytest.fixture(autouse=True)
def _clear_caches():
    index_mod._INDEX_CACHE.clear()
    index_mod._RESOLVER_CACHE.clear()
    yield
    index_mod._INDEX_CACHE.clear()
    index_mod._RESOLVER_CACHE.clear()


def _shell_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "reference").mkdir(parents=True)
    (root / "src" / "app.py").write_text(textwrap.dedent("""\
        from reference.vendorlib import secret_helper

        def run_job():
            return secret_helper(1)
        """), encoding="utf-8")
    (root / "reference" / "__init__.py").write_text("", encoding="utf-8")
    (root / "reference" / "vendorlib.py").write_text(textwrap.dedent("""\
        def secret_helper(x):
            # PROPRIETARY_VENDOR_BODY marker
            return x * 2
        """), encoding="utf-8")
    return root


def test_shell_body_never_enters_a_scoped_symbol_slice(tmp_path):
    """A SHELL file must not be expanded into, on ANY slice path.

    ``semantic_slice`` gates module-level expansion on ``r in modules``, but the
    symbol-level branch expands through ``index.resolution_context`` instead.
    ``_RESOLVER_CACHE`` is keyed by repo root ALONE while ``_INDEX_CACHE`` is
    keyed by root + scope fingerprint -- so any unscoped build of the same root
    overwrites the scoped resolver, and a subsequent *scoped* slice (an
    ``_INDEX_CACHE`` hit, so no rebuild repairs it) resolves callees against
    ``defs_by_file`` that still contains shell units.

    Reachable from /api/distill: two projects may share a repo_root with
    different centers, and web_api caches per (root, scope) exactly this way.
    """
    root = _shell_repo(tmp_path)
    center = ("src",)

    idx = cached_index(root, center=center)
    clean = semantic_slice(root, "src/app.py::run_job", idx=idx)
    assert "PROPRIETARY_VENDOR_BODY" not in clean["slice_text"], (
        "precondition failed: scoped slice already leaked before pollution")

    cached_index(root)  # an unscoped scan of the same root

    idx2 = cached_index(root, center=center)
    assert "reference/vendorlib.py" not in idx2["modules"], (
        "fixture inert: shell file was never withheld from the center")

    res = semantic_slice(root, "src/app.py::run_job", idx=idx2)
    leaked = [i for i in res["included"] if i["file"] == "reference/vendorlib.py"]
    assert not leaked, (
        f"shell file expanded into slice as {leaked}; "
        f"shell_boundary_stops={res['shell_boundary_stops']} claims it stopped")
    assert "PROPRIETARY_VENDOR_BODY" not in res["slice_text"]


_DETERMINISM_SNIPPET = r"""
import hashlib, sys
sys.path.insert(0, {repo!r})
from daedalus.structcore.index import build_index
from daedalus.structcore.slice import semantic_slice
idx = build_index({root!r})
r = semantic_slice({root!r}, "pkg/app.py::dispatch", idx=idx)
print(hashlib.sha256(r["slice_text"].encode()).hexdigest())
"""


def test_symbol_slice_is_byte_identical_across_hash_seeds(tmp_path):
    """The distilled slice must be byte-identical across PYTHONHASHSEED.

    ``graph.callees`` was fixed to iterate ``sorted(used)``, but the resolution
    it delegates to still iterates a SET: ``SymbolResolver.imports_by_file`` is
    built as ``{k: set(v)}`` (graph.py:95) and ``resolve`` returns the FIRST
    import that defines the name (graph.py:78). When two imported modules define
    the same name, WHICH unit is emitted depends on set iteration order of the
    rel-path strings, i.e. on PYTHONHASHSEED.
    """
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    for n in "abcdef":
        (root / "pkg" / f"mod_{n}.py").write_text(
            f"def handle(x):\n    return 'FROM_MOD_{n.upper()}'\n", encoding="utf-8")
    (root / "pkg" / "app.py").write_text(
        "".join(f"from pkg.mod_{n} import handle as h_{n}\n" for n in "abcdef")
        + "\n\ndef dispatch(payload):\n    return handle(payload)\n", encoding="utf-8")

    repo = str(Path(__file__).resolve().parents[1])
    code = _DETERMINISM_SNIPPET.format(repo=repo, root=str(root))
    hashes = {}
    for seed in ("0", "1", "12345", "99991", "31337"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, cwd=repo)
        assert out.returncode == 0, out.stderr
        hashes[seed] = out.stdout.strip().splitlines()[-1]

    assert len(set(hashes.values())) == 1, (
        f"slice_text differs across PYTHONHASHSEED: {hashes}")
