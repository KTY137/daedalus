"""Tests for the git plumbing -- the module that had no test file at all.

Two gaps motivated this file, both found by mutation testing rather than by
reading:

* **M15.** ``gitio.read_blobs`` supplies *all* document content in this
  package.  Made to return ``b""`` for every blob, the published BM25 table
  would collapse to near zero -- and the whole suite still passed, because
  nothing constructed a ``BlobStore``, called ``read_blobs``, or exercised
  ``build_universe``.  Every content number rested on an untested function.
* **M8.** ``_READ_ONLY_VERBS`` gated ``_run``, but ``read_blobs`` shelled
  ``cat-file --batch`` around it and ``RecencyPrior._recency`` shelled
  ``git log`` straight out of ``retrievers.py``.  The gate was enforced at
  four call sites, skipped at the fifth, and tested at none.

These build a real (tiny) git repository in a temp directory, because a mock
of git cannot fail the way git fails.  The fixture has three commits on
purpose: the pre-image is *not* the commit that created the gold file, so an
oracle confined to the pre-image cannot name the gold file first by accident.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import gitio, harness  # noqa: E402
from s09_eval.contract import Budget, QueryView  # noqa: E402
from s09_eval.retrievers import RecencyPrior  # noqa: E402
from s09_eval.taskset import Case  # noqa: E402

ALPHA_FIRST = b"def alpha():\n    return 'the first revision of alpha'\n"
ALPHA_SECOND = b"def alpha():\n    return 'the second revision of alpha'\n"
README_BODY = b"# notes\n\nthe knowledge plane representative\n"
CHANGELOG_BODY = b"# changelog\n\ntouched only by the pre-image commit\n"
PARENT_TREE = {"pkg/alpha.py", "notes/readme.md", "notes/changelog.md"}
GOLD = "pkg/alpha.py"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True
    )
    return proc.stdout.decode("utf-8", "replace").strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c", "user.email=s09@example.invalid",
        "-c", "user.name=s09 fixture",
        "commit", "--quiet", "-m", message,
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory) -> dict:
    """Three commits: seed, pre-image, and the commit holding the answer."""
    repo = tmp_path_factory.mktemp("s09_fixture_repo")
    _git(repo, "init", "--quiet", ".")
    (repo / "pkg").mkdir()
    (repo / "notes").mkdir()
    (repo / "pkg" / "alpha.py").write_bytes(ALPHA_FIRST)
    (repo / "notes" / "readme.md").write_bytes(README_BODY)
    seed = _commit(repo, "seed the tree")

    (repo / "notes" / "changelog.md").write_bytes(CHANGELOG_BODY)
    parent = _commit(repo, "the pre-image touches only the changelog")

    (repo / "pkg" / "alpha.py").write_bytes(ALPHA_SECOND)
    (repo / "pkg" / "beta.py").write_bytes(b"def beta():\n    return 2\n")
    child = _commit(repo, "edit alpha and create beta")
    return {"repo": repo, "seed": seed, "parent": parent, "child": child}


def _case(fixture_repo: dict) -> Case:
    return Case(
        case_id="c00",
        commit=fixture_repo["child"],
        parent=fixture_repo["parent"],
        committed_at=0,
        query_raw="edit alpha",
        query_scrubbed="edit",
        gold=(GOLD,),
        gold_created_dropped=(),
        leak_tokens=("alpha",),
        universe_size=len(PARENT_TREE),
    )


# --------------------------------------------------------------------- M8
def test_run_refuses_a_mutating_git_verb(fixture_repo):
    """The verb allowlist is the door; this proves the door is shut."""
    with pytest.raises(gitio.GitError) as excinfo:
        gitio._run(fixture_repo["repo"], ["commit", "--allow-empty", "-m", "no"])
    assert "non-read-only" in str(excinfo.value)


def test_run_refuses_an_empty_command(fixture_repo):
    with pytest.raises(gitio.GitError):
        gitio._run(fixture_repo["repo"], [])


def test_run_disables_transports_lazy_fetch_prompts_replacements_and_locks(
    fixture_repo, monkeypatch, tmp_path
):
    seen = {}
    real_run = gitio.subprocess.run
    trace = tmp_path / "git-trace.log"
    trace2 = tmp_path / "git-trace2-event.log"
    hostile = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "hostile-routing-value",
        "GIT_DIR": "hostile-routing-value",
        "GIT_OBJECT_DIRECTORY": "hostile-routing-value",
        "GIT_TRACE": str(trace),
        "GIT_TRACE2_EVENT": str(trace2),
        "GIT_WORK_TREE": "hostile-routing-value",
    }
    for name, value in hostile.items():
        monkeypatch.setenv(name, value)

    def spy(*args, **kwargs):
        seen.update(kwargs["env"])
        return real_run(*args, **kwargs)

    monkeypatch.setattr(gitio.subprocess, "run", spy)
    assert gitio.rev_parse(fixture_repo["repo"], "HEAD") == fixture_repo["child"]
    assert seen["GIT_ALLOW_PROTOCOL"] == ""
    assert seen["GIT_NO_LAZY_FETCH"] == "1"
    assert seen["GIT_TERMINAL_PROMPT"] == "0"
    assert seen["GCM_INTERACTIVE"] == "Never"
    assert seen["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert seen["GIT_OPTIONAL_LOCKS"] == "0"
    assert seen["GIT_PROTOCOL_FROM_USER"] == "0"
    inherited_git = {
        name: value
        for name, value in seen.items()
        if name.upper().startswith("GIT_")
    }
    assert inherited_git == gitio._SAFE_GIT_ENV
    assert not trace.exists()
    assert not trace2.exists()


def test_read_blobs_goes_through_the_read_only_gate(fixture_repo, monkeypatch):
    """``cat-file --batch`` used to bypass ``_run`` because it needs stdin."""
    seen = []
    real = gitio._run

    def spy(repo, args, stdin=None):
        seen.append(list(args))
        return real(repo, args, stdin)

    monkeypatch.setattr(gitio, "_run", spy)
    tree = gitio.list_tree(fixture_repo["repo"], fixture_repo["parent"])
    gitio.read_blobs(fixture_repo["repo"], [blob for blob, _ in tree.values()])
    assert ["cat-file", "--batch"] in seen, (
        "read_blobs shelled git directly instead of through the read-only gate"
    )


def test_recency_prior_reads_history_through_the_gate(fixture_repo, monkeypatch):
    """``RecencyPrior`` used to shell ``git log`` straight out of retrievers.py."""
    seen = []
    real = gitio._run

    def spy(repo, args, stdin=None):
        seen.append(list(args))
        return real(repo, args, stdin)

    monkeypatch.setattr(gitio, "_run", spy)
    prior = RecencyPrior(repo=fixture_repo["repo"], window=10)
    order = prior._recency(fixture_repo["repo"], fixture_repo["child"])
    assert any(args and args[0] == "log" for args in seen), (
        "RecencyPrior read history without passing the read-only gate"
    )
    assert order[GOLD] >= 1


def test_recency_prior_follows_the_repo_the_harness_hands_it(fixture_repo, tmp_path):
    """Isolation is worthless if a retriever ignores ``QueryView.repo``."""
    isolation = harness.PreimageIsolation(fixture_repo["repo"], root=tmp_path / "iso")
    try:
        clone = isolation.repo_for(fixture_repo["parent"])
        universe = harness.build_universe(
            fixture_repo["repo"], _case(fixture_repo), Budget(),
            harness.BlobStore(fixture_repo["repo"], Budget()),
        )
        ranking = RecencyPrior(repo=fixture_repo["repo"], window=10).rank(
            QueryView("c00", "", "raw", fixture_repo["parent"], clone), universe
        )
    finally:
        isolation.close()
    assert ranking, "the prior read nothing out of the clone it was handed"
    assert ranking[0] == "notes/changelog.md", (
        "the prior ranked by history the pre-image clone does not contain"
    )


def test_log_name_only_reports_touched_paths(fixture_repo):
    paths = gitio.log_name_only(fixture_repo["repo"], fixture_repo["child"], 10)
    assert GOLD in paths
    assert "pkg/beta.py" in paths


# -------------------------------------------------------------------- M15
def test_read_blobs_returns_the_actual_file_bytes(fixture_repo):
    """The function every content number in the published table rests on."""
    tree = gitio.list_tree(fixture_repo["repo"], fixture_repo["parent"])
    assert set(tree) == PARENT_TREE
    blobs = gitio.read_blobs(
        fixture_repo["repo"], [blob for blob, _ in tree.values()]
    )
    bodies = set(blobs.values())
    assert ALPHA_FIRST in bodies, "read_blobs returned no content for a real blob"
    assert README_BODY in bodies
    assert all(payload for payload in blobs.values()), "a blob came back empty"


def test_read_blobs_skips_unknown_objects_without_raising(fixture_repo):
    tree = gitio.list_tree(fixture_repo["repo"], fixture_repo["parent"])
    known = [blob for blob, _ in tree.values()][:1]
    blobs = gitio.read_blobs(fixture_repo["repo"], known + ["0" * 40])
    assert len(blobs) == 1


def test_read_blobs_on_an_empty_request_does_not_shell_out(fixture_repo, monkeypatch):
    monkeypatch.setattr(
        gitio, "_run", lambda *a, **k: pytest.fail("empty request still ran git")
    )
    assert gitio.read_blobs(fixture_repo["repo"], []) == {}


def test_build_universe_hands_retrievers_real_content(fixture_repo):
    """End to end: pre-image tree -> BlobStore -> Candidate.text().

    Nothing exercised this path before, so a ``read_blobs`` that returned
    nothing would have produced an all-empty universe, a collapsed BM25
    table, and a green suite.
    """
    budget = Budget()
    store = harness.BlobStore(fixture_repo["repo"], budget)
    universe = harness.build_universe(
        fixture_repo["repo"], _case(fixture_repo), budget, store
    )
    by_path = {c.path: c for c in universe}
    assert set(by_path) == PARENT_TREE
    assert "the first revision of alpha" in by_path[GOLD].text(), (
        "the universe carried no content -- every content-based number is void"
    )
    assert by_path[GOLD].raw == ALPHA_FIRST
    assert store.fetched == len(PARENT_TREE)

    # the pre-image really is the pre-image: the child's new file is absent,
    # and the gold file is at its OLD content
    assert "pkg/beta.py" not in by_path
    assert b"second revision" not in by_path[GOLD].raw


def test_blob_store_reuses_across_cases(fixture_repo):
    budget = Budget()
    store = harness.BlobStore(fixture_repo["repo"], budget)
    tree = gitio.list_tree(fixture_repo["repo"], fixture_repo["parent"])
    shas = [blob for blob, _ in tree.values()]
    store.ensure(shas)
    fetched_once = store.fetched
    store.ensure(shas)
    assert store.fetched == fetched_once, "a cached blob was fetched twice"
    assert store.reused >= len(shas)


# --------------------------------------------------------------------- A3
def test_preimage_clone_does_not_contain_the_answer_commit(fixture_repo, tmp_path):
    """The oracle hole, closed by absence rather than by instruction.

    ``QueryView.revision`` says "read nothing after the case".  A retriever
    that ignored that and walked git forward to its own child commit scored
    MRR 1.000 with nothing objecting.  Inside a pre-image clone the child is
    not merely unreferenced -- it is not in the object store.
    """
    dest = tmp_path / "preimage"
    gitio.make_preimage_clone(fixture_repo["repo"], fixture_repo["parent"], dest)

    assert gitio.contains_commit(dest, fixture_repo["parent"])
    assert gitio.contains_commit(dest, fixture_repo["seed"])
    assert not gitio.contains_commit(dest, fixture_repo["child"]), (
        "the pre-image clone still holds the commit whose diff is the answer key"
    )
    reachable = gitio._run(dest, ["log", "--pretty=format:%H", "--all"])
    assert fixture_repo["child"].encode() not in reachable


def test_preimage_clone_still_serves_the_pre_image_tree(fixture_repo, tmp_path):
    """Isolation that also broke legitimate reads would be useless."""
    dest = tmp_path / "preimage"
    gitio.make_preimage_clone(fixture_repo["repo"], fixture_repo["parent"], dest)
    tree = gitio.list_tree(dest, fixture_repo["parent"])
    assert set(tree) == PARENT_TREE
    blobs = gitio.read_blobs(dest, [blob for blob, _ in tree.values()])
    assert ALPHA_FIRST in set(blobs.values())


def test_preimage_clone_refuses_an_existing_destination(fixture_repo, tmp_path):
    dest = tmp_path / "already"
    dest.mkdir()
    with pytest.raises(gitio.GitError):
        gitio.make_preimage_clone(fixture_repo["repo"], fixture_repo["parent"], dest)


def test_a_forward_walking_retriever_is_blinded_by_isolation(fixture_repo, tmp_path):
    """The executed attack, run against the defence.

    ``Oracle`` does what the audit's probe did: ask git which files changed
    most recently anywhere in the repository it can see, and return them.
    Against the live repository the newest commit IS the case commit, so it
    names the gold file first.  Against the clone the harness hands it, the
    newest thing it can see is the pre-image, and the answer is gone.
    """

    class Oracle:
        name = "oracle"

        def rank(self, query, universe):
            probe = subprocess.run(
                ["git", "-C", query.repo, "log", "--pretty=format:",
                 "--name-only", "--all"],
                capture_output=True,
                check=False,
            )
            if probe.returncode != 0:
                return []
            known = {c.path for c in universe}
            out: list = []
            for line in probe.stdout.decode("utf-8", "replace").splitlines():
                path = line.strip()
                if path in known and path not in out:
                    out.append(path)
            return out

    universe = harness.build_universe(
        fixture_repo["repo"], _case(fixture_repo), Budget(),
        harness.BlobStore(fixture_repo["repo"], Budget()),
    )

    exposed = Oracle().rank(
        QueryView("c00", "q", "raw", fixture_repo["parent"], str(fixture_repo["repo"])),
        universe,
    )
    assert exposed[:1] == [GOLD], (
        "the attack itself is broken -- it must succeed without isolation "
        "or this test proves nothing"
    )

    isolation = harness.PreimageIsolation(fixture_repo["repo"], root=tmp_path / "iso")
    try:
        blinded = Oracle().rank(
            QueryView(
                "c00", "q", "raw", fixture_repo["parent"],
                isolation.repo_for(fixture_repo["parent"]),
            ),
            universe,
        )
    finally:
        isolation.close()
    assert blinded[:1] == ["notes/changelog.md"], (
        f"isolation did not blind the oracle: it still ranked {blinded[:1]} first"
    )
    assert "pkg/beta.py" not in blinded, (
        "the clone leaked a path that exists only after the pre-image"
    )


def test_isolation_caches_one_clone_per_revision(fixture_repo, tmp_path):
    isolation = harness.PreimageIsolation(fixture_repo["repo"], root=tmp_path / "iso")
    try:
        first = isolation.repo_for(fixture_repo["parent"])
        second = isolation.repo_for(fixture_repo["parent"])
        assert first == second
        assert isolation.built == 1
    finally:
        isolation.close()
