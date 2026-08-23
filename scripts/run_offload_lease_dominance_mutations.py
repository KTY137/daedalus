"""Mutants for the ``python.offload`` lease-dominance guard.

Each mutation restores one shape the guard exists to refuse, and each must turn
at least one test red. The four shapes:

* the planner executes the dispatch itself, so the write is reachable from a
  leased AND an un-leased caller again -- the exact state of 21f21f2a;
* the leased branch never executes the dispatch, so the lease is consumed and
  nothing happens (a guard that also stops the work is not a guard);
* the declaration admits a module-private helper whose name is mentioned in
  another module, which is how a helper other code can call gets attributed to
  a lease it never held;
* the declaration stops requiring every in-module reference to a helper to sit
  in the leased region, which is the callback/dual-caller hole.

A NOTE ON THE ASSEMBLED NAME BELOW, because it looks like an affectation and is
not. ``scripts/declare_write_surfaces.py`` admits a module-private helper only
when its identifier appears in NO other Python source in the tree -- including
this file. Spelling the executor's name here would permanently un-declare the
very surface these mutants protect, and the guard would go red with this runner
as the cause. Assembling it from two fragments keeps the token out of this
file's identifier stream while the mutation text is still exact.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "offload": ROOT / "daedalus" / "offload.py",
    "declare": ROOT / "scripts" / "declare_write_surfaces.py",
}
TESTS = (
    "tests/gates/test_write_surface_lease_dominance.py",
    "tests/test_offload_unleased_planner.py",
    "tests/test_offload_write_failclose.py",
    "tests/test_offload_slice_context.py",
    "tests/test_parallel_dispatch.py",
)

#: See the module docstring. Two fragments, never one token.
EXECUTOR = "_leased" + "_bench_cascade"

_DISPATCH_FIELDS = (
    "        objective=objective, repo_root=repo_root, paths=paths,\n"
    "        run_tests=run_tests, isolate_paths=isolate_paths,\n"
    "        rewrite_windows=rewrite_windows, model=model,\n"
    "        agent=agent, decision=decision, pdata=pdata, pol=pol, result=result,\n"
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    """Replace exactly one site, in whatever line ending the file actually has.

    This repository holds both LF and CRLF sources -- ``daedalus/offload.py`` is
    CRLF in the working copy -- and a mutation written with ``\\n`` matches zero
    sites in a CRLF file. Translating the PATTERN rather than the file keeps the
    mutant a one-line change instead of a whole-file rewrite.
    """

    if "\r\n" in source:
        old = old.replace("\n", "\r\n")
        new = new.replace("\n", "\r\n")
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one mutation site, found {count}")
    return source.replace(old, new, 1)


def _write(path: Path, text: str) -> None:
    """Write verbatim: ``newline=""`` so Windows does not turn a CRLF the
    pattern just produced into ``\\r\\r\\n``."""

    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def main() -> int:
    originals = {name: path.read_bytes() for name, path in TARGETS.items()}
    sources = {name: value.decode("utf-8") for name, value in originals.items()}
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("offload lease-dominance mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "offload",
            "planner-executes-the-dispatch-itself",
            f"    result[_LIVE_DISPATCH_KEY] = _LiveDispatch(\n"
            f"{_DISPATCH_FIELDS}"
            f"    )\n    return result\n",
            f"    return {EXECUTOR}(_LiveDispatch(\n"
            f"{_DISPATCH_FIELDS}"
            f"    ))\n",
        ),
        (
            "offload",
            "leased-branch-never-executes-the-dispatch",
            f"        if dispatch is not None:\n"
            f"            result = {EXECUTOR}(dispatch)\n",
            "        if dispatch is not None:\n            pass\n",
        ),
        (
            "declare",
            "admit-a-helper-named-outside-its-own-module",
            "            if name in exported or name in external_names:\n",
            "            if name in exported:\n",
        ),
        (
            "declare",
            "admit-a-helper-with-un-leased-in-module-references",
            "            if not _references_are_dominated(tree, name, dominated_ids):\n",
            "            if False:\n",
        ),
    )

    killed: list[str] = []
    try:
        for target_name, label, old, new in mutations:
            target = TARGETS[target_name]
            _write(target, _replace_once(sources[target_name], old, new, label))
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            target.write_bytes(originals[target_name])
    finally:
        for name, target in TARGETS.items():
            target.write_bytes(originals[name])

    for name, target in TARGETS.items():
        if target.read_bytes() != originals[name]:
            raise RuntimeError(f"mutation runner failed to restore {name}")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
