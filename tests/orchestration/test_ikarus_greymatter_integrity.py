"""KITCHEN-02: retain source identity and keep generated evidence out of retrieval."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus.kitchen import greymatter as gm


def corpus(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.py").write_text("def invoice_total():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("# README\nUse `invoice_total` for invoice totals.\n", encoding="utf-8")
    return root


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], check=True,
                            capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip()


def test_repeated_definitions_and_overloads_retain_distinct_cards(tmp_path: Path) -> None:
    root = corpus(tmp_path / "repo")
    (root / "main.py").write_text(
        "def invoice_total(x: int):\n    return 1\n\ndef invoice_total(x: str):\n    return 2\n",
        encoding="utf-8")
    (root / "module.ts").write_text(
        "function invoice_total(x: number): number;\nfunction invoice_total(x: string): number;\n",
        encoding="utf-8")
    (root / "data.sql").write_text("create table invoice(id int);\ncreate table invoice(id text);\n", encoding="utf-8")
    grey = gm.GreyMatter(tmp_path / "gm.db")
    try:
        result = grey.ingest_repo(root)
        cards = grey.db.execute("SELECT card_id, locator FROM cards").fetchall()
        assert result["cards"] == len(cards) == len({c[0] for c in cards})
        assert grey.db.execute("SELECT COUNT(*) FROM cards WHERE name='invoice_total'").fetchone()[0] == 4
        assert grey.db.execute("SELECT COUNT(*) FROM cards WHERE name='invoice'").fetchone()[0] == 2
        assert grey.stats()["cards"] == sum(grey.stats()["planes"].values())
        assert grey.stats()["integrity"]["invalid_verified_bindings"] == 0
    finally:
        grey.close()


def test_truncated_document_never_creates_dangling_verified_bindings(tmp_path: Path) -> None:
    root = corpus(tmp_path / "repo")
    (root / "README.md").write_text("".join(f"# Section {n}\nUse `invoice_total`.\n" for n in range(405)), encoding="utf-8")
    grey = gm.GreyMatter(tmp_path / "gm.db")
    try:
        grey.ingest_repo(root)
        assert grey.plane_counts()["knowledge"] == 400
        assert grey.db.execute("SELECT COUNT(*) FROM edges e LEFT JOIN cards c ON e.source=c.card_id WHERE c.card_id IS NULL").fetchone()[0] == 0
        assert grey.stats()["verified_bindings"] > 0
        assert grey.stats()["integrity"]["invalid_verified_bindings"] == 0
    finally:
        grey.close()


def test_default_motifs_exclude_candidates_even_when_they_match_best(tmp_path: Path) -> None:
    grey = gm.GreyMatter(tmp_path / "gm.db")
    try:
        grey.ingest_repo(corpus(tmp_path / "corpus"), name="external-example")
        candidate = grey.ingest_repo(corpus(tmp_path / "candidate"), name="candidate:generated-answer",
                                     provenance={"candidate": True, "order_id": "order-example"})
        assert all(hit["repo"] == "external-example" for hit in grey.search("invoice_total", k=100))
        assert "generated-answer" not in grey.motif_context("invoice_total", k=100)
        assert grey.search("invoice_total", repo_id=candidate["repo_id"]) == []
        assert grey.search("invoice_total", repo_id=candidate["repo_id"], include_candidates=True)
        with grey.db:
            grey.db.execute("UPDATE repos SET provenance='{}' WHERE repo_id=?", (candidate["repo_id"],))
        assert grey.search("invoice_total", repo_id=candidate["repo_id"]) == []  # legacy name boundary
    finally:
        grey.close()


def test_stats_report_stored_rows_and_retained_invalid_evidence(tmp_path: Path) -> None:
    grey = gm.GreyMatter(tmp_path / "gm.db")
    try:
        result = grey.ingest_repo(corpus(tmp_path / "repo"))
        before = grey.stats()
        target = grey.db.execute("SELECT card_id FROM cards WHERE plane='code' LIMIT 1").fetchone()[0]
        with grey.db:
            grey.db.execute("UPDATE repos SET card_count=card_count+500, edge_count=edge_count+100")
            grey.db.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?,?)",
                            (result["repo_id"], "missing-card", target, "documents", 1.0, 1, "legacy invalid evidence"))
            grey.db.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?)",
                            (result["repo_id"], "missing-card", "symbol:invoice_total", "mentions", "README.md:999", "knowledge", "code"))
        measured = grey.stats()
        assert measured["cards"] == before["cards"]
        assert measured["edges"] == before["edges"] + 1
        assert measured["verified_bindings"] == before["verified_bindings"]
        assert measured["integrity"] == {"reported_cards": before["cards"] + 500, "invalid_verified_bindings": 1}
        assert grey.db.execute("SELECT COUNT(*) FROM proposals WHERE source='missing-card'").fetchone()[0] == 1
        grey.propose_bindings(result["repo_id"])
        assert grey.db.execute("SELECT COUNT(*) FROM proposals WHERE source='missing-card'").fetchone()[0] == 0
    finally:
        grey.close()


def test_candidate_source_digest_covers_unsupported_bytes_and_refuses_mismatch(tmp_path: Path) -> None:
    root = corpus(tmp_path / "candidate")
    (root / "asset.bin").write_bytes(b"original")
    digest, _count = gm.source_tree_digest(root)
    grey = gm.GreyMatter(tmp_path / "gm.db")
    try:
        result = grey.ingest_repo(root, source_digest=digest,
                                 provenance={"candidate": True, "revision": "forged", "root": "forged"})
        assert result["revision"] == f"sha256:{digest}"
        row = grey.repos()[0]
        assert row["provenance"]["source_tree_sha256"] == digest
        assert row["provenance"]["revision"] == result["revision"]
        assert row["provenance"]["root"] == str(root.resolve())
        assert row["provenance"]["projection_scope"]["complete_source_tree"] is False
        (root / "asset.bin").write_bytes(b"changed")
        with pytest.raises(ValueError, match="does not match"):
            grey.ingest_repo(root, source_digest=digest)
        assert grey.stats()["repos"] == 1
    finally:
        grey.close()


def test_worktree_revision_binds_dirty_observed_bytes(tmp_path: Path) -> None:
    root = corpus(tmp_path / "repo")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "-qm", "base")
    worktree = tmp_path / "worktree"
    git(root, "worktree", "add", "--detach", str(worktree), "HEAD")
    grey = gm.GreyMatter(tmp_path / "gm.db")
    try:
        clean = grey.ingest_repo(worktree)
        clean_row = grey.repos()[0]
        assert clean_row["provenance"]["git_head"] == git(root, "rev-parse", "HEAD")
        assert clean_row["provenance"]["git_dirty"] is False
        (worktree / "main.py").write_text("def invoice_total():\n    return 12\n", encoding="utf-8")
        dirty = grey.ingest_repo(worktree)
        assert dirty["repo_id"] != clean["repo_id"]
        assert dirty["revision"] != clean["revision"]
        assert grey.repos()[0]["provenance"]["git_dirty"] is True
        assert clean["revision"] != git(root, "rev-parse", "HEAD")
        assert grey.stats()["repos"] == 2  # prior revision remains inspectable
    finally:
        grey.close()


@pytest.mark.parametrize("fault", ["duplicate", "dangling", "changed-source"])
def test_invalid_extraction_preserves_previous_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    root = corpus(tmp_path / "repo")
    grey = gm.GreyMatter(tmp_path / "gm.db")
    try:
        before = grey.ingest_repo(root)
        original = gm.extract_cards

        def altered(*args, **kwargs):
            cards, edges = original(*args, **kwargs)
            if fault == "duplicate":
                cards.append(cards[0])
            elif fault == "dangling":
                edges.append(gm.Edge("absent", cards[0].card_id, "documents", "invalid"))
            else:
                (root / "main.py").write_text("CHANGED = True\n", encoding="utf-8")
            return cards, edges

        monkeypatch.setattr(gm, "extract_cards", altered)
        with pytest.raises(ValueError):
            grey.ingest_repo(root)
        assert grey.stats()["repos"] == 1
        assert grey.stats()["cards"] == before["cards"]
    finally:
        grey.close()


def test_source_digest_uses_posix_path_order_and_refuses_links(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("Z.txt", "a.txt", "B.txt"):
        (root / name).write_bytes(name.encode("ascii"))
    expected = hashlib.sha256()
    for path in sorted(root.iterdir(), key=lambda p: p.relative_to(root).as_posix()):
        expected.update(path.name.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    assert gm.source_tree_digest(root) == (expected.hexdigest(), 3)
    try:
        (root / "link.txt").symlink_to(root / "Z.txt")
    except OSError:
        pytest.skip("host cannot create symlinks")
    with pytest.raises(ValueError, match="symlink or junction"):
        gm.source_tree_digest(root)
