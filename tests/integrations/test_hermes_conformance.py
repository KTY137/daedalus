from __future__ import annotations

import subprocess
from pathlib import Path

from daedalus.integrations.hermes.configuration import HermesPinnedSource, file_sha256
from daedalus.integrations.hermes.conformance import (
    HermesAdmissionEvidence,
    build_conformance_receipt,
    scan_forbidden_imports,
)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _checkout(tmp_path: Path) -> tuple[Path, HermesPinnedSource]:
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "run_agent.py").write_text("class AIAgent:\n    pass\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Daedalus Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")
    source = HermesPinnedSource(
        repository="NousResearch/hermes-agent",
        release="fixture",
        tag="fixture",
        commit=_git(root, "rev-parse", "HEAD"),
        tree=_git(root, "rev-parse", "HEAD^{tree}"),
        run_agent_sha256=file_sha256(root / "run_agent.py"),
        license_sha256=file_sha256(root / "LICENSE"),
        archive_sha256="2" * 64,
    )
    return root, source


def test_static_scan_rejects_direct_model_or_network_clients(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "bad.py").write_text("import requests\nfrom openai import OpenAI\n", encoding="utf-8")
    assert scan_forbidden_imports(adapter) == ("bad.py:openai", "bad.py:requests")


def test_conformance_receipt_remains_non_production_without_all_evidence(tmp_path: Path) -> None:
    checkout, source = _checkout(tmp_path)
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "safe.py").write_text("from pathlib import Path\n", encoding="utf-8")
    receipt = build_conformance_receipt(
        checkout_root=checkout,
        adapter_root=adapter,
        source=source,
        evidence=HermesAdmissionEvidence(
            sealed_broker_verified=True,
            exact_version_verified=True,
        ),
    )
    assert receipt.forbidden_imports == ()
    assert receipt.evidence.production_admitted is False
    assert receipt.to_dict()["production_admitted"] is False
    assert len(receipt.digest) == 64
