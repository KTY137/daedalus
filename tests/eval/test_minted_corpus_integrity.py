"""The minted corpus must survive leaving the machine that minted it.

These are corpus-integrity tests, not mint unit tests (those live in
tests/test_eval_mint.py). They assert properties of the COMMITTED store,
``daedalus/eval/minted_tasks.json``, because that file is shared, reviewed,
and is meant to become a frozen public task set for Gate 3.

WHAT WENT WRONG, 2026-09-09, and why this file exists
-----------------------------------------------------
Both mint sites wrote ``str(Path(repo_root).resolve())`` -- an absolute host
path -- into the committed store. Measured consequence:

  * 17 tasks pinned to ``C:/Users/nukei/Desktop/agent_env``, a checkout on a
    DIFFERENT machine. ``resolve_task_repo`` raised on all 17 here. They had
    been unusable for as long as they had existed, on every machine but one.
  * 31 tasks (minted an hour earlier, by me) pinned to a disposable git
    worktree. Those resolved -- but only while the process happened to be
    running inside that worktree, and not at all once it was removed.

Nothing detected either, because nothing ever asked the store to resolve
itself. That is the gap these tests close.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from daedalus.eval import mint
from daedalus.eval.tasks import AGENT_ENV_ROOT, resolve_task_repo


# --------------------------------------------------------------------------- #
# Known corpus rot: a minted task pins a target path at mint time, the         #
# repository moves on, and nothing revalidates. Each entry names the task, the #
# commit that removed its target, and why the task is kept anyway.             #
#                                                                              #
# Entries are KEPT, not deleted: AGENTS.md rule 4 ("retain negative            #
# experimental evidence"). The task remains valid AT ITS ``minted_at_sha``;    #
# what expired is the assumption that HEAD still contains what it names. A new #
# row here should be a deliberate acknowledgement, never a convenient way to   #
# silence this test.                                                           #
# --------------------------------------------------------------------------- #
RETIRED_TARGET_ALLOWLIST = {
    "mint-commit-a8ef3c7b3fe4": (
        "apps/web/src/App.tsx was deleted by 321917d1 "
        "'refactor(web): retire Classic app in G1-UI-02'. The task is still "
        "well-formed at its minted_at_sha 12fd47e9; it is HEAD that moved."
    ),
}


@pytest.fixture(scope="module")
def stored():
    return mint.load_minted_tasks()


def test_store_is_not_empty(stored):
    """Guard against every assertion below passing vacuously on an empty store."""
    assert len(stored) >= 40, (
        f"minted store holds only {len(stored)} tasks; the corpus assertions "
        "below would be near-vacuous. If the store was deliberately emptied, "
        "update this floor deliberately."
    )


def test_no_stored_repo_is_an_absolute_host_path(stored):
    """The defect itself, pinned. An absolute path survives exactly one machine."""
    offenders = {t["id"]: t["repo"] for t in stored
                 if isinstance(t.get("repo"), str) and os.path.isabs(t["repo"])}
    assert not offenders, (
        "these tasks name an absolute host path as their repo, which no other "
        "machine can resolve: " + repr(offenders)
    )


def test_every_stored_repo_resolves_here(stored):
    """The property that actually matters: this checkout can resolve the corpus.

    Stronger than the shape check above -- a label that is portable but simply
    wrong (a fixture that was renamed) fails here and passes there.
    """
    unresolvable = {}
    for t in stored:
        try:
            resolve_task_repo(t["repo"])
        except Exception as exc:  # ValueError today; do not over-narrow
            unresolvable[t["id"]] = f"{t['repo']!r}: {exc}"
    assert not unresolvable, (
        "these tasks' repo references do not resolve in this checkout: "
        + repr(unresolvable)
    )


def test_stored_targets_exist_or_are_acknowledged_as_retired(stored):
    """Corpus rot is allowed to exist; it is not allowed to be invisible."""
    missing = {}
    for t in stored:
        rel = (t.get("target") or "").split("::", 1)[0]
        if not rel:
            missing[t["id"]] = "task has no target at all"
            continue
        if not (Path(resolve_task_repo(t["repo"])) / rel).is_file():
            missing[t["id"]] = rel

    unacknowledged = {k: v for k, v in missing.items()
                      if k not in RETIRED_TARGET_ALLOWLIST}
    assert not unacknowledged, (
        "these tasks name a target that no longer exists, and are not in "
        "RETIRED_TARGET_ALLOWLIST: " + repr(unacknowledged) + ". Add a row "
        "naming the commit that removed it and why the task is kept, or fix "
        "the target. Do not delete the task to make this pass."
    )

    stale_rows = set(RETIRED_TARGET_ALLOWLIST) - set(missing)
    assert not stale_rows, (
        "these ids are allowlisted as retired but their targets exist again: "
        f"{sorted(stale_rows)}. Remove the rows -- an allowlist that outlives "
        "its reason silences the next real failure."
    )


def test_default_store_write_refuses_an_absolute_repo(monkeypatch, tmp_path):
    """The writer-side guard, exercised against the DEFAULT store path.

    monkeypatched to a temp file so the test never touches the real corpus,
    while still taking the ``p == DEFAULT_MINT_STORE_PATH`` branch.
    """
    fake_default = str(tmp_path / "minted_tasks.json")
    monkeypatch.setattr(mint, "_COMMITTED_STORE_PATH",
                        os.path.normcase(os.path.realpath(fake_default)))

    task = {"id": "x", "repo": str(tmp_path / "somewhere"), "target": "a.py",
            "must_include": ["z"]}
    with pytest.raises(ValueError, match="not a portable label"):
        mint.save_minted_tasks([task], fake_default)

    assert not os.path.exists(fake_default), (
        "the store was written before the refusal -- the guard must run "
        "before any bytes reach disk"
    )


def test_a_custom_store_path_is_not_policed(monkeypatch, tmp_path):
    """The documented limit of the guard, pinned so it cannot drift silently.

    A test minting against a temp fixture legitimately has no portable label.
    That is allowed at a caller-chosen path; only the repository's own corpus
    is protected. If this ever becomes undesirable, the docstring on
    ``_refuse_nonportable_repos`` is the thing to change first.
    """
    monkeypatch.setattr(mint, "_COMMITTED_STORE_PATH",
                        os.path.normcase(os.path.realpath(str(tmp_path / "real.json"))))
    scratch = str(tmp_path / "scratch.json")
    task = {"id": "x", "repo": str(tmp_path / "fixture"), "target": "a.py",
            "must_include": ["z"]}
    assert mint.save_minted_tasks([task], scratch) == scratch
    assert os.path.exists(scratch)


def test_portable_label_maps_this_checkout_to_agent_env():
    """``agent_env`` means 'the checkout this harness runs from' -- which is
    exactly why it travels. Minted here, resolvable there."""
    assert mint._portable_repo_label(AGENT_ENV_ROOT) == "agent_env"
    assert mint._portable_repo_label(Path(AGENT_ENV_ROOT)) == "agent_env"


def test_minting_here_produces_a_portable_label(stored):
    """Close the loop: the tests above read the STORE, so on their own they
    would never notice the mint SITES regressing to an absolute path -- a
    fixed store and a broken writer look identical to them until the next
    mint. This one exercises the writer.

    It re-mints a commit the store was actually minted from, so it cannot be
    skipped by picking a commit that happens to yield nothing.
    """
    seeds = [t for t in stored
             if t.get("label_provenance") == "independent_text_diff"
             and t.get("minted_at_sha")]
    if not seeds:
        pytest.skip("no text-minted task in the store to re-mint from")
    sha = seeds[0]["minted_at_sha"]

    minted = mint.mint_text_from_commit(AGENT_ENV_ROOT, sha)
    assert minted, (
        f"re-minting {sha[:12]} produced nothing, but the store holds a task "
        "minted from it -- either minting regressed or the commit is no "
        "longer reachable in this checkout"
    )
    repos = {t["repo"] for t in minted}
    assert repos == {"agent_env"}, (
        f"minting in this checkout produced repo refs {repos!r}; expected the "
        "portable label 'agent_env'. A mint site has regressed to writing an "
        "absolute host path."
    )


def test_portable_label_leaves_an_unknown_root_alone():
    """No guessing. An unrecognized root comes back unchanged, and is refused
    later at the store boundary rather than silently relabelled as this repo --
    mislabelling a temp fixture 'agent_env' would score an arm against the
    wrong corpus entirely."""
    unknown = os.path.abspath(os.sep + os.path.join("nowhere", "in", "particular"))
    assert mint._portable_repo_label(unknown) == unknown.replace("\\", "/")


def test_a_differently_cased_path_cannot_slip_past_the_write_guard(monkeypatch, tmp_path):
    """The gate used to be a case-SENSITIVE string compare on a
    case-INSENSITIVE filesystem.

    Found by an adversarial pass: lowercasing the drive and directories gave a
    path that opens the very same file and compared unequal, so the refusal was
    skipped and a ``C:/Users/nukei/...`` repo landed in the real corpus. The
    store-side tests still caught the result -- defence in depth held -- but
    the writer-side guard itself was porous, and a guard that only works when
    the caller spells the path the way you did is not a guard.
    """
    real = tmp_path / "minted_tasks.json"
    monkeypatch.setattr(mint, "_COMMITTED_STORE_PATH",
                        os.path.normcase(os.path.realpath(str(real))))
    task = {"id": "x", "repo": "C:/Users/nukei/Desktop/agent_env",
            "target": "a.py", "must_include": ["z"]}
    for spelling in (str(real), str(real).lower(), str(real).replace("\\", "/").lower()):
        with pytest.raises(ValueError, match="not a portable label"):
            mint.save_minted_tasks([task], spelling)
        assert not os.path.exists(real), f"{spelling!r} wrote the corpus anyway"


def test_a_relative_nonportable_repo_is_also_refused():
    """``os.path.isabs`` alone let ``../../nukei/Desktop/agent_env`` through --
    just as unportable, and not absolute. The guard asks whether the value is a
    declared label instead of guessing from the path's shape."""
    task = {"id": "x", "repo": "../../nukei/Desktop/agent_env",
            "target": "a.py", "must_include": ["z"]}
    with pytest.raises(ValueError, match="not a portable label"):
        mint._refuse_nonportable_repos([task])
