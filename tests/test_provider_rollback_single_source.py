"""One rollback, two providers -- and a guard against the copy coming back.

``DeepSeekProvider.rollback`` and ``OllamaProvider.rollback`` were
byte-identical bodies in two files (AST- and bytecode-equal; only the
docstrings differed). That is the exact path the external write lane took on
2026-07-30 when it wrote one file's content into another and three of five
modules had to be restored from backups -- the undo path for a lane that
destroys files is the last place a second, silently diverging copy belongs.

This file pins three separate things, because a single-source claim that only
checks identity would survive a re-inlined copy, and one that only checks
behaviour would survive a divergence:

1. the two providers resolve to ONE shared implementation object;
2. neither provider module re-implements the restore loop (AST: no filesystem
   sink inside either ``rollback``), while both KEEP a ``def rollback`` --
   the Gate-0 effect registry names those two defs by module and qualname and
   resolves them statically, so deleting them to inherit would fire
   ``registry.target_missing`` (blocker);
3. the rollback semantics themselves -- restore, delete, prune, record, clear
   -- hold identically for both providers.

Plus a Gate-0 non-regression check: moving the sinks out of a registered
module must not add a blocker to the effect matrix for either rollback row.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from daedalus.providers.base import Provider
from daedalus.providers.deepseek import DeepSeekProvider
from daedalus.providers.ollama import OllamaProvider
from daedalus.spine.effect_boundary import check_conformance


ROOT = Path(__file__).resolve().parents[1]
DEEPSEEK_PY = ROOT / "daedalus" / "providers" / "deepseek.py"
OLLAMA_PY = ROOT / "daedalus" / "providers" / "ollama.py"

# The registry rows in daedalus/spine/effect_boundary.py that name these two
# methods as effectful entrypoints. Both are resolved by static AST lookup.
#
# Findings report under EITHER key and both must be watched: discovery-side
# codes (entrypoint.*) carry the target, registry-side codes (registry.*) carry
# the row id. MEASURED: filtering on targets alone silently misses
# ``registry.target_missing``, the blocker that fires when a ``def rollback``
# is deleted -- which is the single most important thing this file is here to
# notice.
ROLLBACK_SUBJECTS = frozenset({
    "daedalus.providers.deepseek:DeepSeekProvider.rollback",
    "daedalus.providers.ollama:OllamaProvider.rollback",
    "provider.deepseek.rollback",
    "provider.ollama.rollback",
})

# Every call name whose presence would mean the restore loop was written out
# again in this module rather than delegated.
FILESYSTEM_SINKS = {
    "write_bytes", "write_text", "unlink", "rmdir", "mkdir",
    "remove", "rename", "replace", "rmtree", "open",
}

PROVIDERS = [
    pytest.param(DeepSeekProvider, id="deepseek"),
    pytest.param(OllamaProvider, id="ollama"),
]


def _rollback_node(path: Path, class_name: str) -> ast.FunctionDef | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == "rollback"):
                    return item
    return None


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


# --------------------------------------------------------------------------- #
# 1. one implementation                                                        #
# --------------------------------------------------------------------------- #
def test_both_providers_resolve_to_one_shared_rollback_implementation() -> None:
    shared = Provider.__dict__.get("_rollback_writes")
    assert shared is not None, (
        "the shared restore loop is not defined on daedalus.providers.base:"
        "Provider -- there is no single source for it")
    assert DeepSeekProvider._rollback_writes is shared
    assert OllamaProvider._rollback_writes is shared
    assert "_rollback_writes" not in DeepSeekProvider.__dict__, (
        "DeepSeekProvider overrides the shared restore loop; the copy is back")
    assert "_rollback_writes" not in OllamaProvider.__dict__, (
        "OllamaProvider overrides the shared restore loop; the copy is back")


# --------------------------------------------------------------------------- #
# 2. no re-inlined copy, and the registry's two defs stay put                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path, class_name",
    [
        pytest.param(DEEPSEEK_PY, "DeepSeekProvider", id="deepseek"),
        pytest.param(OLLAMA_PY, "OllamaProvider", id="ollama"),
    ],
)
def test_provider_rollback_delegates_and_reimplements_nothing(
    path: Path, class_name: str
) -> None:
    node = _rollback_node(path, class_name)
    assert node is not None, (
        f"{class_name}.rollback is no longer defined in {path.name}; the "
        f"Gate-0 registry resolves that target by static AST lookup, so "
        f"inheriting it silently fires registry.target_missing (blocker)")

    calls = _called_names(node)
    reimplemented = sorted(calls & FILESYSTEM_SINKS)
    assert not reimplemented, (
        f"{class_name}.rollback calls {reimplemented} directly -- the restore "
        f"loop has been written out again instead of delegating to the shared "
        f"implementation, which is how the two copies diverge")
    assert "_rollback_writes" in calls, (
        f"{class_name}.rollback does not call the shared restore loop")


# --------------------------------------------------------------------------- #
# 3. identical semantics for both providers                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_rollback_restores_the_exact_original_bytes(provider_cls, tmp_path) -> None:
    doc = tmp_path / "notes.md"
    before = b"alpha\r\n\xffomega\r\n"
    doc.write_bytes(before)
    provider = provider_cls()
    provider._backups[str(doc)] = before
    doc.write_bytes(b"clobbered by the model\n")

    restored = provider.rollback()

    assert restored == [str(doc)]
    assert doc.read_bytes() == before
    assert provider.rollback_failures == []


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_rollback_deletes_created_files_and_prunes_created_dirs(
    provider_cls, tmp_path
) -> None:
    target = tmp_path / "docs" / "nested" / "new.md"
    target.parent.mkdir(parents=True)
    target.write_text("# new\n", encoding="utf-8")
    keeper = tmp_path / "keep"
    keeper.mkdir()
    (keeper / "other.txt").write_text("not ours\n", encoding="utf-8")

    provider = provider_cls()
    provider._backups[str(target)] = None
    provider._created_dirs.extend(
        [str(tmp_path / "docs"), str(target.parent), str(keeper)])

    restored = provider.rollback()

    assert restored == [str(target)]
    assert not target.exists()
    assert not target.parent.exists()
    assert not (tmp_path / "docs").exists(), "the shallower dir must be pruned too"
    assert keeper.is_dir(), "a directory that is not empty is never removed"
    assert provider.rollback_failures == []


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_rollback_of_an_already_missing_created_file_is_not_a_failure(
    provider_cls, tmp_path
) -> None:
    ghost = tmp_path / "gone.md"
    provider = provider_cls()
    provider._backups[str(ghost)] = None

    restored = provider.rollback()

    assert restored == [str(ghost)]
    assert provider.rollback_failures == []


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_unrestorable_path_is_recorded_as_a_failure_not_as_restored(
    provider_cls, tmp_path
) -> None:
    # A directory where a file is expected: write_bytes raises OSError on every
    # platform. This is the 'dirty' escalation offload() reads back.
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    good = tmp_path / "good.md"
    good.write_bytes(b"original\n")

    provider = provider_cls()
    provider.rollback_failures.append("stale entry from a previous call")
    provider._backups[str(blocked)] = b"cannot land here\n"
    provider._backups[str(good)] = b"original\n"

    restored = provider.rollback()

    assert provider.rollback_failures == [str(blocked)], (
        "the failure list must be reset per call and hold exactly the paths "
        "that could not be reverted")
    assert str(blocked) not in restored
    assert str(good) in restored, "one bad path must not abort the other restores"


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_rollback_clears_its_state_so_a_second_call_is_a_no_op(
    provider_cls, tmp_path
) -> None:
    doc = tmp_path / "notes.md"
    doc.write_bytes(b"before\n")
    provider = provider_cls()
    provider._backups[str(doc)] = b"before\n"
    provider._created_dirs.append(str(tmp_path / "absent"))

    assert provider.rollback() == [str(doc)]
    assert provider._backups == {}
    assert provider._created_dirs == []

    doc.write_bytes(b"a later, legitimate write\n")
    assert provider.rollback() == []
    assert doc.read_bytes() == b"a later, legitimate write\n", (
        "a second rollback re-restored bytes it no longer owns")


# --------------------------------------------------------------------------- #
# 4. Gate-0 non-regression                                                     #
# --------------------------------------------------------------------------- #
def test_the_effect_matrix_cost_of_this_consolidation_is_exactly_one_named_row() -> None:
    """The Gate-0 price of single-sourcing, named instead of unseen.

    ``daedalus/spine/effect_boundary.py`` resolves both rollback rows by static
    AST lookup and compares the effects it can INFER against the effects the row
    declares. Its call resolution is same-module only -- deliberately, it does
    not claim whole-program reachability -- so a lifecycle method that delegates
    across modules has no inferable sink and falls back to an interface
    contract. For an OLLAMA-surface method that contract asserts process_spawn
    and network_egress as well.

    MEASURED at the moment of consolidation: the deepseek row is unaffected
    (Surface.PYTHON falls back to filesystem_write alone, which its row already
    declares), and the ollama row gains exactly one blocker::

        entrypoint.effect_drift: daedalus.providers.ollama:OllamaProvider.rollback
          -- new undeclared effects: network_egress, process_spawn

    That finding is FALSE about the code: ``rollback`` restores bytes and
    removes directories; it opens no socket and spawns no process. It is the
    scanner's conservative fallback describing an interface, not this function.
    Correcting it means editing the ``provider.ollama.rollback`` registry row
    (or the fallback) in ``daedalus/spine/effect_boundary.py``, which moves
    ``registry_sha256`` and therefore the owner-signed Gate-0 matrix -- an
    amendment-shaped decision, not a refactor's to take. So the gap is pinned
    here rather than tolerated silently.

    This test is a two-way guard, not a rubber stamp. It goes red if the drift
    finding disappears (the registry was corrected -- delete this pin and
    restore the plain no-blocker assertion) AND if any OTHER blocker attaches
    to either row.

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-08-21]: deleting
    ``def rollback`` from ``daedalus/providers/ollama.py`` so the class
    inherits the shared loop instead -- the tempting next step of this very
    refactor -- replaces the drift finding with
    ``blocker registry.target_missing: provider.ollama.rollback -- registered
    target daedalus.providers.ollama:OllamaProvider.rollback does not exist``
    and turns this test red, along with all five ollama semantics cases (the
    inherited base class has no public ``rollback``, so ``offload`` would stop
    granting write rights and silently downgrade the lane to advisory). The
    same measurement corrected this test: the registry-side codes report under
    the row ID, not the target, so an earlier draft that watched targets alone
    stayed GREEN through the deletion.
    """
    report = check_conformance(ROOT)
    blockers = sorted(
        f"{row.code}: {row.subject} -- {row.detail}"
        for row in report.findings
        if row.severity == "blocker" and row.subject in ROLLBACK_SUBJECTS
    )

    # THE PIN RESOLVED, the way its own text prescribed (2026-08-24,
    # b90d236a): the FALLBACK was corrected -- an interface-contract default
    # with no observed sink may question a reviewed declaration as the review
    # finding entrypoint.effect_default_exceeds_declaration, but no longer
    # overrules it as a drift blocker. So: no blocker on either rollback row,
    # and the ignorance still NAMED for the ollama row rather than swallowed.
    assert not blockers, (
        "a blocker attached to a rollback row again -- the undo path of a "
        "write lane just moved out from under its registry row; read it "
        "before making this green:\n  " + "\n  ".join(blockers))
    named_defaults = [
        f"{row.code}: {row.subject}"
        for row in report.findings
        if row.code == "entrypoint.effect_default_exceeds_declaration"
        and row.subject in ROLLBACK_SUBJECTS
    ]
    assert named_defaults == [
        "entrypoint.effect_default_exceeds_declaration: "
        "daedalus.providers.ollama:OllamaProvider.rollback"
    ], (
        "the scanner's admitted ignorance about the ollama rollback stopped "
        f"being named: {named_defaults}")
