"""G3-MINT-TEXT-01: the ``independent_text_diff`` provenance.

Hermetic — every test builds a throwaway git repository, so these assert
behaviour rather than a measurement and run anywhere. The measured yield on
this repository lives in the packet, stamped with its commit budget.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from daedalus.eval import mint


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "subject"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    return root


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


# --------------------------------------------------------------------------- #
# A2: the provenance and tier a minted text task must carry                   #
# --------------------------------------------------------------------------- #
def test_a_two_file_doc_commit_mints_a_quarantined_text_task(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "seed", {"docs/a.md": "# Alpha\n", "docs/b.md": "# Bravo\n"})
    sha = _commit(repo, "document two things", {
        "docs/a.md": "# Alpha\n\n## Anchor Section\n",
        "docs/b.md": "# Bravo\n\n## Retrieved One\n\n## Retrieved Two\n",
    })

    tasks = mint.mint_text_from_commit(str(repo), sha)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["label_provenance"] == "independent_text_diff"
    assert task["tier"] == "quarantine"
    assert task["confirmations"] == 0
    assert task["text_plane"] == "knowledge"
    assert task["minted_at_sha"] == sha
    # The anchor is the file introducing the FEWEST labels.
    assert task["target"] == "docs/a.md"
    assert task["must_include"] == ["Retrieved One", "Retrieved Two"]


def test_json_top_level_keys_mint_a_data_task(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "seed", {
        "conf/a.json": json.dumps({"keep": 1}),
        "conf/b.json": json.dumps({"keep": 1}),
    })
    sha = _commit(repo, "add config", {
        "conf/a.json": json.dumps({"keep": 1, "anchor_key": 2}),
        "conf/b.json": json.dumps({"keep": 1, "wanted_one": 2, "wanted_two": 3}),
    })

    task = mint.mint_text_from_commit(str(repo), sha)[0]
    assert task["text_plane"] == "data"
    assert task["target"] == "conf/a.json"
    assert task["must_include"] == ["wanted_one", "wanted_two"]


# --------------------------------------------------------------------------- #
# A3: the cross-file rule -- the whole reason the yield is what it is         #
# --------------------------------------------------------------------------- #
def test_a_label_the_anchor_also_introduces_is_never_emitted(tmp_path: Path) -> None:
    """Recalled by construction, so it cannot be gold."""
    repo = _repo(tmp_path)
    _commit(repo, "seed", {"docs/a.md": "# A\n", "docs/b.md": "# B\n"})
    sha = _commit(repo, "same heading in both", {
        "docs/a.md": "# A\n\n## Shared Heading\n",
        "docs/b.md": "# B\n\n## Shared Heading\n\n## Only In B\n",
    })

    task = mint.mint_text_from_commit(str(repo), sha)[0]
    assert "Shared Heading" not in task["must_include"]
    assert task["must_include"] == ["Only In B"]


def test_a_single_file_commit_mints_nothing(tmp_path: Path) -> None:
    """114 of 400 commits on the real repository look like this."""
    repo = _repo(tmp_path)
    _commit(repo, "seed", {"docs/a.md": "# A\n", "src/x.py": "x = 1\n"})
    sha = _commit(repo, "one doc only", {"docs/a.md": "# A\n\n## New\n"})

    assert mint.mint_text_from_commit(str(repo), sha) == []


# --------------------------------------------------------------------------- #
# A4: out of scope is recorded, never silently dropped                        #
# --------------------------------------------------------------------------- #
def test_ignored_dirs_and_fixture_text_are_recorded_not_dropped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "seed", {
        "docs/a.md": "# A\n", "docs/b.md": "# B\n",
        "dist/bundle.md": "# D\n", "pkg/fixtures/toy.md": "# F\n",
    })
    sha = _commit(repo, "touch everything", {
        "docs/a.md": "# A\n\n## Anchor\n",
        "docs/b.md": "# B\n\n## Wanted\n",
        "dist/bundle.md": "# D\n\n## Generated Noise\n",
        "pkg/fixtures/toy.md": "# F\n\n## Fixture Noise\n",
    })

    task = mint.mint_text_from_commit(str(repo), sha)[0]
    assert task["must_include"] == ["Wanted"]
    assert "Generated Noise" not in task["must_include"]
    assert "Fixture Noise" not in task["must_include"]
    assert task["skipped_out_of_scope"] == ["dist/bundle.md", "pkg/fixtures/toy.md"]


def test_the_generated_index_is_out_of_scope(tmp_path: Path) -> None:
    """The prose equivalent of a minified bundle."""
    assert mint._text_in_scope("docs/work-packets/index.json") is False
    assert mint._text_in_scope("docs/work-packets/G1-REAL-01.json") is True


# --------------------------------------------------------------------------- #
# A8: the secret floor applies to text label sources too                      #
# --------------------------------------------------------------------------- #
def test_a_floor_tripping_file_is_excluded_from_anchor_and_labels(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "seed", {
        "docs/a.md": "# A\n", "docs/b.md": "# B\n", "docs/c.md": "# C\n",
    })
    sha = _commit(repo, "one carries a credential", {
        "docs/a.md": "# A\n\n## Anchor\n",
        "docs/b.md": "# B\n\n## Wanted\n",
        "docs/c.md": (
            "# C\n\n## Leaked Section\n\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAx7Vn9Q==\n"
            "-----END RSA PRIVATE KEY-----\n"
        ),
    })

    task = mint.mint_text_from_commit(str(repo), sha)[0]
    assert "Leaked Section" not in task["must_include"]
    assert task["target"] != "docs/c.md"
    assert "docs/c.md" in task["skipped_secret_floor"]


# --------------------------------------------------------------------------- #
# A1: the existing provenance path is untouched                               #
# --------------------------------------------------------------------------- #
def test_the_symbol_path_still_mints_its_own_provenance(tmp_path: Path) -> None:
    """A text commit must not start producing independent_diff, or vice versa."""
    repo = _repo(tmp_path)
    _commit(repo, "seed", {"docs/a.md": "# A\n", "docs/b.md": "# B\n"})
    sha = _commit(repo, "docs only", {
        "docs/a.md": "# A\n\n## Anchor\n", "docs/b.md": "# B\n\n## Wanted\n",
    })

    # The symbol path sees no in-scope code and mints nothing.
    assert mint.mint_from_commit(str(repo), sha) == []
    # The text path mints, and says which provenance it is.
    assert mint.mint_text_from_commit(str(repo), sha)[0][
        "label_provenance"] == "independent_text_diff"


def test_an_unresolvable_ref_returns_empty_never_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "seed", {"docs/a.md": "# A\n"})
    assert mint.mint_text_from_commit(str(repo), "does-not-exist") == []


# --------------------------------------------------------------------------- #
# A5: the real classifier agrees with the minted plane                        #
# --------------------------------------------------------------------------- #
def test_gate3_classifier_assigns_the_minted_planes(tmp_path: Path) -> None:
    from daedalus.eval.gate3 import taskset

    repo = _repo(tmp_path)
    _commit(repo, "seed", {"docs/a.md": "# A\n", "docs/b.md": "# B\n"})
    know_sha = _commit(repo, "docs", {
        "docs/a.md": "# A\n\n## Anchor\n", "docs/b.md": "# B\n\n## Wanted\n",
    })
    know = mint.mint_text_from_commit(str(repo), know_sha)[0]
    assert taskset.classify_task_plane(know) == "knowledge"

    _commit(repo, "seed json", {
        "conf/a.json": json.dumps({"k": 1}), "conf/b.json": json.dumps({"k": 1})})
    data_sha = _commit(repo, "config", {
        "conf/a.json": json.dumps({"k": 1, "anchor": 2}),
        "conf/b.json": json.dumps({"k": 1, "wanted": 2})})
    data = mint.mint_text_from_commit(str(repo), data_sha)[0]
    assert taskset.classify_task_plane(data) == "data"
