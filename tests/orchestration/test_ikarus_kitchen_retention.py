"""Adversarial evidence-retention regressions for KITCHEN-02."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus.kitchen import chef as chef_module, toolchain, waiter
from daedalus.orchestration.ikarus.kitchen.chef import Chef, Kitchen
from daedalus.orchestration.ikarus.kitchen.ledger import OrderLedger
from daedalus.orchestration.ikarus.kitchen.orders import parse_order
from daedalus.orchestration.ikarus.kitchen.report import BuilderReport


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "retention@test.invalid")
    _git(root, "config", "user.name", "Retention test")
    (root / "main.py").write_text("print('base')\n", encoding="utf-8")
    (root / "daedalus" / "spine").mkdir(parents=True)
    (root / "daedalus" / "spine" / "protected.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "--", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def test_terminal_order_is_immutable_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "orders.db"
    first, second = OrderLedger(path), OrderLedger(path)
    try:
        assert first.open_order("same", "build_app", "a", "request")
        first.set_status("same", "failed", {"status": "failed", "error": "retained"})
        before = first.order("same")
        assert not second.open_order("same", "build_app", "b", "request")
        assert second.order("same") == before
    finally:
        first.close()
        second.close()


def test_waiter_replays_without_builder_or_artifact_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    monkeypatch.setattr(waiter, "kitchen_for", lambda root: kitchen)
    monkeypatch.setattr(waiter, "_repo_root", lambda project: None)
    order = parse_order("build me a notes app")
    assert order is not None
    artifact = tmp_path / "negative-evidence.json"
    artifact.write_bytes(b"retained failure")
    calls = []

    class Worker:
        def cook(self, order, *, project, repo_root):
            calls.append(order.order_id)
            result = {"status": "failed", "error": "fixture", "evidence_path": str(artifact)}
            kitchen.ledger.set_status(order.order_id, "failed", result)
            return result

    try:
        first = waiter.place_order(None, order, sync=True, chef=Worker())
        before = kitchen.ledger.order(first["order_id"])
        second = waiter.place_order(None, order, sync=True, chef=Worker())
        assert second["replayed"] and second["result"] == first["result"]
        assert calls == [first["order_id"]]
        assert kitchen.ledger.order(first["order_id"]) == before
        assert artifact.read_bytes() == b"retained failure"
    finally:
        kitchen.close()


def test_same_words_in_two_projects_have_distinct_orders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    monkeypatch.setattr(waiter, "kitchen_for", lambda root: kitchen)
    monkeypatch.setattr(waiter, "_repo_root", lambda project: str(tmp_path / project))
    order = parse_order("improve this app")
    calls = []

    class Worker:
        def cook(self, order, *, project, repo_root):
            calls.append((project, order.order_id))
            result = {"status": "blocked", "blocker": project}
            kitchen.ledger.set_status(order.order_id, "blocked", result)
            return result

    try:
        a = waiter.place_order("a", order, sync=True, chef=Worker())
        b = waiter.place_order("b", order, sync=True, chef=Worker())
        assert a["order_id"] != b["order_id"]
        assert len(calls) == 2
        assert kitchen.ledger.order(a["order_id"])["result"]["blocker"] == "a"
    finally:
        kitchen.close()


def test_self_renovation_rename_checks_removed_source_before_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path / "repo")
    kitchen = Kitchen(tmp_path / "kitchen")

    def builder(workspace, prompt, timeout_s):
        _git(workspace, "mv", "daedalus/spine/protected.py", "ordinary.py")
        return BuilderReport("fixture", True, 0, 0, "rename")

    def forbidden(*args, **kwargs):
        pytest.fail("protected rename reached the evaluator")

    monkeypatch.setattr(chef_module, "run_plan", forbidden)
    try:
        order = parse_order("verbessere dich selbst")
        result = Chef(kitchen, builder=builder)._improve(order, str(repo), lambda *a, **k: None, self_mode=True)
        assert result["rejection"] == "leakage_boundary"
        assert result["protected_paths_touched"] == ["daedalus/spine/protected.py"]
        assert (repo / "daedalus/spine/protected.py").is_file()
    finally:
        kitchen.close()


def test_failed_git_inspection_does_not_mean_no_changes(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    try:
        with pytest.raises(RuntimeError, match="git inspection failed"):
            Chef(kitchen)._leak(tmp_path, "fake-base")
    finally:
        kitchen.close()


def test_existing_candidate_and_evidence_cannot_be_overwritten(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    order = parse_order("build me a notes app")
    workspace = kitchen.root / "candidates" / f"{chef_module._slug(order.text)}-{order.order_id[-8:]}"
    workspace.mkdir()
    (workspace / "previous.txt").write_bytes(b"previous failure")
    evidence = kitchen.root / "orders" / "previous.evidence.json"
    evidence.write_bytes(b"previous receipt")
    try:
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        result = Chef(kitchen).cook(order, project=None, repo_root=None)
        assert result["status"] == "failed" and "FileExistsError" in result["error"]
        assert (workspace / "previous.txt").read_bytes() == b"previous failure"
        with pytest.raises(FileExistsError):
            chef_module._write_json(evidence, {"replacement": True})
        assert evidence.read_bytes() == b"previous receipt"
    finally:
        kitchen.close()


def test_repair_cannot_replace_failing_command_and_negative_round_survives(tmp_path: Path) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")
    calls = []

    def builder(workspace, prompt, timeout_s):
        calls.append(prompt)
        code = "raise SystemExit(7)" if len(calls) == 1 else "print('pretend pass')"
        (workspace / toolchain.MANIFEST).write_text(json.dumps({"test": ["python", "-c", code]}), encoding="utf-8")
        return BuilderReport("fixture", True, 0, 0, "changed command")

    try:
        order = parse_order("build me a notes app")
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        result = Chef(kitchen, builder=builder).cook(order, project=None, repo_root=None)
        assert result["status"] == "failed"
        packet = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
        rounds = packet["verification_rounds"]
        assert len(rounds) == 2
        assert rounds[0]["observations"][0]["exit_code"] == 7
        assert rounds[1]["observations"][0]["name"] == "verification_integrity"
        assert "pretend pass" not in rounds[1]["observations"][0]["output_tail"]
    finally:
        kitchen.close()


def test_twin_failure_never_nominates_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kitchen = Kitchen(tmp_path / "kitchen")

    def broken_twin(*args, **kwargs):
        raise ValueError("extraction failed")

    monkeypatch.setattr(kitchen.grey, "ingest_repo", broken_twin)
    try:
        workspace = tmp_path / "candidate"
        workspace.mkdir()
        (workspace / "main.py").write_text("print('ok')\n", encoding="utf-8")
        order = parse_order("build me a notes app")
        plan = toolchain.Plan([], None, None, "fixture", "python")
        result = Chef(kitchen)._nominate(order, workspace, [], plan, [], True, lambda *a, **k: None,
                                         base_revision=None, patch=None)
        assert result["status"] == "failed" and result["checks"]["candidate_twin"] is False
        assert (workspace / "main.py").is_file()
    finally:
        kitchen.close()


def test_cli_async_refuses_before_accepting_an_unresumable_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from daedalus.orchestration.ikarus.kitchen import __main__ as cli

    def forbidden(*args, **kwargs):
        pytest.fail("a one-shot CLI accepted a daemon-thread order")

    monkeypatch.setattr(cli, "place_order", forbidden)
    with pytest.raises(SystemExit) as result:
        cli.main(["order", "build me a notes app", "--async"])
    assert result.value.code == 2


def test_explicit_new_request_does_not_replace_original(monkeypatch: pytest.MonkeyPatch) -> None:
    from daedalus.orchestration.ikarus.kitchen import __main__ as cli
    seen = []

    def accept(project, order, **kwargs):
        seen.append(order.order_id)
        return {"status": "done"}

    monkeypatch.setattr(cli, "place_order", accept)
    for _ in range(2):
        assert cli.main(["order", "build me a notes app", "--request-id", "delivery-1"]) == 0
    assert cli.main(["order", "build me a notes app", "--new-request"]) == 0
    assert seen[0] == seen[1] != seen[2]


def test_failed_round_survives_repair_provider_disappearance(tmp_path: Path) -> None:
    from daedalus.orchestration.ikarus.kitchen.report import BuilderUnavailable

    kitchen = Kitchen(tmp_path / "kitchen")
    calls = []

    def builder(workspace, prompt, timeout_s):
        calls.append(prompt)
        if len(calls) > 1:
            saved = list((kitchen.root / "orders").glob("*.round-0000.json"))
            assert len(saved) == 1  # failure persisted BEFORE the repair effect
            raise BuilderUnavailable("provider stopped")
        (workspace / toolchain.MANIFEST).write_text(json.dumps({"test": ["python", "-c", "raise SystemExit(7)"]}), encoding="utf-8")
        return BuilderReport("fixture", True, 0, 0, "initial draft")

    try:
        order = parse_order("build me a notes app")
        kitchen.ledger.open_order(order.order_id, order.kind, None, order.text)
        result = Chef(kitchen, builder=builder).cook(order, project=None, repo_root=None)
        assert result["status"] == "failed"
        packet = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
        assert packet["verification_rounds"][0]["observations"][0]["exit_code"] == 7
        assert packet["verification_rounds"][1]["failures"] == ["repair_builder"]
        assert "provider stopped" in packet["builder_reports"][-1]["summary"]
    finally:
        kitchen.close()
