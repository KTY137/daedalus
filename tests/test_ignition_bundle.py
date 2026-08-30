# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The Gate-1 evaluator bundle: what judged, named by its bytes.

Two Codex reviews of the ignition slice (2026-08-23) ended INCONCLUSIVE for the
same reason: the receipt could say "the criterion is outside the candidate's
write scope" and "the two runs agree" while the thing doing the judging was
quietly replaced. These tests are the measurements that make a replacement
visible.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.ignition import bundle as ignition_bundle
from daedalus.ignition import checks as ignition_checks
from daedalus.ignition import gate1

ROOT = Path(__file__).resolve().parents[1]


def _bundle(root: Path = ROOT, **kw):
    args = dict(
        criterion_path=ignition_checks.CONFORMANCE_TEST_PATH,
        criterion_source=ignition_checks.CONFORMANCE_TEST_SOURCE,
        node_ids={
            "code-type": ignition_checks.CODE_TYPE_NODE_IDS,
            "data-knowledge": ignition_checks.DATA_KNOWLEDGE_NODE_IDS,
        },
        # MUST match what daedalus.ignition.gate1.run_gate1_ignition actually
        # passes, or this helper computes a DIFFERENT bundle than the one that
        # ran -- the environment fingerprint's conftest.py discovery path is
        # rooted here, not at ``root``. Overridable via **kw for the
        # throwaway-repo tests below, which do not exercise this field.
        fixture_root=gate1.DEFAULT_FIXTURE,
    )
    args.update(kw)
    return ignition_bundle.evaluator_bundle(root, **args)


# --------------------------------------------------------------------------- #
# identity                                                                     #
# --------------------------------------------------------------------------- #
def test_the_bundle_names_the_criterion_the_nodes_the_evaluators_and_the_toolchain():
    body = _bundle()
    assert body["schema"] == ignition_bundle.SCHEMA
    assert body["criterion"]["path"] == ignition_checks.CONFORMANCE_TEST_PATH
    assert body["criterion"]["bytes"] == len(ignition_checks.CONFORMANCE_TEST_SOURCE.encode("utf-8"))
    assert body["criterion"]["canonical_sha256"] == ignition_checks.CONFORMANCE_TEST_SHA256
    assert body["nodes"]["code-type"] == list(ignition_checks.CODE_TYPE_NODE_IDS)
    assert body["nodes"]["data-knowledge"] == list(ignition_checks.DATA_KNOWLEDGE_NODE_IDS)
    assert set(body["evaluators"]) == set(ignition_bundle.EVALUATOR_MODULES)
    assert body["toolchain"]["python"] == sys.version.split()[0]
    assert len(body["digest"]) == 64


def test_the_digest_is_a_function_of_content_and_not_of_the_path(tmp_path):
    """Codex round 3 called the first version of this test weak, and it was: it
    called one function twice on one tree, which proves determinism and nothing
    about content. Two SEPARATE trees with identical content must agree, and a
    tree whose content differs by one byte must not."""

    import subprocess as sp

    def repo_with(name: str, text: str) -> Path:
        # named explicitly: deriving the directory from the content collided for
        # the two trees this test needs to hold IDENTICAL content
        repo = tmp_path / name
        repo.mkdir()
        sp.run(["git", "-C", str(repo), "init", "-q"], check=True)
        sp.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
        sp.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "judge.py").write_text(text, encoding="utf-8")
        sp.run(["git", "-C", str(repo), "add", "judge.py"], check=True)
        sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "j"], check=True)
        return repo

    same_a = _bundle(root=repo_with("a", "def verdict():\n    return True\n"), modules=("judge.py",))
    same_b = _bundle(root=repo_with("b", "def verdict():\n    return True\n"), modules=("judge.py",))
    other = _bundle(root=repo_with("c", "def verdict():\n    return False\n"), modules=("judge.py",))
    assert same_a["digest"] == same_b["digest"], "identical content in two trees must agree"
    assert same_a["digest"] != other["digest"]


def test_a_changed_criterion_changes_the_digest():
    before = _bundle()["digest"]
    after = _bundle(criterion_source=ignition_checks.CONFORMANCE_TEST_SOURCE + "\n# tweak\n")["digest"]
    assert before != after


