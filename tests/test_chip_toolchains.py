from __future__ import annotations

import os
from pathlib import Path

import pytest

from daedalus.chip_design import toolchains


def _launcher(
    root: Path,
    *,
    product: str,
    release: str,
    launcher_name: str,
    legacy: bool = False,
) -> Path:
    if legacy:
        path = root / product / release / "bin" / launcher_name
    else:
        path = root / release / product / "bin" / launcher_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"vendor launcher\n")
    return path.resolve()


def _configure_patterns(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tool_id: str,
    root: Path,
    product: str,
    launcher_name: str,
    reverse: bool = False,
) -> None:
    patterns = (
        str(root / "*" / product / "bin" / launcher_name),
        str(root / product / "*" / "bin" / launcher_name),
    )
    if reverse:
        patterns = tuple(reversed(patterns))
    attribute = "_WINDOWS_TOOL_GLOBS" if os.name == "nt" else "_POSIX_TOOL_GLOBS"
    monkeypatch.setattr(toolchains, attribute, {tool_id: patterns})


@pytest.mark.parametrize(
    ("tool_id", "product", "launcher_name"),
    (("vivado", "Vivado", "vivado.bat"), ("vitis", "Vitis", "vitis.bat")),
)
def test_amd_discovery_ranks_numeric_releases_and_refuses_malformed_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_id: str,
    product: str,
    launcher_name: str,
) -> None:
    malformed = _launcher(
        tmp_path,
        product=product,
        release="latest",
        launcher_name=launcher_name,
    )
    older = _launcher(
        tmp_path,
        product=product,
        release="2024.2",
        launcher_name=launcher_name,
    )
    base = _launcher(
        tmp_path,
        product=product,
        release="2025.1",
        launcher_name=launcher_name,
        legacy=True,
    )
    patch = _launcher(
        tmp_path,
        product=product,
        release="2025.1.1",
        launcher_name=launcher_name,
    )
    _configure_patterns(
        monkeypatch,
        tool_id=tool_id,
        root=tmp_path,
        product=product,
        launcher_name=launcher_name,
    )

    inventory = toolchains.trusted_vendor_tool_paths(tool_id)

    assert inventory == (str(older), str(base), str(patch))
    assert str(malformed) not in inventory
    assert toolchains.find_trusted_vendor_tool_path(tool_id) == str(patch)


@pytest.mark.parametrize(
    ("tool_id", "product", "launcher_name"),
    (("vivado", "Vivado", "vivado.bat"), ("vitis", "Vitis", "vitis.bat")),
)
def test_newer_numeric_amd_release_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_id: str,
    product: str,
    launcher_name: str,
) -> None:
    patch = _launcher(
        tmp_path,
        product=product,
        release="2025.1.1",
        launcher_name=launcher_name,
    )
    newer = _launcher(
        tmp_path,
        product=product,
        release="2026.1",
        launcher_name=launcher_name,
        legacy=True,
    )
    _configure_patterns(
        monkeypatch,
        tool_id=tool_id,
        root=tmp_path,
        product=product,
        launcher_name=launcher_name,
    )

    assert toolchains.trusted_vendor_tool_paths(tool_id) == (str(patch), str(newer))
    assert toolchains.find_trusted_vendor_tool_path(tool_id) == str(newer)


def test_equal_release_tie_is_stable_across_layout_and_pattern_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unified = _launcher(
        tmp_path,
        product="Vivado",
        release="2025.1.1",
        launcher_name="vivado.bat",
    )
    legacy = _launcher(
        tmp_path,
        product="Vivado",
        release="2025.1.1",
        launcher_name="vivado.bat",
        legacy=True,
    )
    expected = tuple(
        sorted((str(unified), str(legacy)), key=lambda path: (path.casefold(), path))
    )
    _configure_patterns(
        monkeypatch,
        tool_id="vivado",
        root=tmp_path,
        product="Vivado",
        launcher_name="vivado.bat",
    )
    first = toolchains.trusted_vendor_tool_paths("vivado")
    first_selection = toolchains.find_trusted_vendor_tool_path("vivado")

    _configure_patterns(
        monkeypatch,
        tool_id="vivado",
        root=tmp_path,
        product="Vivado",
        launcher_name="vivado.bat",
        reverse=True,
    )
    second = toolchains.trusted_vendor_tool_paths("vivado")

    assert first == second == expected
    assert first_selection == toolchains.find_trusted_vendor_tool_path("vivado")
    assert first_selection == expected[-1]


def test_finder_ranks_an_inventory_independently_of_its_input_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _launcher(
        tmp_path,
        product="Vivado",
        release="2025.1",
        launcher_name="vivado.bat",
    )
    patch = _launcher(
        tmp_path,
        product="Vivado",
        release="2025.1.1",
        launcher_name="vivado.bat",
    )
    monkeypatch.setattr(
        toolchains,
        "trusted_vendor_tool_paths",
        lambda _tool_id: (str(patch), str(base)),
    )

    assert toolchains.find_trusted_vendor_tool_path("vivado") == str(patch)
