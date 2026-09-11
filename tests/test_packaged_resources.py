from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from daedalus import config, router
from daedalus.orchestration import agents_registry, categories

# The OWNER: the catalogue test below fakes ``gui_catalogue.__file__`` to a
# site-packages path, and ``load_catalogue`` resolves the packaged data from
# the owner module's own ``__file__``. Faking it on the flat facade G1-FLAT-01
# left behind would have patched a name nothing reads; G1-FLAT-02 retired it.
from daedalus.orchestration import gui_catalogue
from daedalus.resources import (
    ResourceDriftError,
    iter_builtin_files,
    read_builtin_text,
    schema_text,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("relative", "legacy", "suffix"),
    (
        ("agents", ROOT / "agents", ".json"),
        ("templates/agents", ROOT / "templates" / "agents", ".json"),
        ("catalogue/gui", ROOT / "catalogue" / "gui", ".json"),
        ("schemas", ROOT / "configs" / "schemas", ".json"),
    ),
)
def test_packaged_directories_match_legacy_mirrors(
    relative: str, legacy: Path, suffix: str
) -> None:
    packaged = iter_builtin_files(relative, legacy=legacy, suffix=suffix)
    assert packaged
    assert [item.name for item in packaged] == [
        item.name for item in sorted(legacy.glob(f"*{suffix}"))
    ]


@pytest.mark.parametrize("name", config.TOOL_INSTRUCTION_TEMPLATES)
def test_packaged_instruction_templates_match_checkout(name: str) -> None:
    assert read_builtin_text(
        f"templates/{name}", legacy=ROOT / "templates" / name
    ) == (ROOT / "templates" / name).read_text(encoding="utf-8")


def test_router_reads_packaged_roles_without_checkout_root(monkeypatch) -> None:
    monkeypatch.setattr(router, "AGENT_DIR", ROOT / "does-not-exist" / "agents")
    names = {row["name"] for row in router.load_agents()}
    assert {"qa-critic", "hardware-dev"}.issubset(names)


def test_router_prefers_explicit_project_roles(tmp_path: Path) -> None:
    override = tmp_path / ".agentenv" / "agents"
    override.mkdir(parents=True)
    (override / "project-only.json").write_text(
        json.dumps({"name": "project-only", "triggers": ["local"]}),
        encoding="utf-8",
    )
    assert [row["name"] for row in router.load_agents(str(tmp_path))] == [
        "project-only"
    ]


def test_init_repo_reads_packaged_templates_without_checkout_root(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "TEMPLATE_DIR", ROOT / "does-not-exist" / "templates")
    config.init_repo(str(tmp_path))
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert tuple((tmp_path / ".agentenv" / "agents").glob("*.json"))


def test_catalogue_reads_packaged_data_without_checkout_root(
    monkeypatch, tmp_path: Path
) -> None:
    fake_module = (
        tmp_path / "site-packages" / "daedalus" / "orchestration" / "gui_catalogue.py"
    )
    monkeypatch.setattr(gui_catalogue, "__file__", str(fake_module))
    catalogue = gui_catalogue.load_catalogue()
    assert set(catalogue.sources) == {"external.json", "glass.json"}
    assert catalogue.entries


def test_categories_read_packaged_seed_and_defaults_are_read_only(monkeypatch) -> None:
    monkeypatch.setattr(categories, "CATEGORIES_PATH", ROOT / "missing" / "categories.json")
    assert categories.get("review") is not None
    with pytest.raises(ValueError, match="repo_root is required"):
        categories.update("review", {"color": "#000000"})
    with pytest.raises(ValueError, match="repo_root is required"):
        agents_registry.role_path("qa-critic")


def test_packaged_json_schema_is_addressed_by_name() -> None:
    payload = json.loads(schema_text("attempt-start-v1.schema.json"))
    assert payload["$schema"].startswith("https://json-schema.org/")
    packet_index = json.loads(schema_text("work-packet-index-v1.schema.json"))
    assert packet_index["properties"]["schema"]["const"] == (
        "daedalus-work-packet-index/1"
    )
    with pytest.raises(ValueError):
        schema_text("../attempt-start-v1.schema.json")
    with pytest.raises(ValueError):
        read_builtin_text("../agents/qa-critic.json")


def test_divergent_legacy_mirror_refuses(tmp_path: Path) -> None:
    mirror = tmp_path / "agents"
    shutil.copytree(ROOT / "agents", mirror)
    target = mirror / "qa-critic.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ResourceDriftError, match="differs"):
        iter_builtin_files("agents", legacy=mirror, suffix=".json")