def test_a_changed_node_selection_changes_the_digest():
    before = _bundle()["digest"]
    after = _bundle(node_ids={"code-type": ignition_checks.CODE_TYPE_NODE_IDS,
                              "data-knowledge": ignition_checks.DATA_KNOWLEDGE_NODE_IDS[:1]})["digest"]
    assert before != after


def test_a_changed_evaluator_changes_the_digest(tmp_path):
    """The point of the whole module: replacing a judge is visible."""

    probe = tmp_path / "probe.py"
    probe.write_text("x = 1\n", encoding="utf-8")
    before = _bundle(root=tmp_path, modules=(probe.name,))["digest"]
    probe.write_text("x = 2\n", encoding="utf-8")
    after = _bundle(root=tmp_path, modules=(probe.name,))["digest"]
    assert before != after


def test_the_digest_does_not_move_with_line_endings(tmp_path):
    """Checkout stability, measured. The first version hashed raw bytes and
    reported every evaluator as uncommitted on a clean Windows checkout, because
    autocrlf gives the working file CRLF while the blob is LF. git's own content
    digest is what makes the bundle identity the same on any machine."""

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    module = repo / "judge.py"
    module.write_bytes(b"def verdict():\n    return True\n")
    subprocess.run(["git", "-C", str(repo), "add", "judge.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "j"], check=True)
    lf = _bundle(root=repo, modules=("judge.py",))
    module.write_bytes(b"def verdict():\r\n    return True\r\n")  # the same content, CRLF
    crlf = _bundle(root=repo, modules=("judge.py",))
    assert lf["digest"] == crlf["digest"]
    assert lf["evaluators"]["judge.py"]["running_bytes_sha256"] != crlf["evaluators"]["judge.py"]["running_bytes_sha256"]
    assert crlf["evaluators"]["judge.py"]["platform_dependent"] is True


def test_an_uncommitted_evaluator_is_named_but_not_refused(tmp_path):
    """A working tree is where development happens; blocking it would make the
    slice unrunnable during the work it exists to serve. Being able to READ the
    receipt as pinned when it is not is the thing that must be impossible."""

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    module = repo / "judge.py"
    module.write_text("def verdict():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "judge.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "j"], check=True)

    clean = _bundle(root=repo, modules=("judge.py",))
    assert clean["fully_committed"] is True
    assert clean["evaluators"]["judge.py"]["uncommitted"] is False
    assert ignition_bundle.bundle_blockers(clean) == []

    module.write_text("def verdict():\n    return False\n", encoding="utf-8")
    dirty = _bundle(root=repo, modules=("judge.py",))
    assert dirty["fully_committed"] is False
    assert dirty["evaluators"]["judge.py"]["uncommitted"] is True
    assert ignition_bundle.bundle_blockers(dirty) == []   # named, not refused
    assert dirty["digest"] != clean["digest"]


def test_an_unreadable_evaluator_is_refused(tmp_path):
    """A verdict produced by code the bundle cannot name is not a pinned one."""

    body = _bundle(root=tmp_path, modules=("does_not_exist.py",))
    assert body["evaluators"]["does_not_exist.py"]["unreadable"] is True
    assert body["fully_committed"] is False
    blockers = ignition_bundle.bundle_blockers(body)
    assert len(blockers) == 1 and "does_not_exist.py" in blockers[0]


def test_the_bundle_describes_the_judge_and_never_the_judged():
    """Mixing the candidate into the bundle would give every candidate its own
    bundle and make the comparison meaningless.

    Asserted on the SHAPE, not on substrings: the first version forbade the word
    "attempt" anywhere in the serialised bundle and then tripped over
    ``daedalus/spine/attempt.py``, which the closure names legitimately -- a
    module path is not a run. What must be absent is any key that identifies a
    RUN, and any path that is a run artefact.
    """

    body = _bundle()
    assert set(body) == {
        "schema", "criterion", "nodes", "evaluators", "closure", "toolchain",
        "environment_fingerprint", "digest", "fully_committed",
    }
    run_shaped = {"mission_id", "attempt_id", "attempt_ids", "candidate_revision",
                  "base_revision", "fixture_tree_sha256", "work_item_ids", "collected_at"}
    assert not (run_shaped & set(body))
    for rel in list(body["evaluators"]) + list(body["closure"]["modules"]):
        assert (ROOT / rel).is_file(), rel
        assert not rel.startswith("runs/"), rel


# --------------------------------------------------------------------------- #
# the transitive closure (Codex round 3)                                       #
# --------------------------------------------------------------------------- #
def test_the_closure_reaches_the_module_that_actually_decides():
    """The roots are wrappers. ``reference_compiler`` delegates the cross-plane
    verdict to ``_reference_claims.verify_claims`` -- the module Codex named as
    escaping the digest -- and reaches it through a RELATIVE import, which the
    first closure implementation resolved with the sign the wrong way round and
    silently dropped. This is the test that would have caught that."""

    closure = ignition_bundle.import_closure(ROOT, ignition_bundle.EVALUATOR_MODULES)
    assert "daedalus/twin/_reference_claims.py" in closure
    assert "daedalus/twin/_reference_inventory.py" in closure
    assert "daedalus/spine/receipts.py" in closure
    assert set(ignition_bundle.EVALUATOR_MODULES) <= set(closure)
    # and nothing outside the repository sneaks in
    for rel in closure:
        assert (ROOT / rel).is_file(), rel
        assert not rel.startswith(".."), rel


def test_a_change_below_the_roots_moves_the_digest(tmp_path):
    """A judge is its transitive code. Editing a module the roots merely IMPORT
    must move the identity, or the bundle names less than it looks."""

    import subprocess as sp

    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    sp.run(["git", "-C", str(repo), "init", "-q"], check=True)
    sp.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    sp.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "deep.py").write_text("LIMIT = 1\n", encoding="utf-8")
    (repo / "pkg" / "root.py").write_text("from .deep import LIMIT\n", encoding="utf-8")
    sp.run(["git", "-C", str(repo), "add", "-A"], check=True)
    sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "p"], check=True)

    before = _bundle(root=repo, modules=("pkg/root.py",))
    assert "pkg/deep.py" in before["closure"]["modules"], "the relative import must be followed"
    (repo / "pkg" / "deep.py").write_text("LIMIT = 999\n", encoding="utf-8")
    after = _bundle(root=repo, modules=("pkg/root.py",))
    assert after["evaluators"]["pkg/root.py"]["blob_sha1"] == before["evaluators"]["pkg/root.py"]["blob_sha1"]
    assert after["digest"] != before["digest"], "a change the roots only import must still move it"


