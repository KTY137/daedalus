"""Static and evidence-driven conformance checks for the Hermes adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ast
from pathlib import Path

from .configuration import DEFAULT_HERMES_SOURCE, HermesPinnedSource, file_sha256, verify_hermes_checkout
from .protocol import canonical_sha256


class HermesConformanceError(RuntimeError):
    pass


FORBIDDEN_DIRECT_IMPORTS = frozenset(
    {
        "anthropic",
        "openai",
        "requests",
        "httpx",
        "urllib.request",
        "websocket",
        "websockets",
    }
)


@dataclass(frozen=True)
class HermesAdmissionEvidence:
    sealed_broker_verified: bool = False
    containment_verified: bool = False
    gateway_fault_matrix_verified: bool = False
    unknown_outcome_verified: bool = False
    live_upstream_compatibility_verified: bool = False
    exact_version_verified: bool = False

    @property
    def production_admitted(self) -> bool:
        return all(asdict(self).values())


@dataclass(frozen=True)
class HermesConformanceReceipt:
    source_commit: str
    source_tree: str
    checkout_digest: str
    adapter_files: tuple[tuple[str, str], ...]
    forbidden_imports: tuple[str, ...]
    evidence: HermesAdmissionEvidence
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "checkout_digest": self.checkout_digest,
            "adapter_files": [list(item) for item in self.adapter_files],
            "forbidden_imports": list(self.forbidden_imports),
            "evidence": asdict(self.evidence),
            "production_admitted": self.evidence.production_admitted,
            "digest": self.digest,
        }


def scan_forbidden_imports(root: str | Path) -> tuple[str, ...]:
    root_path = Path(root).resolve(strict=True)
    findings: set[str] = set()
    for path in sorted(root_path.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if any(name == forbidden or name.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_DIRECT_IMPORTS):
                    findings.add(f"{path.name}:{name}")
    return tuple(sorted(findings))


def build_conformance_receipt(
    *,
    checkout_root: str | Path,
    adapter_root: str | Path | None = None,
    source: HermesPinnedSource = DEFAULT_HERMES_SOURCE,
    evidence: HermesAdmissionEvidence = HermesAdmissionEvidence(),
    git_executable: str = "git",
) -> HermesConformanceReceipt:
    checkout = verify_hermes_checkout(checkout_root, source=source, git_executable=git_executable)
    root = Path(adapter_root or Path(__file__).parent).resolve(strict=True)
    forbidden = scan_forbidden_imports(root)
    if forbidden:
        raise HermesConformanceError("Hermes adapter directly imports a model/network client")
    files = tuple((path.name, file_sha256(path)) for path in sorted(root.glob("*.py")))
    payload = {
        "source_commit": checkout.commit,
        "source_tree": checkout.tree,
        "checkout_digest": checkout.digest,
        "adapter_files": files,
        "forbidden_imports": forbidden,
        "evidence": asdict(evidence),
    }
    return HermesConformanceReceipt(
        source_commit=checkout.commit,
        source_tree=checkout.tree,
        checkout_digest=checkout.digest,
        adapter_files=files,
        forbidden_imports=forbidden,
        evidence=evidence,
        digest=canonical_sha256(payload),
    )
