"""The Ikarus kitchen: Waiter, Chef, Grey Matter (G1-IKARUS-KITCHEN-01).

Everything here runs with an injected builder, never a real CLI: the
contracts under test are order recognition, corpus ingestion, retrieval,
the toolchain verdict, candidate identity, the leakage boundary and the
chat door. Live Claude/Codex runs are owner-operated evidence, not unit tests.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus.kitchen import orders, toolchain
from daedalus.orchestration.ikarus.kitchen.builders import BuilderReport, BuilderUnavailable
from daedalus.orchestration.ikarus.kitchen.chef import PROTECTED_PREFIXES, Chef, Kitchen, tree_digest
from daedalus.orchestration.ikarus.kitchen.greymatter import GreyMatter, cosine, embed, extract_cards
from daedalus.orchestration.ikarus.kitchen.orders import parse_order


# --------------------------------------------------------------------------- #
# Orders                                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, kind", [
    ("bau mir nh app die meine todos verwaltet", orders.KIND_BUILD),
    ("Bau mir eine App für Rezepte", orders.KIND_BUILD),
    ("build me a small cli tool that renames files", orders.KIND_BUILD),
    ("erstelle mir bitte ein dashboard für meine ausgaben", orders.KIND_BUILD),
    ("ich brauche eine neue App für meine Rezepte", orders.KIND_BUILD),
    ("ok ikarus, build me a small game", orders.KIND_BUILD),
    ("improve diese App: dark mode fehlt", orders.KIND_IMPROVE),
    ("verbessere die Fehlermeldungen in diesem Projekt", orders.KIND_IMPROVE),
    ("verbessere dich selbst: der Chat ist zu langsam", orders.KIND_SELF),
    ("improve yourself, Ikarus", orders.KIND_SELF),
    ("füttere Ariadne mit https://github.com/pallets/flask", orders.KIND_FEED),
    ("feed ariadne with repos https://github.com/a/b and https://github.com/c/d", orders.KIND_FEED),
    ("Küche Status", orders.KIND_STATUS),
    ("/kitchen", orders.KIND_STATUS),
    ("kitchen status please", orders.KIND_STATUS),
])
def test_orders_are_recognised(text: str, kind: str) -> None:
    order = parse_order(text)
    assert order is not None, text
    assert order.kind == kind


@pytest.mark.parametrize("text", [
    "wie geht es dir?",
    "was ist ein monad",
    "erklär mir den unterschied zwischen list und tuple",
    "/computer run lies die README",
    "hello",
    "kannst du mir sagen wie spät es ist",
    # component work stays with the confirm-gated computer task (G1-IKARUS-46)
    "improve the parser",
    "verbessere Daedalus",
    "erweitere den Parser",
    "build a login page",
    "Mach den Parser robuster",
    "entwickle ein CLI-Tool",
    "programmiere einen Parser",
    "korrigiere die Doku",
])
def test_ordinary_chat_is_not_an_order(text: str) -> None:
    assert parse_order(text) is None


def test_feed_order_extracts_urls_and_existing_paths(tmp_path: Path) -> None:
    order = parse_order(f"füttere ariadne mit https://github.com/x/y.git und {tmp_path}")
    assert order is not None and order.kind == orders.KIND_FEED
    assert "https://github.com/x/y.git" in order.sources
    assert str(tmp_path) in order.sources


def test_order_identity_is_content_addressed() -> None:
    a = parse_order("bau mir eine app für notizen")
    b = parse_order("bau mir eine app für notizen")
    c = parse_order("bau mir eine app für rezepte")
    assert a is not None and b is not None and c is not None
    assert a.order_id == b.order_id != c.order_id
    assert a.stack is None
    assert parse_order("bau mir eine react app").stack == "react"


# --------------------------------------------------------------------------- #
# Grey Matter                                                                  #
# --------------------------------------------------------------------------- #
def _corpus(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "models.py").write_text(
        '"""Domain models."""\nfrom dataclasses import dataclass\n\n@dataclass\nclass Invoice:\n    """An invoice."""\n'
        '    number: str\n    total: float\n\n\ndef total_of(invoice: Invoice) -> float:\n    """Sum an invoice."""\n'
        '    return invoice.total\n', encoding="utf-8")
    (root / "schema.sql").write_text("CREATE TABLE invoice (\n number TEXT,\n total REAL\n);\n", encoding="utf-8")
    (root / "data.csv").write_text("number,total\nA1,10\n", encoding="utf-8")
    (root / "README.md").write_text("# Billing\n\nThe `Invoice` model is summed by `total_of` in [models](pkg/models.py).\n\n"
                                    "## Storage\n\nRows live in the invoice table.\n", encoding="utf-8")
    (root / "web.ts").write_text("export interface InvoiceRow { number: string; total: number }\n"
                                 "export function renderInvoice(row: InvoiceRow) { return row.number }\n", encoding="utf-8")
    return root


def test_embedding_is_deterministic_and_normalised() -> None:
    a = embed("class Invoice total number")
    b = embed("class Invoice total number")
    assert a == b
    assert abs(cosine(a, a) - 1.0) < 1e-6
    assert cosine(embed("Invoice total"), embed("Invoice total number")) > cosine(embed("Invoice total"), embed("render html canvas"))


def test_extract_cards_covers_four_planes(tmp_path: Path) -> None:
    cards, edges = extract_cards(_corpus(tmp_path), "r", "rev")
    planes = {c.plane for c in cards}
    assert planes == {"code", "type", "data", "knowledge"}
    names = {c.name for c in cards}
    assert {"Invoice", "total_of", "invoice", "InvoiceRow", "renderInvoice", "Billing"} <= names
    relations = {e.relation for e in edges}
    assert {"declares", "annotated_with", "references", "mentions", "imports"} <= relations


def test_grey_matter_ingests_searches_and_projects_tensor(tmp_path: Path) -> None:
    grey = GreyMatter(tmp_path / "gm.db")
    try:
        report = grey.ingest_repo(_corpus(tmp_path / "repo"), name="billing")
        assert report["cards"] > 5 and report["edges"] > 3
        assert report["planes"]["knowledge"] >= 2
        assert report["verified_bindings"] >= 1  # README literally names Invoice / total_of
        hits = grey.search("sum an invoice total", k=3)
        assert hits and hits[0]["name"] in {"total_of", "Invoice", "invoice", "InvoiceRow"}
        tensor = grey.relation_tensor(report["repo_id"])
        assert tensor["schema"] == "daedalus-kitchen-relation-tensor/1"
        assert tensor["total"] == report["edges"]
        assert tensor["cross_plane"] >= 1
        assert len(tensor["sha256"]) == 64
        stats = grey.stats()
        assert stats["repos"] == 1 and stats["cards"] == report["cards"]
        context = grey.motif_context("invoice")
        assert "Grey Matter retrieval" in context and "billing" in context
        again = grey.ingest_repo(_corpus(tmp_path / "repo2"), name="billing2")
        assert grey.stats()["repos"] == 2
        assert again["repo_id"] != report["repo_id"]
    finally:
        grey.close()


# --------------------------------------------------------------------------- #
# Toolchain                                                                    #
# --------------------------------------------------------------------------- #
def test_toolchain_prefers_manifest_and_runs_steps(tmp_path: Path) -> None:
    (tmp_path / toolchain.MANIFEST).write_text(json.dumps({
        "stack": "python", "build": ["python", "-c", "print('built')"], "test": ["python", "-c", "import sys; sys.exit(3)"],
        "run": ["python", "-m", "http.server"], "preview": "http://127.0.0.1:8000"}), encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    assert plan.source == "manifest" and plan.stack == "python"
    assert [s.name for s in plan.steps] == ["build", "test"]
    assert plan.steps[0].argv[0] == sys.executable
    observations = toolchain.run_plan(plan, tmp_path, timeout_s=60)
    green, failures = toolchain.verdict(observations)
    assert not green and failures == ["test"]
    assert "built" in observations[0].output_tail
    assert "exit 3" in toolchain.failure_digest(observations)


def test_toolchain_detects_python_layout(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    assert plan.stack == "python" and [s.name for s in plan.steps] == ["build", "test"]
    assert plan.run == [sys.executable, "main.py"]


def test_toolchain_detects_static_web_and_none(tmp_path: Path) -> None:
    assert toolchain.detect(tmp_path).stack == "unknown"
    (tmp_path / "index.html").write_text("<!doctype html><html><body>hi</body></html>", encoding="utf-8")
    plan = toolchain.detect(tmp_path)
    assert plan.stack == "static-web" and plan.preview == "http://127.0.0.1:8765"
    observations = toolchain.run_plan(plan, tmp_path, timeout_s=60)
    assert toolchain.verdict(observations)[0]


# --------------------------------------------------------------------------- #
# Chef with an injected builder                                                #
# --------------------------------------------------------------------------- #
def _fake_builder(files: dict[str, str], *, ok: bool = True):
    calls: list[str] = []

    def builder(workspace: Path, prompt: str, timeout_s: int) -> BuilderReport:
        calls.append(prompt)
        for rel, text in files.items():
            path = workspace / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return BuilderReport("fake", ok, 0, 0.01, "wrote files", sorted(files))

    builder.calls = calls  # type: ignore[attr-defined]
    return builder


_GREEN_APP = {
    "README.md": "# Notes\n\nRun `python main.py`.\n",
    "main.py": "def main():\n    return 'notes'\n\nif __name__ == '__main__':\n    print(main())\n",
    "tests/test_main.py": "from main import main\n\ndef test_main():\n    assert main() == 'notes'\n",
    toolchain.MANIFEST: json.dumps({"stack": "python", "build": ["python", "-m", "compileall", "-q", "."],
                                   "test": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                   "run": ["python", "main.py"], "preview": None}),
}


def test_chef_builds_checks_and_nominates(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        builder = _fake_builder(_GREEN_APP)
        chef = Chef(kitchen, builder=builder, max_repairs=1)
        order = parse_order("bau mir eine app für notizen")
        assert order is not None
        assert kitchen.ledger.open_order(order.order_id, order.kind, "proj", order.text)
        result = chef.cook(order, project="proj", repo_root=None)
        assert result["status"] == "nominated", result
        assert result["automatic_promotion"] is False and result["owner_approval_required"] is True
        assert result["checks"] == {"build": True, "test": True}
        assert result["repairs"] == 0 and result["builder_lanes"] == ["fake"]
        workspace = Path(result["workspace"])
        assert (workspace / "main.py").is_file()
        digest, files = tree_digest(workspace)
        assert digest == result["candidate_tree_sha256"] and files == result["files"] >= 4
        packet = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
        assert packet["schema"] == "daedalus-kitchen-evidence/1"
        assert packet["containment"].startswith("deferred")
        assert packet["candidate_twin"]["cards"] >= 3
        assert "Corpus motifs" not in builder.calls[0]  # empty corpus: no motifs claimed
        ledger_row = kitchen.ledger.order(order.order_id)
        assert ledger_row["status"] == "nominated" and any("evidence packet" in e["text"] for e in ledger_row["events"])
    finally:
        kitchen.close()


def test_chef_repairs_then_fails_honestly(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        red = dict(_GREEN_APP)
        red["tests/test_main.py"] = "def test_red():\n    assert False\n"
        builder = _fake_builder(red)
        chef = Chef(kitchen, builder=builder, max_repairs=2)
        order = parse_order("build me a notes app")
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        result = chef.cook(order, project=None, repo_root=None)
        assert result["status"] == "failed"
        assert result["repairs"] == 2 and len(builder.calls) == 3
        assert "Repair round 1" in builder.calls[1] and "FAILURES" in builder.calls[1]
        assert result["owner_approval_required"] is False
    finally:
        kitchen.close()


def test_chef_uses_grey_matter_motifs_when_corpus_exists(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        kitchen.grey.ingest_repo(_corpus(tmp_path / "corpus"), name="billing")
        builder = _fake_builder(_GREEN_APP)
        chef = Chef(kitchen, builder=builder, max_repairs=0)
        order = parse_order("bau mir eine app für invoice total")
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        chef.cook(order, project=None, repo_root=None)
        assert "Corpus motifs" in builder.calls[0] and "billing" in builder.calls[0]
    finally:
        kitchen.close()


def test_chef_blocks_without_builder(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        def unavailable(workspace: Path, prompt: str, timeout_s: int) -> BuilderReport:
            raise BuilderUnavailable("no lane")
        chef = Chef(kitchen, builder=unavailable)
        order = parse_order("bau mir eine app")
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        result = chef.cook(order, project=None, repo_root=None)
        assert result["status"] == "blocked" and "no lane" in result["blocker"]
    finally:
        kitchen.close()


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "kitchen@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "kitchen"], cwd=root, check=True)
    for rel, text in _GREEN_APP.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True)
    return root


def test_chef_improves_in_detached_worktree_and_leaves_checkout_untouched(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "proj")
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        improved = {"main.py": "def main():\n    return 'notes'\n\ndef extra():\n    return 1\n\nif __name__ == '__main__':\n    print(main())\n",
                    "docs/CHANGES.md": "added extra\n"}
        chef = Chef(kitchen, builder=_fake_builder(improved), max_repairs=0)
        order = parse_order("improve this app: add an extra function")
        kitchen.ledger.open_order(order.order_id, order.kind, "proj", order.text)
        result = chef.cook(order, project="proj", repo_root=str(repo))
        assert result["status"] == "nominated", result
        assert result["base_revision"] and result["patch"]
        patch = Path(result["patch"]).read_text(encoding="utf-8")
        assert "def extra" in patch and "docs/CHANGES.md" in patch
        assert "def extra" not in (repo / "main.py").read_text(encoding="utf-8")
        assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout == ""
    finally:
        kitchen.close()


def test_self_improvement_rejects_leakage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _git_repo(tmp_path / "daedalus")
    (repo / "daedalus" / "spine").mkdir(parents=True)
    (repo / "daedalus" / "spine" / "ledger.py").write_text("X = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "spine"], cwd=repo, check=True)
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        chef = Chef(kitchen, builder=_fake_builder({"daedalus/spine/ledger.py": "X = 2\n"}), max_repairs=0)
        order = parse_order("verbessere dich selbst")
        assert order.kind == orders.KIND_SELF
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        result = chef._improve(order, str(repo), lambda *a, **k: None, self_mode=True)
        assert result["status"] == "failed" and result["rejection"] == "leakage_boundary"
        assert result["protected_paths_touched"] == ["daedalus/spine/ledger.py"]
        assert "daedalus/spine/" in PROTECTED_PREFIXES
    finally:
        kitchen.close()


def test_feed_ingests_local_repository(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        corpus = _corpus(tmp_path / "corpus")
        chef = Chef(kitchen, builder=_fake_builder({}))
        order = parse_order(f"füttere ariadne mit {corpus}")
        assert order.kind == orders.KIND_FEED and str(corpus) in order.sources
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        result = chef.cook(order, project=None, repo_root=None)
        assert result["status"] == "done"
        row = result["ingested"][0]
        assert row["cards"] > 5 and len(row["relation_tensor_sha256"]) == 64 and row["cross_plane_edges"] >= 1
        assert (kitchen.root / "corpus" / f"{row['repo_id']}.tensor.json").is_file()
        assert result["grey_matter"]["repos"] == 1
    finally:
        kitchen.close()


# --------------------------------------------------------------------------- #
# The chat door                                                                #
# --------------------------------------------------------------------------- #
def test_waiter_serves_orders_and_status_through_the_chat_door(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAEDALUS_KITCHEN_ROOT", str(tmp_path / "kitchen"))
    monkeypatch.setenv("DAEDALUS_KITCHEN_SYNC", "1")
    from daedalus.orchestration.ikarus.kitchen import waiter
    waiter._KITCHENS.clear()
    import daedalus.orchestration.ikarus.kitchen.chef as chef_mod
    monkeypatch.setattr(chef_mod, "run_builder",
                        lambda workspace, prompt, **kw: _fake_builder(_GREEN_APP)(workspace, prompt, 0))
    assert waiter.maybe_serve(None, "wie geht es dir") is None
    served = waiter.maybe_serve(None, "bau mir nh app für notizen")
    assert served is not None and served["intent"] == "kitchen" and served["shell"] == "kitchen"
    assert served["status"] == "nominated" and "nominiert" in served["assistant"]
    assert served["result"]["automatic_promotion"] is False
    status = waiter.maybe_serve(None, "Küche Status")
    assert status is not None and served["order_id"] in status["assistant"]
    again = waiter.maybe_serve(None, "bau mir nh app für notizen")
    assert again["status"] == "nominated"  # terminal orders may be re-placed
    from daedalus.orchestration.ikarus import shell
    envelope = shell._ask_inner(None, "Küche Status")
    assert envelope["intent"] == "kitchen"
    waiter._KITCHENS.clear()