def test_an_untracked_evaluator_is_not_reported_as_committed(tmp_path):
    """Outside git, in an unborn repository, or for an untracked evaluator,
    `rev-parse HEAD:path` fails while `hash-object` still answers -- and the
    first version read that as committed (Codex round 3)."""

    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    sp.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "judge.py").write_text("x = 1\n", encoding="utf-8")   # never committed
    body = _bundle(root=repo, modules=("judge.py",))
    assert body["evaluators"]["judge.py"]["committed_blob_sha1"] is None
    assert body["evaluators"]["judge.py"]["uncommitted"] is True
    assert body["fully_committed"] is False


# --------------------------------------------------------------------------- #
# the environment fingerprint (the first named-open gap)                       #
# --------------------------------------------------------------------------- #
# What the bundle pinned before this: the criterion, the node selection, and
# the evaluator code by git blob sha. What it could NOT yet say: whether the
# ENVIRONMENT that code ran in -- installed pytest plugins, PYTHONPATH, which
# conftest.py files pytest actually collected, the OS/platform -- was the same
# between two runs. A conftest.py in particular is never reached by
# import_closure: pytest loads it by directory position, not by an import
# statement any evaluator module writes, so it was invisible by construction.
def test_pytest_plugins_are_measured_on_this_host():
    """Not mocked: the real query, on the real host, must come back as a
    measurement (a list, however short) rather than an error -- the floor
    this repo's own dependencies guarantee (anyio, hypothesis and
    pytest-asyncio are all installed, MEASURED 2026-08-24)."""

    plugins, error = ignition_bundle._pytest_plugins()
    assert error is None
    assert plugins is not None
    assert len(plugins) >= 1
    assert all({"name", "version"} <= set(row) for row in plugins)


