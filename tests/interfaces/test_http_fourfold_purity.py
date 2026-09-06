from __future__ import annotations

from pathlib import Path

from daedalus.interfaces.http import web_api
from daedalus.structcore import index as index_mod


def test_fourfold_cold_read_uses_no_disk_cache_or_child_process(
    tmp_path: Path, monkeypatch
) -> None:
    """The new GET projection stays effect-free even on its first request."""

    (tmp_path / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project\n\nSee `app.py`.\n", encoding="utf-8")

    monkeypatch.setattr(web_api, "resolve_repo_root", lambda *_: str(tmp_path))
    monkeypatch.setattr(web_api, "_project_center", lambda *_: [])
    monkeypatch.setattr(web_api, "_project_ignore", lambda *_: [])
    monkeypatch.setattr(
        index_mod,
        "FileCache",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Fourfold GET opened the persistent SQLite cache")
        ),
    )
    monkeypatch.setattr(
        index_mod,
        "git_churn",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Fourfold GET spawned Git")
        ),
    )
    index_mod._INDEX_CACHE.clear()

    result = web_api._structure_index("fixture", refresh=True, fourfold=True)

    assert result["scope_key"].endswith("+effect-free+docs+types+wiki")
    assert "app.py" in result["modules"]
    assert "README.md" in result["modules"]
    assert all(row.get("churn") == 0 for row in result["module_heat"])


def test_ordinary_index_does_not_share_fourfold_effect_free_identity(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_NO_CACHE", "1")
    monkeypatch.setattr(index_mod, "git_churn", lambda *_: {})
    index_mod._INDEX_CACHE.clear()

    pure = index_mod.cached_index(tmp_path, effect_free=True)
    ordinary = index_mod.cached_index(tmp_path)

    assert pure is not ordinary
    assert pure["scope_key"] != ordinary["scope_key"]
