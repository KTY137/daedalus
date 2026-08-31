#!/usr/bin/env python3
"""Check the deterministic, tracked-only Work Packet registry.

The checker deliberately does not shell out to Git.  A subprocess would make
this governance check a new ``PROCESS_SPAWN`` entrypoint and would change the
canonical Effect Registry merely to enumerate files.  Instead, the narrow
reader below accepts the SHA-1 Git index formats used by this repository
(DIRC v2/v3), refuses split/sparse/conflicted or changing indices, and returns
only stage-zero tracked paths.  Untracked files are therefore invisible.

Usage:
    python tools/index_work_packets.py --check
    python tools/index_work_packets.py --render  # canonical JSON on stdout
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = "docs/work-packets/index.json"
PACKET_PREFIX = "docs/work-packets/"
SCHEMA_PATH = "configs/schemas/work-packet-index-v1.schema.json"

LEGACY_BASE_REVISION = "151b8d180e321cfba48b4c7d62f9be56579d52a5"
LEGACY_PATH_COUNT = 204
LEGACY_PATHS_SHA256 = (
    "9b657c0b81e8ce37812af1e3649429dc850528f2f0936de687662a6c9ebc1775"
)
MASTER_PLAN_REVISION = 11
ACTIVE_GATE = 1
MASTER_PLAN_SHA256 = (
    "711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2"
)
MASTER_PLAN_PATH = "docs/IKARUS_ARIADNE_MASTER_PLAN.md"

UNKNOWN = "unknown"
ALLOWED_FORMATS = {".json": "json", ".md": "markdown"}
ALLOWED_ROLES = {"primary", "companion"}
ALLOWED_CLASSIFICATIONS = {"ALIGNED", "AMENDMENT", "EXPERIMENT"}
REQUIRED_METADATA = (
    "active_gate",
    "classification",
    "owner",
    "base_revision",
    "dependencies",
)
REQUIRED_SECTIONS = (
    "primary_acceptance_claim",
    "scope",
    "contracts_and_behavior",
    "acceptance_matrix",
    "migration_and_rollback",
    "evidence_expected_failures_and_review",
)

# Packet IDs end at the first numeric packet component.  Upper-case segments
# before it are part of the ID, so both G0-RTC-06Y and
# G1-DESKTOP-STARTUP-NONCE-270 are retained without treating the descriptive
# filename suffix as identity.
PACKET_ID_RE = re.compile(r"^(G\d+(?:-[A-Z][A-Z0-9]*)+-\d+[A-Z0-9]*)")
SHA1_HEX_RE = re.compile(r"^[0-9a-f]{40}$")


class IndexError(RuntimeError):
    """The registry or Git index could not be measured safely."""


def _git_dir(repo_root: Path) -> Path:
    marker = repo_root / ".git"
    if marker.is_dir():
        return marker.resolve()
    try:
        line = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise IndexError(f"cannot read Git metadata pointer {marker}: {exc}") from exc
    prefix = "gitdir:"
    if not line.lower().startswith(prefix):
        raise IndexError(f"invalid Git metadata pointer in {marker}")
    target = Path(line[len(prefix) :].strip())
    if not target.is_absolute():
        target = marker.parent / target
    return target.resolve()


def _read_stable_bytes(path: Path) -> bytes:
    lock_path = path.with_name(path.name + ".lock")
    if lock_path.exists():
        raise IndexError(f"Git index is being updated: {lock_path}")
    try:
        before = path.stat()
        payload = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise IndexError(f"cannot read Git index {path}: {exc}") from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or len(payload) != after.st_size:
        raise IndexError(f"Git index changed while it was being read: {path}")
    if lock_path.exists():
        raise IndexError(f"Git index update began while reading: {lock_path}")
    return payload


def _parse_extensions(data: bytes, offset: int, checksum_offset: int) -> None:
    while offset < checksum_offset:
        if offset + 8 > checksum_offset:
            raise IndexError("truncated Git index extension header")
        signature = data[offset : offset + 4]
        size = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        offset += 8
        if offset + size > checksum_offset:
            raise IndexError("truncated Git index extension payload")
        try:
            name = signature.decode("ascii")
        except UnicodeDecodeError as exc:
            raise IndexError("non-ASCII Git index extension signature") from exc
        if name in {"link", "sdir"}:
            raise IndexError(f"unsupported split/sparse Git index extension: {name}")
        # Lower-case initial bytes identify extensions Git requires readers to
        # understand.  Unknown optional (upper-case) extensions are length
        # delimited and can be skipped without changing the path census.
        if name and name[0].islower():
            raise IndexError(f"unsupported mandatory Git index extension: {name}")
        offset += size
    if offset != checksum_offset:
        raise IndexError("invalid Git index extension boundary")


def parse_git_index(data: bytes) -> tuple[str, ...]:
    """Return sorted stage-zero paths from a complete SHA-1 DIRC v2/v3 index."""

    if len(data) < 32 or data[:4] != b"DIRC":
        raise IndexError("Git index signature is not DIRC")
    version, entry_count = struct.unpack(">II", data[4:12])
    if version not in {2, 3}:
        raise IndexError(f"unsupported Git index version: {version}")
    checksum_offset = len(data) - 20
    expected_checksum = data[checksum_offset:]
    observed_checksum = hashlib.sha1(data[:checksum_offset]).digest()
    if observed_checksum != expected_checksum:
        raise IndexError("Git index SHA-1 checksum mismatch")

    offset = 12
    paths: list[str] = []
    seen: set[str] = set()
    for _ in range(entry_count):
        entry_start = offset
        if offset + 62 > checksum_offset:
            raise IndexError("truncated Git index entry")
        mode = struct.unpack(">I", data[offset + 24 : offset + 28])[0]
        flags = struct.unpack(">H", data[offset + 60 : offset + 62])[0]
        offset += 62
        if mode == 0o040000:
            raise IndexError("sparse directory entry is unsupported")
        if flags & 0x4000:
            if version != 3 or offset + 2 > checksum_offset:
                raise IndexError("invalid extended Git index flags")
            offset += 2
        stage = (flags & 0x3000) >> 12
        if stage != 0:
            raise IndexError("conflicted Git index stages are unsupported")
        try:
            name_end = data.index(b"\0", offset, checksum_offset)
        except ValueError as exc:
            raise IndexError("unterminated Git index path") from exc
        raw_path = data[offset:name_end]
        encoded_length = flags & 0x0FFF
        if encoded_length != 0x0FFF and encoded_length != len(raw_path):
            raise IndexError("Git index path length does not match entry flags")
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IndexError("Git index path is not valid UTF-8") from exc
        if not path or "\\" in path or path.startswith("/"):
            raise IndexError(f"invalid repository-relative Git index path: {path!r}")
        if path in seen:
            raise IndexError(f"duplicate stage-zero Git index path: {path}")
        seen.add(path)
        paths.append(path)
        offset = name_end + 1
        padding = (8 - ((offset - entry_start) % 8)) % 8
        if offset + padding > checksum_offset:
            raise IndexError("truncated Git index entry padding")
        if any(data[offset : offset + padding]):
            raise IndexError("non-zero Git index entry padding")
        offset += padding

    _parse_extensions(data, offset, checksum_offset)
    return tuple(sorted(paths))


def tracked_paths(repo_root: Path) -> tuple[str, ...]:
    index_path = _git_dir(repo_root) / "index"
    return parse_git_index(_read_stable_bytes(index_path))


def _paths_digest(paths: Iterable[str]) -> str:
    payload = "".join(f"{path}\n" for path in paths).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_master_plan(repo_root: Path) -> None:
    try:
        payload = (repo_root / MASTER_PLAN_PATH).read_bytes()
    except OSError as exc:
        raise IndexError(f"cannot read Master Plan authority: {exc}") from exc
    observed = hashlib.sha256(payload).hexdigest()
    if observed != MASTER_PLAN_SHA256:
        raise IndexError(
            f"Master Plan authority drifted from Revision {MASTER_PLAN_REVISION}: {observed}"
        )


def canonical_packet_id(value: str) -> str:
    match = PACKET_ID_RE.match(value.strip())
    return match.group(1) if match else UNKNOWN


def _clean_markdown_value(value: str) -> str:
    value = value.strip().rstrip("  ")
    while len(value) >= 2 and (
        (value.startswith("`") and value.endswith("`"))
        or (value.startswith("**") and value.endswith("**"))
    ):
        value = value[1:-1].strip() if value.startswith("`") else value[2:-2].strip()
    return value or UNKNOWN


def _metadata_value(value: Any) -> str | int:
    if value is None or value == "":
        return UNKNOWN
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _clean_markdown_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _empty_metadata() -> dict[str, str]:
    return {name: UNKNOWN for name in REQUIRED_METADATA}


LABEL_ALIASES = {
    "packet id": "packet_id",
    "work packet id": "packet_id",
    "artifact role": "artifact_role",
    "active gate": "active_gate",
    "gate": "active_gate",
    "iron gate": "active_gate",
    "target gate": "active_gate",
    "classification": "classification",
    "owner": "owner",
    "base revision": "base_revision",
    "exact base revision": "base_revision",
    "dependencies": "dependencies",
}
LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?([A-Za-z ]+?)(?::\*\*|\*\*:|:)\s*(.*?)\s*$"
)


def _normalize_gate(value: str | int) -> str | int:
    if isinstance(value, int):
        return value
    match = re.fullmatch(r"(?:Gate\s+)?(\d+)(?:\s+[-\N{EM DASH}].*)?", value, re.IGNORECASE)
    return int(match.group(1)) if match else value


def _markdown_contract(text: str) -> tuple[str, str, dict[str, str | int], tuple[str, ...]]:
    values: dict[str, str] = {}
    for line in text.splitlines()[:80]:
        match = LABEL_RE.match(line)
        if not match:
            continue
        key = LABEL_ALIASES.get(match.group(1).strip().lower())
        if key and key not in values:
            values[key] = _clean_markdown_value(match.group(2))

    metadata: dict[str, str | int] = _empty_metadata()
    for field in REQUIRED_METADATA:
        if field in values:
            metadata[field] = _metadata_value(values[field])
    metadata["active_gate"] = _normalize_gate(metadata["active_gate"])

    headings = {
        re.sub(r"[^a-z0-9]+", "_", line.lstrip("# ").lower()).strip("_")
        for line in text.splitlines()
        if line.startswith("## ")
    }
    section_aliases = {
        "primary_acceptance_claim": {"primary_acceptance_claim"},
        "scope": {"scope", "frozen_scope"},
        "contracts_and_behavior": {"contracts_and_behavior", "behavior_and_compatibility_contract"},
        "acceptance_matrix": {"acceptance_matrix", "deterministic_acceptance_and_evidence"},
        "migration_and_rollback": {"migration_and_rollback", "rollback_and_review_questions"},
        "evidence_expected_failures_and_review": {
            "evidence_expected_failures_and_review",
            "budget_expected_failures_and_stop_rule",
        },
    }
    sections = tuple(
        section
        for section in REQUIRED_SECTIONS
        if headings.intersection(section_aliases[section])
    )
    return (
        values.get("packet_id", UNKNOWN),
        values.get("artifact_role", UNKNOWN).lower(),
        metadata,
        sections,
    )


def _json_contract(
    payload: Mapping[str, Any],
) -> tuple[str, str, dict[str, str | int], tuple[str, ...]]:
    declared_id: Any = UNKNOWN
    for key in ("work_packet_id", "work_packet", "packet_id"):
        if key in payload:
            declared_id = payload[key]
            break
    role = _metadata_value(payload.get("artifact_role", UNKNOWN))
    metadata: dict[str, str | int] = _empty_metadata()
    aliases = {
        "active_gate": ("active_gate", "gate"),
        "classification": ("classification",),
        "owner": ("owner",),
        "base_revision": ("base_revision", "exact_base_revision"),
        "dependencies": ("dependencies",),
    }
    for field, keys in aliases.items():
        for key in keys:
            if key in payload:
                metadata[field] = _metadata_value(payload[key])
                break
    metadata["active_gate"] = _normalize_gate(metadata["active_gate"])
    section_keys = {
        "primary_acceptance_claim": {"primary_claim", "primary_acceptance_claim"},
        "scope": {"scope"},
        "contracts_and_behavior": {"contracts", "behavior", "compatibility"},
        "acceptance_matrix": {"acceptance", "acceptance_matrix"},
        "migration_and_rollback": {"migration", "rollback"},
        "evidence_expected_failures_and_review": {
            "evidence",
            "expected_failures",
            "review_questions",
        },
    }
    sections = tuple(
        section for section in REQUIRED_SECTIONS if section_keys[section].intersection(payload)
    )
    return str(declared_id), str(role).lower(), metadata, sections


def _artifact(repo_root: Path, relpath: str, legacy_paths: set[str]) -> dict[str, Any]:
    path = repo_root / relpath
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise IndexError(f"tracked Work Packet artifact is unreadable: {relpath}: {exc}") from exc
    suffix = path.suffix.lower()
    artifact_format = ALLOWED_FORMATS.get(suffix)
    if artifact_format is None:
        raise IndexError(f"unsupported tracked Work Packet artifact format: {relpath}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IndexError(f"Work Packet artifact is not UTF-8: {relpath}") from exc
    if artifact_format == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise IndexError(f"invalid Work Packet JSON {relpath}: {exc}") from exc
        if not isinstance(payload, dict):
            raise IndexError(f"Work Packet JSON root must be an object: {relpath}")
        declared_id, role, metadata, sections = _json_contract(payload)
    else:
        declared_id, role, metadata, sections = _markdown_contract(text)

    filename_id = canonical_packet_id(path.stem)
    declared_canonical = canonical_packet_id(declared_id)
    origin = "legacy" if relpath in legacy_paths else "post_index"
    artifact = {
        "artifact_role": role if role in ALLOWED_ROLES else UNKNOWN,
        "declared_packet_id": declared_id if declared_canonical != UNKNOWN else UNKNOWN,
        "format": artifact_format,
        "metadata": metadata,
        "origin": origin,
        "path": relpath,
        "sections": list(sections),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if origin == "post_index":
        _validate_new_artifact(artifact, filename_id, declared_canonical)
    return artifact


def _validate_new_artifact(
    artifact: Mapping[str, Any], filename_id: str, declared_canonical: str
) -> None:
    path = str(artifact["path"])
    if filename_id == UNKNOWN or declared_canonical == UNKNOWN:
        raise IndexError(f"new Work Packet artifact lacks a canonical explicit ID: {path}")
    if filename_id != declared_canonical:
        raise IndexError(
            f"new Work Packet artifact ID disagrees with filename: {path}: "
            f"{declared_canonical} != {filename_id}"
        )
    if artifact.get("declared_packet_id") != declared_canonical:
        raise IndexError(f"new Work Packet artifact must declare the canonical ID exactly: {path}")
    role = artifact["artifact_role"]
    if role not in ALLOWED_ROLES:
        raise IndexError(f"new Work Packet artifact lacks artifact_role: {path}")
    if role != "primary":
        return
    metadata = artifact["metadata"]
    missing = [field for field in REQUIRED_METADATA if metadata[field] == UNKNOWN]
    if missing:
        raise IndexError(
            f"new primary Work Packet metadata is incomplete "
            f"({', '.join(missing)}): {path}"
        )
    if not isinstance(metadata["active_gate"], int) or metadata["active_gate"] < 0:
        raise IndexError(f"new primary Work Packet active_gate must be an integer: {path}")
    if metadata["classification"] not in ALLOWED_CLASSIFICATIONS:
        raise IndexError(f"new primary Work Packet classification is invalid: {path}")
    if not isinstance(metadata["base_revision"], str) or not SHA1_HEX_RE.fullmatch(
        metadata["base_revision"]
    ):
        raise IndexError(f"new primary Work Packet base_revision must be a full SHA-1: {path}")
    missing_sections = sorted(set(REQUIRED_SECTIONS) - set(artifact["sections"]))
    if missing_sections:
        raise IndexError(
            f"new primary Work Packet is missing contract sections "
            f"({', '.join(missing_sections)}): {path}"
        )


def _merged_metadata(
    artifacts: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    merged: dict[str, Any] = {}
    conflicts: dict[str, list[Any]] = {}
    artifacts = tuple(artifacts)
    for field in REQUIRED_METADATA:
        values: list[Any] = []
        for artifact in artifacts:
            value = artifact["metadata"][field]
            if value != UNKNOWN and value not in values:
                values.append(value)
        if len(values) == 1:
            merged[field] = values[0]
        else:
            merged[field] = UNKNOWN
            if len(values) > 1:
                conflicts[field] = sorted(
                    values, key=lambda value: json.dumps(value, sort_keys=True)
                )
    return merged, conflicts


def _validate_artifact_groups(packets: Iterable[Mapping[str, Any]]) -> None:
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for packet in packets:
        packet_id = str(packet["packet_id"])
        if packet_id in seen_ids:
            raise IndexError(f"duplicate packet group ID: {packet_id}")
        seen_ids.add(packet_id)
        artifacts = packet["artifacts"]
        for artifact in artifacts:
            path = str(artifact["path"])
            if path in seen_paths:
                raise IndexError(f"artifact is assigned more than once: {path}")
            seen_paths.add(path)
        legacy = [a for a in artifacts if a["origin"] == "legacy"]
        new_primary = [
            a for a in artifacts if a["origin"] == "post_index" and a["artifact_role"] == "primary"
        ]
        if legacy and new_primary:
            raise IndexError(f"new primary artifact redefines legacy packet ID: {packet_id}")
        if not legacy and len(new_primary) != 1:
            raise IndexError(
                f"new packet ID must have exactly one primary artifact: {packet_id} "
                f"(found {len(new_primary)})"
            )


def _validate_legacy_baseline(index: Mapping[str, Any]) -> tuple[str, ...]:
    baseline = index.get("legacy_baseline")
    if not isinstance(baseline, dict):
        raise IndexError("registry has no legacy_baseline object")
    paths = baseline.get("paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise IndexError("legacy_baseline.paths must be a string array")
    normalized = tuple(sorted(paths))
    if len(normalized) != len(set(normalized)):
        raise IndexError("legacy_baseline.paths contains duplicates")
    if baseline.get("revision") != LEGACY_BASE_REVISION:
        raise IndexError("legacy baseline revision changed")
    if len(normalized) != LEGACY_PATH_COUNT or baseline.get("path_count") != LEGACY_PATH_COUNT:
        raise IndexError("legacy baseline path count changed")
    digest = _paths_digest(normalized)
    if digest != LEGACY_PATHS_SHA256 or baseline.get("paths_sha256") != digest:
        raise IndexError("legacy baseline path set changed")
    return normalized


def build_index(repo_root: Path, current_index: Mapping[str, Any]) -> dict[str, Any]:
    _verify_master_plan(repo_root)
    legacy_paths = _validate_legacy_baseline(current_index)
    tracked = tracked_paths(repo_root)
    work_packet_paths = tuple(path for path in tracked if path.startswith(PACKET_PREFIX))
    if INDEX_PATH not in work_packet_paths:
        raise IndexError(f"registry itself is not tracked: {INDEX_PATH}")
    missing_legacy = sorted(set(legacy_paths) - set(work_packet_paths))
    if missing_legacy:
        raise IndexError(
            "tracked legacy Work Packet artifacts were removed or moved: "
            + ", ".join(missing_legacy[:10])
        )

    artifacts: list[dict[str, Any]] = []
    legacy_set = set(legacy_paths)
    for relpath in work_packet_paths:
        if relpath == INDEX_PATH:
            continue
        artifacts.append(_artifact(repo_root, relpath, legacy_set))

    groups: dict[str, list[dict[str, Any]]] = {}
    unassigned: list[dict[str, Any]] = []
    for artifact in artifacts:
        packet_id = canonical_packet_id(Path(artifact["path"]).stem)
        if packet_id == UNKNOWN:
            unassigned.append(artifact)
        else:
            groups.setdefault(packet_id, []).append(artifact)

    packets: list[dict[str, Any]] = []
    artifact_groups: list[dict[str, Any]] = []
    for packet_id, packet_artifacts in sorted(groups.items()):
        packet_artifacts.sort(key=lambda item: item["path"])
        metadata, conflicts = _merged_metadata(packet_artifacts)
        origins = {artifact["origin"] for artifact in packet_artifacts}
        primaries = [
            artifact["path"]
            for artifact in packet_artifacts
            if artifact["artifact_role"] == "primary"
        ]
        artifact_group = {
            "artifacts": packet_artifacts,
            "packet_id": packet_id,
        }
        artifact_groups.append(artifact_group)
        packet = {
            "artifacts": [artifact["path"] for artifact in packet_artifacts],
            "metadata": metadata,
            "metadata_conflicts": conflicts,
            "origin": next(iter(origins)) if len(origins) == 1 else "mixed",
            "packet_id": packet_id,
            "primary_artifact": primaries[0] if len(primaries) == 1 else UNKNOWN,
        }
        packets.append(packet)
    _validate_artifact_groups(artifact_groups)

    unassigned.sort(key=lambda item: item["path"])
    legacy_artifacts = sum(a["origin"] == "legacy" for a in artifacts)
    post_index_artifacts = len(artifacts) - legacy_artifacts
    assigned_artifacts = sum(len(packet["artifacts"]) for packet in packets)
    post_index_contracts = [
        {
            "artifact_role": artifact["artifact_role"],
            "format": artifact["format"],
            "packet_id": canonical_packet_id(Path(artifact["path"]).stem),
            "path": artifact["path"],
            "sections": artifact["sections"],
        }
        for artifact in artifacts
        if artifact["origin"] == "post_index"
    ]
    post_index_contracts.sort(key=lambda item: item["path"])
    result = {
        "$schema": "../../configs/schemas/work-packet-index-v1.schema.json",
        "authority": {
            "active_gate": ACTIVE_GATE,
            "automatic_merge": False,
            "automatic_promotion": False,
            "classification": "ALIGNED",
            "master_plan_revision": MASTER_PLAN_REVISION,
            "master_plan_sha256": MASTER_PLAN_SHA256,
        },
        "counts": {
            "assigned_artifacts": assigned_artifacts,
            "legacy_artifacts": legacy_artifacts,
            "packet_artifacts": len(artifacts),
            "packet_ids": len(packets),
            "post_index_artifacts": post_index_artifacts,
            "registry_artifacts": 1,
            "tracked_files": len(work_packet_paths),
            "unassigned_artifacts": len(unassigned),
        },
        "legacy_baseline": {
            "path_count": LEGACY_PATH_COUNT,
            "paths": list(legacy_paths),
            "paths_sha256": LEGACY_PATHS_SHA256,
            "revision": LEGACY_BASE_REVISION,
        },
        "packets": packets,
        "post_index_contracts": post_index_contracts,
        "registry_artifacts": [INDEX_PATH],
        "schema": "daedalus-work-packet-index/1",
        "unassigned_artifacts": [artifact["path"] for artifact in unassigned],
    }
    _validate_registry(result)
    return result


def _validate_registry(index: Mapping[str, Any]) -> None:
    packets = index.get("packets")
    if not isinstance(packets, list):
        raise IndexError("registry packets must be an array")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for packet in packets:
        if not isinstance(packet, dict):
            raise IndexError("registry packet entries must be objects")
        packet_id = packet.get("packet_id")
        if not isinstance(packet_id, str) or canonical_packet_id(packet_id) != packet_id:
            raise IndexError(f"invalid registry packet ID: {packet_id!r}")
        if packet_id in seen_ids:
            raise IndexError(f"duplicate packet group ID: {packet_id}")
        seen_ids.add(packet_id)
        artifact_paths = packet.get("artifacts")
        if not isinstance(artifact_paths, list) or not artifact_paths:
            raise IndexError(f"packet has no artifact paths: {packet_id}")
        for path in artifact_paths:
            if not isinstance(path, str) or path in seen_paths:
                raise IndexError(f"duplicate or invalid artifact path: {path!r}")
            if canonical_packet_id(Path(path).stem) != packet_id:
                raise IndexError(f"artifact path is assigned to the wrong packet ID: {path}")
            seen_paths.add(path)
    counts = index.get("counts")
    if not isinstance(counts, dict):
        raise IndexError("registry counts must be an object")
    assigned = sum(len(packet["artifacts"]) for packet in packets)
    unassigned = index.get("unassigned_artifacts")
    if not isinstance(unassigned, list) or not all(isinstance(path, str) for path in unassigned):
        raise IndexError("unassigned_artifacts must be an array")
    if len(unassigned) != len(set(unassigned)) or seen_paths.intersection(unassigned):
        raise IndexError("unassigned artifact paths are duplicated or assigned")
    post_index_contracts = index.get("post_index_contracts")
    if not isinstance(post_index_contracts, list):
        raise IndexError("post_index_contracts must be an array")
    legacy_paths = set(_validate_legacy_baseline(index))
    all_artifacts = seen_paths.union(unassigned)
    legacy_count = len(all_artifacts.intersection(legacy_paths))
    post_index_count = len(all_artifacts - legacy_paths)
    expected = {
        "assigned_artifacts": assigned,
        "legacy_artifacts": legacy_count,
        "packet_artifacts": assigned + len(unassigned),
        "packet_ids": len(packets),
        "post_index_artifacts": post_index_count,
        "registry_artifacts": len(index.get("registry_artifacts", [])),
        "tracked_files": assigned + len(unassigned) + len(index.get("registry_artifacts", [])),
        "unassigned_artifacts": len(unassigned),
    }
    if counts != expected:
        raise IndexError(f"registry counts disagree with contents: {counts!r} != {expected!r}")


def canonical_json(payload: Mapping[str, Any]) -> str:
    # ASCII escapes keep the generated registry byte-identical across Windows
    # console/code-page settings even when a legacy document contains Unicode.
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def load_index(repo_root: Path) -> dict[str, Any]:
    path = repo_root / INDEX_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexError(f"cannot read Work Packet registry {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise IndexError("Work Packet registry root must be an object")
    return payload


def check(repo_root: Path) -> tuple[bool, str]:
    current = load_index(repo_root)
    expected = build_index(repo_root, current)
    expected_text = canonical_json(expected)
    current_text = (repo_root / INDEX_PATH).read_text(encoding="utf-8")
    if current_text != expected_text:
        return False, "Work Packet registry is stale or not canonically formatted"
    counts = expected["counts"]
    return True, (
        "Work Packet registry clean: "
        f"{counts['tracked_files']} tracked files, "
        f"{counts['packet_ids']} packet IDs, "
        f"{counts['unassigned_artifacts']} unassigned legacy artifacts"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify the committed registry")
    mode.add_argument("--render", action="store_true", help="print canonical registry JSON")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        if args.render:
            print(canonical_json(build_index(repo_root, load_index(repo_root))), end="")
            return 0
        clean, message = check(repo_root)
    except IndexError as exc:
        print(f"COULD NOT MEASURE: {exc}", file=sys.stderr)
        return 2
    print(message, file=sys.stderr if not clean else sys.stdout)
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