def test_an_unmeasurable_plugin_query_is_named_and_reported_not_measured(monkeypatch):
    """The instrument-honesty rule this project has paid for four times over:
    a failed measurement must not read as an empty, clean one."""

    monkeypatch.setattr(
        ignition_bundle, "_pytest_plugins", lambda: (None, "boom: metadata scan failed")
    )
    body = _bundle()
    fingerprint = body["environment_fingerprint"]
    assert fingerprint["pytest_plugins"] is None
    assert fingerprint["pytest_plugins_measured"] is False
    assert fingerprint["pytest_plugins_error"] == "boom: metadata scan failed"
    blockers = ignition_bundle.bundle_blockers(body)
    assert len(blockers) == 1
    assert "could not measure installed pytest plugins" in blockers[0]


def test_a_different_pytest_plugin_set_changes_the_digest(monkeypatch):
    """Simulates a plugin VERSION changing between two runs (2026-08-23's ask,
    named explicitly): the digest must move, the same way a changed evaluator
    module does, or an upgraded plugin between two runs could silently change
    what ran without the bundle saying so."""

    responses = iter([
        ([{"name": "pytest-cov", "version": "4.1.0"}], None),
        ([{"name": "pytest-cov", "version": "5.0.0"}], None),
    ])
    monkeypatch.setattr(ignition_bundle, "_pytest_plugins", lambda: next(responses))
    before = _bundle()["digest"]
    after = _bundle()["digest"]
    assert before != after


def test_an_extra_conftest_py_changes_the_digest(tmp_path):
    """A conftest.py is never reached by import_closure -- pytest loads it by
    directory position, not by any import statement an evaluator writes -- so
    this is the part of the environment fingerprint that makes one visible.
    Mirrors the commit that landed the closure: 'appending one comment line to
    a module no root names directly moves the bundle digest'; this is the same
    claim for a file no root ever imports at all."""

    fixture = tmp_path / "fixture"
    (fixture / "tests").mkdir(parents=True)
    before = _bundle(fixture_root=fixture)["digest"]
    (fixture / "tests" / "conftest.py").write_text("collect_ignore = []\n", encoding="utf-8")
    after = _bundle(fixture_root=fixture)["digest"]
    assert before != after


def test_the_conftest_chain_tells_a_missing_directory_from_a_checked_one(tmp_path):
    """A directory that does not exist is not the same fact as a directory
    that was checked and had no conftest.py -- collapsing the two is the exact
    shape of defect this project has hit before (an absence read as a clean
    measurement instead of a limit)."""

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    chain = ignition_bundle._conftest_chain(fixture, "tests/test_event_field.py")
    candidates = {row["dir"]: row for row in chain["candidates"]}
    assert candidates["."]["exists"] is True
    assert candidates["."]["conftest_sha256"] is None
    assert candidates["tests"]["exists"] is False
    assert candidates["tests"]["conftest_sha256"] is None


def test_a_different_platform_string_changes_the_digest(monkeypatch):
    """OS/platform: the exact axis the CRLF bug (2026-08-23) moved along,
    measured here rather than assumed stable."""

    monkeypatch.setattr(ignition_bundle.platform, "platform", lambda: "Linux-6.1.0-x86_64")
    before = _bundle()["digest"]
    monkeypatch.setattr(ignition_bundle.platform, "platform", lambda: "Windows-10-10.0.26200")
    after = _bundle()["digest"]
    assert before != after


