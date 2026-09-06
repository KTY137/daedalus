"""Tests for ``python -m daedalus.wiki`` -- the dispatcher over plan, verify, health.

The module documents four exit codes and one arity bug it once had (a Path
bound into ``k`` by position). Nothing pinned either until 2026-09-05. These
tests exercise the dispatcher without crossing the effect boundary of the two
delegates that write: ``plan.main`` and ``verify.main`` are replaced by
recorders, so what is tested is the argv contract between dispatcher and
delegate, which is exactly the surface that drifted before.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from daedalus.wiki import __main__ as wiki_cli


def test_usage_error_is_exit_2() -> None:
    with pytest.raises(SystemExit) as caught:
        wiki_cli.main([])
    assert caught.value.code == 2


@pytest.mark.parametrize("command", ["plan", "verify", "health"])
def test_a_root_that_is_not_a_directory_is_exit_2(tmp_path: pathlib.Path, command: str,
                                                  capsys: pytest.CaptureFixture) -> None:
    missing = tmp_path / "nope"
    assert wiki_cli.main([command, str(missing)]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_plan_delegates_with_the_documented_argv_order(tmp_path: pathlib.Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    from daedalus.wiki import plan as wiki_plan
    seen: list[list[str]] = []
    monkeypatch.setattr(wiki_plan, "main", lambda argv: seen.append(argv) or 0)
    assert wiki_cli.main(["plan", str(tmp_path), "--authors", "7", "--wiki-dir", "w"]) == 0
    assert seen == [["daedalus.wiki.plan", str(tmp_path.resolve()), "7", "w"]]


def test_verify_passes_the_wiki_dir_through_verbatim(tmp_path: pathlib.Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from daedalus.wiki import verify as wiki_verify
    seen: list[list[str]] = []
    monkeypatch.setattr(wiki_verify, "main", lambda argv: seen.append(argv) or 1)
    assert wiki_cli.main(["verify", str(tmp_path)]) == 1
    assert wiki_cli.main(["verify", str(tmp_path), "rel/wiki"]) == 1
    assert seen == [["daedalus.wiki.verify", str(tmp_path.resolve())],
                    ["daedalus.wiki.verify", str(tmp_path.resolve()), "rel/wiki"]]


def test_health_prints_json_and_never_gates(tmp_path: pathlib.Path,
                                            capsys: pytest.CaptureFixture) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("class A:\n    pass\n", encoding="utf-8")
    assert wiki_cli.main(["health", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    # the documented default k survives the dispatch -- the retained arity bug
    # put the root Path into k and crashed inside k_core
    assert report["k"] == 3
    assert "could_not_measure" in report


def test_health_without_a_callable_is_exit_3_not_0(tmp_path: pathlib.Path,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture) -> None:
    from daedalus.wiki import metrics as wiki_metrics
    monkeypatch.setattr(wiki_metrics, "wiki_health", None)
    assert wiki_cli.main(["health", str(tmp_path)]) == 3
    assert "not available" in capsys.readouterr().err
