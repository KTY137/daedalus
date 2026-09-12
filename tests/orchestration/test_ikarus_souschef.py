"""The Sous-Chef: a tool-less local model working through kitchen task division.

The model is faked: these tests pin the DIVISION OF LABOUR (plan → one file per
call with bounded context → kitchen-owned evaluator → triage-scoped repair),
not any particular model's taste. Live Ollama runs are owner-operated evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus.kitchen import souschef, toolchain
from daedalus.orchestration.ikarus.kitchen.builders import BuilderUnavailable
from daedalus.orchestration.ikarus.kitchen.greymatter import GreyMatter

_PLAN = {"summary": "A shopping list.", "stack": "static-web",
         "files": [{"path": "index.html", "purpose": "shell with #item-input and #item-list"},
                   {"path": "app.js", "purpose": "addItem(), removeItem(), storage key \"shopping-list\""},
                   {"path": "styles.css", "purpose": "styles"},
                   {"path": "tests/test_app.py", "purpose": "model-proposed tests (kitchen overrides)"},
                   {"path": "README.md", "purpose": "how to run"}],
         "shared_contract": "ids #item-input #item-list; functions addItem() removeItem(); localStorage key \"shopping-list\""}

_FILES = {
    "index.html": "<!doctype html><html><head><title>List</title><link rel=\"stylesheet\" href=\"styles.css\"></head>"
                  "<body><h1>List</h1><input id=\"item-input\"><ul id=\"item-list\"></ul><script src=\"app.js\"></script></body></html>",
    "app.js": "function addItem(t){const l=load();l.push(t);localStorage.setItem('shopping-list',JSON.stringify(l));}\n"
              "function removeItem(i){const l=load();l.splice(i,1);localStorage.setItem('shopping-list',JSON.stringify(l));}\n"
              "function load(){return JSON.parse(localStorage.getItem('shopping-list')||'[]');}\n",
    "styles.css": "body{font-family:sans-serif}\n",
    "README.md": "# List\n\nRun `python -m http.server 8765` and open http://127.0.0.1:8765.\n",
}


def _fake_chat_factory(record: list[dict], *, repair_pick: str = "app.js"):
    def fake_chat(messages, *, json_mode, timeout_s, host, model, num_predict=0):
        user = messages[-1]["content"]
        record.append({"json": json_mode, "chars": sum(len(m["content"]) for m in messages), "user": user})
        if json_mode and "Plan at most" in user:
            return json.dumps(_PLAN)
        if json_mode and "FAILING CHECK OUTPUT" in user:
            return json.dumps({"files": [repair_pick, "tests/test_app.py"], "diagnosis": "app.js lacks a function"})
        if json_mode and "Choose at most 6 files" in user:
            return json.dumps({"summary": "add clear", "files": [{"path": "app.js", "purpose": "add clearList()"},
                                                                 {"path": "tests/test_app.py", "purpose": "rewrite tests"},
                                                                 {"path": "tests/test_clear.py", "purpose": "new test"}]})
        target = user.split("TARGET FILE: ", 1)[1].split("\n", 1)[0].strip()
        body = _FILES.get(target, f"// {target}\n")
        if "REPAIR this file" in user:
            body = body + "function repaired(){}\n"
        return f"```\n{body}```"
    return fake_chat


def test_build_divides_labour_and_kitchen_owns_the_evaluator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record: list[dict] = []
    monkeypatch.setattr(souschef, "_chat", _fake_chat_factory(record))
    monkeypatch.setattr(souschef, "ollama_available", lambda host=None, model=None: True)
    grey = GreyMatter(tmp_path / "gm.db")
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        report = souschef.ollama_builder(workspace, "unused", 600, {"order_text": "bau mir eine einkaufsliste", "mode": "build",
                                                                  "grey": grey, "log": lambda t: None})
        assert report.ok and report.lane == "ollama"
        assert set(report.changed_files) >= {"index.html", "app.js", "styles.css", "README.md", "tests/test_app.py", toolchain.MANIFEST}
        evaluator = (workspace / "tests" / "test_app.py").read_text(encoding="utf-8")
        assert "Kitchen-owned structural evaluator" in evaluator
        assert '"item-input"' in evaluator and '"addItem"' in evaluator
        # one call per file, every call bounded, the plan never re-sent whole
        writes = [r for r in record if not r["json"]]
        assert len(writes) == 4  # tests/ was not asked from the model
        assert all(r["chars"] < 12_000 for r in record)
        assert report.details["step_count"] == len(record) == 5
        assert report.details["decomposition"] == "grey-matter-task-division/1"
        plan = toolchain.detect(workspace)
        assert plan.source == "manifest" and plan.stack == "static-web"
        observations = toolchain.run_plan(plan, workspace, timeout_s=120)
        assert toolchain.verdict(observations)[0], toolchain.failure_digest(observations)
    finally:
        grey.close()


def test_repair_never_picks_the_evaluator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record: list[dict] = []
    monkeypatch.setattr(souschef, "_chat", _fake_chat_factory(record))
    monkeypatch.setattr(souschef, "ollama_available", lambda host=None, model=None: True)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    souschef.ollama_builder(workspace, "unused", 600, {"order_text": "einkaufsliste", "mode": "build", "log": lambda t: None})
    before = (workspace / "tests" / "test_app.py").read_text(encoding="utf-8")
    report = souschef.ollama_builder(workspace, "Repair round 1 ...\n\nFAILURES:\n### test (exit 1)\nmissing", 600,
                                     {"order_text": "einkaufsliste", "mode": "repair", "log": lambda t: None})
    assert report.ok and report.changed_files == ["app.js"]
    assert (workspace / "tests" / "test_app.py").read_text(encoding="utf-8") == before
    assert "repaired" in (workspace / "app.js").read_text(encoding="utf-8")


def test_improve_keeps_existing_tests_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record: list[dict] = []
    monkeypatch.setattr(souschef, "_chat", _fake_chat_factory(record))
    monkeypatch.setattr(souschef, "ollama_available", lambda host=None, model=None: True)
    workspace = tmp_path / "ws"
    (workspace / "tests").mkdir(parents=True)
    for rel, text in _FILES.items():
        (workspace / rel).write_text(text, encoding="utf-8")
    (workspace / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    report = souschef.ollama_builder(workspace, "unused", 600, {"order_text": "add a clear button", "mode": "improve", "log": lambda t: None})
    assert report.ok
    assert "app.js" in report.changed_files and "tests/test_clear.py" in report.changed_files
    assert "tests/test_app.py" not in report.changed_files
    assert (workspace / "tests" / "test_app.py").read_text(encoding="utf-8") == "def test_x():\n    assert True\n"


def test_unavailable_ollama_raises_builder_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(souschef, "ollama_available", lambda host=None, model=None: False)
    with pytest.raises(BuilderUnavailable):
        souschef.ollama_builder(tmp_path, "x", 10, {"mode": "build"})


def test_host_url_accepts_ollama_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAEDALUS_KITCHEN_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11435")
    assert souschef.host_url() == "http://127.0.0.1:11435"
    monkeypatch.setenv("OLLAMA_HOST", "http://0.0.0.0:11434/")
    assert souschef.host_url() == "http://127.0.0.1:11434"


def test_contract_terms_extraction() -> None:
    ids, functions, keys = souschef._contract_terms(_PLAN)
    assert ids == ["item-input", "item-list"]
    assert functions == ["addItem", "removeItem"]
    assert keys == ["shopping-list"]