def test_a_changed_pythonpath_changes_the_digest(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    before = _bundle()["digest"]
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    after = _bundle()["digest"]
    assert before != after


def test_environment_fingerprint_is_stable_across_two_calls_in_one_process():
    """The negative control for every test above: with nothing simulated, the
    fingerprint -- and therefore the digest -- must NOT move on its own. Two
    runs with nothing changed are the baseline replay claim depends on."""

    first = _bundle()
    second = _bundle()
    assert first["environment_fingerprint"]["digest"] == second["environment_fingerprint"]["digest"]
    assert first["digest"] == second["digest"]


# --------------------------------------------------------------------------- #
# the retrievable artifact (the third named-open gap)                          #
# --------------------------------------------------------------------------- #
# Until this, the bundle's identity was computed and asserted at run time; no
# artifact a reader could FETCH and HOLD was the bundle, as opposed to
# re-deriving it against a live tree. These tests prove the artifact is
# self-contained: given only the file (no git call, no live tree beyond it),
# recomputing the digest from its own content reproduces the digest named in
# both the filename and the receipt.
def test_write_bundle_artifact_names_itself_by_digest(tmp_path):
    body = _bundle()
    path = ignition_bundle.write_bundle_artifact(body, tmp_path)
    assert path.name == f"evaluator-bundle-{body['digest']}.json"
    assert path.is_file()


def test_write_bundle_artifact_refuses_a_digestless_bundle(tmp_path):
    with pytest.raises(ValueError):
        ignition_bundle.write_bundle_artifact({"schema": "x"}, tmp_path)


def test_the_artifact_alone_reproduces_its_own_digest(tmp_path):
    """The central claim: fetch this file, and ONLY this file, and recompute
    the digest the receipt names -- no live tree, no git call."""

    original = _bundle()
    path = ignition_bundle.write_bundle_artifact(original, tmp_path)

    retrieved = ignition_bundle.load_bundle_artifact(path)
    assert retrieved == original, "the artifact must be the bundle, not a projection of it"
    recomputed = ignition_bundle.bundle_digest_from_body(retrieved)
    assert recomputed == original["digest"]
    assert recomputed == retrieved["digest"]


def test_a_bundle_that_differs_only_in_the_environment_still_round_trips(monkeypatch, tmp_path):
    """Not just the happy path where nothing changed: an artifact minted under
    a DIFFERENT environment must still verify against itself."""

    monkeypatch.setattr(
        ignition_bundle, "_pytest_plugins",
        lambda: ([{"name": "pytest-xdist", "version": "3.6.1"}], None),
    )
    body = _bundle()
    path = ignition_bundle.write_bundle_artifact(body, tmp_path)
    retrieved = ignition_bundle.load_bundle_artifact(path)
    assert ignition_bundle.bundle_digest_from_body(retrieved) == body["digest"]


# --------------------------------------------------------------------------- #
# the slice binds it                                                           #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    receipts = tmp_path_factory.mktemp("bundle-replay")
    first = gate1.run_gate1_ignition(receipt_root=receipts, collected_at="2026-08-22T00:00:00Z")
    second = gate1.run_gate1_ignition(receipt_root=receipts, collected_at="2026-08-22T00:00:00Z")
    return first, second


def test_the_receipt_carries_the_bundle_that_judged(two_runs):
    _, second = two_runs
    body = second.receipt["evaluator_bundle"]
    assert body["schema"] == ignition_bundle.SCHEMA
    assert body["digest"] == _bundle()["digest"], "the receipt must name the bundle that ran"
    assert set(body["evaluators"]) == set(ignition_bundle.EVALUATOR_MODULES)


def test_the_receipt_names_a_retrievable_bundle_artifact(two_runs):
    """The third named-open gap, bound to the real slice: the receipt does not
    just carry the bundle inline, it also names a FILE a reader can fetch on
    its own and verify without the receipt, without git, and without a live
    tree."""

    _, second = two_runs
    named = second.receipt["evaluator_bundle_artifact"]
    assert named is not None
    assert named["digest"] == second.receipt["evaluator_bundle"]["digest"]

    artifact_path = second.receipt_path.parent / named["path"]
    assert artifact_path.is_file()

    retrieved = ignition_bundle.load_bundle_artifact(artifact_path)
    assert retrieved == second.receipt["evaluator_bundle"]
    assert ignition_bundle.bundle_digest_from_body(retrieved) == named["digest"]


def test_two_runs_are_a_replay_only_under_one_bundle(two_runs):
    first, second = two_runs
    assert second.receipt["replay"]["same_evaluator_bundle"] is True
    assert second.receipt["replay"]["replay_demonstrated"] is True
    assert second.receipt["blockers"] == []

    # and a run whose predecessor used another bundle is refused by name
    blockers = gate1._replay_blockers({
        "is_replay": True, "same_fixture": True, "same_evaluator_bundle": False,
        "previous_evaluator_bundle_digest": "c" * 64,
        "criterion_changed_since_previous": False,
        **{name: True for name in gate1.REPLAY_REQUIRED_STABLE},
    })
    assert len(blockers) == 1 and "different evaluator bundle" in blockers[0]
    assert "cccccccccccc" in blockers[0]


def test_a_predecessor_without_a_bundle_is_refused_and_told_apart(two_runs, tmp_path):
    """A receipt written before the bundle existed records none. That is not a
    replay under one bundle -- and it is not "a different bundle" either, which
    would send a reader looking for a change nobody made.

    This exercises the product's own path (write_receipt reading a predecessor
    off disk), not a re-implementation of the derivation in the test: the first
    version of this test asserted `bool(a and b and None) is False`, which tests
    Python, and carried an `== [] or True` that could never fail.
    """

    import json as _json

    receipts = tmp_path / "no-bundle"
    first = gate1.run_gate1_ignition(receipt_root=receipts, collected_at="2026-08-22T00:00:00Z")
    assert first.receipt["evaluator_bundle"]["digest"]
    path = receipts / "mission-gate1-voltage-ignition" / "receipt.json"
    body = _json.loads(path.read_text(encoding="utf-8"))
    del body["evaluator_bundle"]
    path.write_text(_json.dumps(body, indent=2, sort_keys=True) + chr(10), encoding="utf-8")

    second = gate1.run_gate1_ignition(receipt_root=receipts, collected_at="2026-08-22T00:00:00Z")
    replay = second.receipt["replay"]
    assert replay["same_evaluator_bundle"] is False
    assert replay["previous_evaluator_bundle_digest"] is None
    assert replay["replay_demonstrated"] is False
    assert len(second.blockers) == 1
    assert "records no evaluator bundle" in second.blockers[0]
    assert "different evaluator bundle" not in second.blockers[0]
    # and the same run against a predecessor that HAS a different digest says so
    other = gate1._replay_blockers({
        "is_replay": True, "same_fixture": True, "same_evaluator_bundle": False,
        "previous_evaluator_bundle_digest": "d" * 64,
        "criterion_changed_since_previous": False,
        **{name: True for name in gate1.REPLAY_REQUIRED_STABLE},
    })
    assert "different evaluator bundle" in other[0] and "dddddddddddd" in other[0]


# --------------------------------------------------------------------------- #
# a replay is two COMPLETE runs under one bundle (Codex round 3)                #
# --------------------------------------------------------------------------- #
def test_a_replay_needs_two_complete_runs(tmp_path):
    """A predecessor that ended in blockers, or produced no packet, is not a run
    this one can claim to have reproduced. The comparison used to require
    neither."""

    import json as _json

    receipts = tmp_path / "incomplete"
    first = gate1.run_gate1_ignition(receipt_root=receipts, collected_at="2026-08-22T00:00:00Z")
    path = receipts / "mission-gate1-voltage-ignition" / "receipt.json"
    body = _json.loads(path.read_text(encoding="utf-8"))
    body["blockers"] = ["a blocker the previous run ended with"]
    path.write_text(_json.dumps(body, indent=2, sort_keys=True) + chr(10), encoding="utf-8")

    second = gate1.run_gate1_ignition(receipt_root=receipts, collected_at="2026-08-22T00:00:00Z")
    replay = second.receipt["replay"]
    assert replay["same_evaluator_bundle"] is True      # the bundle did not move
    assert replay["previous_run_complete"] is False
    assert replay["replay_demonstrated"] is False       # ... and the claim does not survive it


def test_two_receipts_without_a_bundle_do_not_read_as_the_same_bundle(tmp_path):
    """None == None used to read as "same bundle", so two refused receipts could
    claim a replay between them."""

    import json as _json

    receipts = tmp_path / "bundleless"
    gate1.run_gate1_ignition(receipt_root=receipts, collected_at="2026-08-22T00:00:00Z")
    path = receipts / "mission-gate1-voltage-ignition" / "receipt.json"
    body = _json.loads(path.read_text(encoding="utf-8"))
    del body["evaluator_bundle"]
    path.write_text(_json.dumps(body, indent=2, sort_keys=True) + chr(10), encoding="utf-8")

    # a body that also records no bundle, compared against it
    from daedalus.ignition.gate1 import write_receipt

    stripped = dict(body)
    stripped["collected_at"] = "2026-08-22T00:00:01Z"
    _path, written = write_receipt(stripped, receipts)
    assert written["replay"]["same_evaluator_bundle"] is False
    assert written["replay"]["replay_demonstrated"] is False
    assert any("records no evaluator bundle" in b for b in written["blockers"])
