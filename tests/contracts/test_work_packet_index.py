from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from daedalus.spine.effect_boundary import registry_sha256
from tools import index_work_packets as subject


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / subject.SCHEMA_PATH
INDEX_PATH = ROOT / subject.INDEX_PATH
# Moved 2026-09-03: the registry gained the ``daedalus.hooks.crosstalk`` row
# (network_egress + process_spawn) and ``daedalus.hooks`` had its notes
# corrected, because its declared egress is no longer loopback-only.
FROZEN_EFFECT_REGISTRY_SHA256 = (
    "44222aa9f9269eb1c9d9f5cf118786cbb1a1d602f6f3ca77aeb00d4f599214c9"
)


def _entry(
    path: str,
    *,
    version: int = 2,
    stage: int = 0,
    extended: bool = False,
    mode: int = 0o100644,
) -> bytes:
    raw = path.encode("utf-8")
    flags = min(len(raw), 0x0FFF) | (stage << 12)
    if extended:
        flags |= 0x4000
    stat = struct.pack(">10I", 0, 0, 0, 0, 0, 0, mode, 0, 0, 0)
    body = stat + (b"o" * 20) + struct.pack(">H", flags)
    if extended:
        assert version == 3
        body += b"\0\0"
    body += raw + b"\0"
    body += b"\0" * ((8 - (len(body) % 8)) % 8)
    return body


def _git_index(
    paths: tuple[str, ...] = ("b.txt", "a.txt"),
    *,
    version: int = 2,
    stage: int = 0,
    extended: bool = False,
    mode: int = 0o100644,
    extensions: tuple[tuple[bytes, bytes], ...] = (),
) -> bytes:
    entries = b"".join(
        _entry(
            path,
            version=version,
            stage=stage,
            extended=extended,
            mode=mode,
        )
        for path in paths
    )
    extension_bytes = b"".join(
        signature + struct.pack(">I", len(payload)) + payload
        for signature, payload in extensions
    )
    payload = b"DIRC" + struct.pack(">II", version, len(paths)) + entries + extension_bytes
    return payload + hashlib.sha1(payload).digest()


def _schema() -> dict[str, object]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def _index() -> dict[str, object]:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("version", "extended"),
    ((2, False), (3, False), (3, True)),
)
def test_git_index_reader_accepts_supported_stage_zero_formats(
    version: int, extended: bool
) -> None:
    payload = _git_index(
        version=version,
        extended=extended,
        extensions=((b"TREE", b"bounded optional payload"),),
    )

    assert subject.parse_git_index(payload) == ("a.txt", "b.txt")


@pytest.mark.parametrize(
    "payload,match",
    (
        (b"NOPE" + _git_index()[4:], "signature"),
        (_git_index(version=4), "version"),
        (_git_index(stage=1), "conflicted"),
        (_git_index(mode=0o040000), "sparse directory"),
        (_git_index(extensions=((b"link", b"split"),)), "split/sparse"),
        (_git_index(extensions=((b"sdir", b"sparse"),)), "split/sparse"),
        (_git_index(extensions=((b"abcd", b"required"),)), "mandatory"),
    ),
)
def test_git_index_reader_refuses_unsupported_or_ambiguous_state(
    payload: bytes, match: str
) -> None:
    with pytest.raises(subject.IndexError, match=match):
        subject.parse_git_index(payload)


def test_git_index_reader_refuses_corruption() -> None:
    corrupt_checksum = bytearray(_git_index())
    corrupt_checksum[-1] ^= 1
    with pytest.raises(subject.IndexError, match="checksum"):
        subject.parse_git_index(bytes(corrupt_checksum))

    truncated = _git_index()[:-25]
    with pytest.raises(subject.IndexError):
        subject.parse_git_index(truncated)


def test_linked_worktree_reader_ignores_untracked_files_and_refuses_lock(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    metadata = tmp_path / "metadata"
    packet_dir = repo / "docs" / "work-packets"
    packet_dir.mkdir(parents=True)
    metadata.mkdir()
    tracked = (
        "docs/work-packets/G9-TEST-01_PRIMARY.md",
        "docs/work-packets/index.json",
    )
    (repo / ".git").write_text(f"gitdir: {metadata.as_posix()}\n", encoding="utf-8")
    (metadata / "index").write_bytes(_git_index(tracked))
    (packet_dir / "G9-TEST-01_PRIMARY.md").write_text("tracked", encoding="utf-8")
    (packet_dir / "UNTRACKED.md").write_text("not in the index", encoding="utf-8")

    assert subject.tracked_paths(repo) == tuple(sorted(tracked))

    (metadata / "index.lock").write_bytes(b"locked")
    with pytest.raises(subject.IndexError, match="being updated"):
        subject.tracked_paths(repo)


def test_git_index_reader_refuses_a_file_that_changes_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_path = tmp_path / "index"
    index_path.write_bytes(_git_index())
    real_stat = Path.stat
    target_calls = 0

    def changing_stat(path: Path, *args: object, **kwargs: object) -> object:
        nonlocal target_calls
        observed = real_stat(path, *args, **kwargs)
        if path == index_path:
            target_calls += 1
            if target_calls == 2:
                return SimpleNamespace(
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino,
                    st_size=observed.st_size,
                    st_mtime_ns=observed.st_mtime_ns + 1,
                )
        return observed

    monkeypatch.setattr(Path, "stat", changing_stat)
    with pytest.raises(subject.IndexError, match="changed while"):
        subject._read_stable_bytes(index_path)


def test_committed_registry_validates_and_matches_the_tracked_index() -> None:
    payload = _index()
    Draft202012Validator(_schema()).validate(payload)

    clean, message = subject.check(ROOT)
    assert clean is True
    # Moving census: every packet that adds a Work Packet document changes
    # these totals. Re-measure them with `tools/index_work_packets.py --render`
    # in the packet that moves them. The invariants that must not weaken are
    # the frozen legacy baseline below and the post-index metadata completeness
    # asserted in test_post_index_packet_contracts_are_unique_complete_and_revision_bound.
    assert "283 tracked files" in message
    # +1 across the board in G1-SCC-02, which adds one planned primary packet
    # document and nothing else. A moving census, not an invariant:
    # re-measure it in the packet that adds or retires an artifact.
    assert payload["counts"] == {
        "assigned_artifacts": 280,
        "legacy_artifacts": 204,
        "packet_artifacts": 282,
        "packet_ids": 217,
        "post_index_artifacts": 78,
        "registry_artifacts": 1,
        "tracked_files": 283,
        "unassigned_artifacts": 2,
    }
    assert len(payload["legacy_baseline"]["paths"]) == 204
    assert payload["legacy_baseline"]["paths_sha256"] == subject.LEGACY_PATHS_SHA256


def test_checker_binds_the_exact_master_plan_authority(tmp_path: Path) -> None:
    subject._verify_master_plan(ROOT)
    plan = tmp_path / subject.MASTER_PLAN_PATH
    plan.parent.mkdir(parents=True)
    plan.write_text("not Revision 11\n", encoding="utf-8")

    with pytest.raises(subject.IndexError, match="authority drifted"):
        subject._verify_master_plan(tmp_path)


def test_registry_groups_companion_artifacts_instead_of_calling_them_conflicts() -> None:
    packets = {packet["packet_id"]: packet for packet in _index()["packets"]}

    assert len(packets["G0-FLT-07A"]["artifacts"]) == 3
    assert len(packets["G0-RTC-06Y"]["artifacts"]) == 4
    assert len(packets["G0-RTC-07C"]["artifacts"]) == 4
    assert len(packets["G0-RTC-07D"]["artifacts"]) == 4
    assert len(packets) == len({packet["packet_id"] for packet in packets.values()})


def test_legacy_unknowns_and_unassigned_artifacts_remain_explicit() -> None:
    payload = _index()
    packets = {packet["packet_id"]: packet for packet in payload["packets"]}

    assert packets["G0-APR-11"]["metadata"] == {
        "active_gate": "unknown",
        "base_revision": "unknown",
        "classification": "unknown",
        "dependencies": "unknown",
        "owner": "unknown",
    }
    assert packets["G1-WP-01"]["primary_artifact"] == "unknown"
    assert payload["unassigned_artifacts"] == [
        "docs/work-packets/G0-OPUS-FLEET-ADVISORY-EXPERIMENT.md",
        "docs/work-packets/G1_ACTIVATION_CHECKLIST.md",
    ]


def test_post_index_packet_contracts_are_unique_complete_and_revision_bound() -> None:
    payload = _index()
    packets = {packet["packet_id"]: packet for packet in payload["packets"]}
    expected_primary_ids = {
        "G1-ENV-01",
        "G1-GATE-01",
        "G1-HERMES-01",
        "G1-HIER-01",
        "G1-HIER-02",
        "G1-HIER-02A",
        "G1-HIER-02B",
        "G1-HIER-03A",
        "G1-HIER-03B",
        "G1-HIER-03C",
        "G1-HIER-03D",
        "G1-HIER-04",
        "G1-HIER-04B",
        "G1-HIER-05",
        "G1-HIER-06A",
        "G1-HIER-06B",
        "G1-HIER-06C",
        "G1-HIER-06D",
        "G1-HIER-06E",
        "G1-HIER-07A",
        "G1-HIER-07B",
        "G1-HIER-08",
        "G1-HIER-09",
        "G1-HIER-10",
        "G1-HIER-11",
        "G1-HIER-12",
        "G1-HIER-13",
        "G1-HIER-14",
        "G1-HIER-15",
        "G1-IDE-13",
        "G1-IFACE-BRIDGE-01",
        "G1-IFACE-BRIDGE-02",
        "G1-IFACE-BRIDGE-03",
        "G1-IFACE-BRIDGE-04",
        "G1-IFACE-BRIDGE-05",
        "G1-IFACE-BRIDGE-06A",
        "G1-IFACE-BRIDGE-06B",
        "G1-IFACE-BRIDGE-07",
        "G1-IFACE-BRIDGE-08",
        "G1-IFACE-BRIDGE-09",
        "G1-IFACE-BRIDGE-10",
        "G1-IFACE-BRIDGE-11",
        "G1-IFACE-BRIDGE-12",
        "G1-IFACE-BRIDGE-13",
        "G1-IFACE-DESKTOP-01",
        "G1-IFACE-DESKTOP-02",
        "G1-IFACE-DESKTOP-03",
        "G1-IFACE-HTTP-01",
        "G1-IFACE-HTTP-02",
        "G1-IFACE-HTTP-03",
        "G1-IKARUS-14",
        "G1-IKARUS-15",
        "G1-MUT-01",
        "G1-MUT-02A",
        "G1-MUT-02B",
        "G1-MUT-02C",
        "G1-MUT-02D",
        "G1-MUT-02E",
        "G1-MUT-02F",
        "G1-ORCH-01",
        "G1-PKG-01",
        "G1-RUNTIME-02",
        "G1-RUNTIME-03",
        "G1-RUNTIME-PROVIDER-01",
        "G1-RUNTIME-PROVIDER-02",
        "G1-RUNTIME-PROVIDER-03",
        "G1-RUNTIME-PROVIDER-04",
        "G1-RUNTIME-PROVIDER-05",
        "G1-RUNTIME-PROVIDER-06",
        "G1-UI-01",
        "G1-UI-02",
        "G1-UI-03",
        "G1-UI-04",
        "G1-UI-05",
        "G1-WEB-01",
        "G1-WP-INDEX-01",
        "G1-SCC-02",
    }
    post_index_packets = {
        packet_id: packet
        for packet_id, packet in packets.items()
        if packet["origin"] == "post_index"
    }

    assert set(post_index_packets) == expected_primary_ids
    for packet in post_index_packets.values():
        assert packet["primary_artifact"] != "unknown"
        assert "unknown" not in packet["metadata"].values()
        assert packet["metadata_conflicts"] == {}

    contracts = payload["post_index_contracts"]
    primary_contracts = [
        contract for contract in contracts
        if contract["artifact_role"] == "primary"
    ]
    companion_contracts = [
        contract for contract in contracts
        if contract["artifact_role"] == "companion"
    ]
    assert {contract["packet_id"] for contract in primary_contracts} == (
        expected_primary_ids
    )
    assert all(
        contract["sections"] == list(subject.REQUIRED_SECTIONS)
        for contract in primary_contracts
    )
    assert companion_contracts == [
        {
            "artifact_role": "companion",
            "format": "json",
            "packet_id": "G1-RUNTIME-02",
            "path": "docs/work-packets/G1-RUNTIME-02_SHIM_REGISTER.json",
            "sections": [],
        }
    ]


def test_new_primary_validation_rejects_missing_contract_and_id_drift() -> None:
    artifact = {
        "artifact_role": "primary",
        "declared_packet_id": "G1-TEST-01",
        "metadata": {
            "active_gate": 1,
            "classification": "ALIGNED",
            "owner": "repository owner",
            "base_revision": subject.LEGACY_BASE_REVISION,
            "dependencies": "frozen parent",
        },
        "path": "docs/work-packets/G1-TEST-01_PRIMARY.md",
        "sections": list(subject.REQUIRED_SECTIONS),
    }
    subject._validate_new_artifact(artifact, "G1-TEST-01", "G1-TEST-01")

    incomplete = copy.deepcopy(artifact)
    incomplete["metadata"]["owner"] = "unknown"
    with pytest.raises(subject.IndexError, match="incomplete"):
        subject._validate_new_artifact(incomplete, "G1-TEST-01", "G1-TEST-01")

    with pytest.raises(subject.IndexError, match="disagrees"):
        subject._validate_new_artifact(artifact, "G1-TEST-01", "G1-OTHER-01")

    noncanonical = copy.deepcopy(artifact)
    noncanonical["declared_packet_id"] = "G1-TEST-01_DESCRIPTIVE_SUFFIX"
    with pytest.raises(subject.IndexError, match="canonical ID exactly"):
        subject._validate_new_artifact(noncanonical, "G1-TEST-01", "G1-TEST-01")


def test_packet_group_allows_companions_but_refuses_two_new_primaries() -> None:
    primary = {
        "artifact_role": "primary",
        "origin": "post_index",
        "path": "docs/work-packets/G1-TEST-01_PRIMARY.md",
    }
    companion = {
        "artifact_role": "companion",
        "origin": "post_index",
        "path": "docs/work-packets/G1-TEST-01_RECEIPT.json",
    }
    subject._validate_artifact_groups(
        [{"packet_id": "G1-TEST-01", "artifacts": [primary, companion]}]
    )

    duplicate = copy.deepcopy(primary)
    duplicate["path"] = "docs/work-packets/G1-TEST-01_SECOND.md"
    with pytest.raises(subject.IndexError, match="exactly one primary"):
        subject._validate_artifact_groups(
            [{"packet_id": "G1-TEST-01", "artifacts": [primary, duplicate]}]
        )


def test_schema_and_tool_reject_authority_or_count_drift() -> None:
    validator = Draft202012Validator(_schema())
    payload = _index()

    changed_authority = copy.deepcopy(payload)
    changed_authority["authority"]["automatic_promotion"] = True
    with pytest.raises(ValidationError):
        validator.validate(changed_authority)

    changed_count = copy.deepcopy(payload)
    changed_count["counts"]["tracked_files"] += 1
    with pytest.raises(subject.IndexError, match="counts disagree"):
        subject._validate_registry(changed_count)


def test_check_is_read_only_and_effect_registry_digest_is_unchanged() -> None:
    git_index = subject._git_dir(ROOT) / "index"
    before = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (git_index, INDEX_PATH)
    }

    assert subject.main(["--check", "--repo-root", str(ROOT)]) == 0

    after = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (git_index, INDEX_PATH)
    }
    assert after == before
    assert registry_sha256() == FROZEN_EFFECT_REGISTRY_SHA256
