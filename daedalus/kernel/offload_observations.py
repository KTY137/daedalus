"""Canonical read-only observations for the bounded Gate-0 Ollama offload.

The records in this module grant no authority and perform no network or write
effect.  Capture binds facts obtained from the existing worktree authority,
Git's stage-0 index, stable no-follow file reads, the canonical source
fingerprint, the canonical artifact store, and raw Ollama metadata bytes.

Path checks reduce accidental aliasing and common link/reparse attacks.  They
are not an OS sandbox and do not close hostile concurrent-filesystem TOCTOU;
the eventual executor must still revalidate immediately at its effect seams.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping, Sequence

from daedalus.kairos.worktree import GitWorktreeManager
from daedalus.kernel.contracts import (
    OffloadExecutionPlan,
    _loopback_ollama_endpoint,
    _portable_target_path,
)
from daedalus.kernel.effects import EffectExecutionRequest, EffectStartResult
from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _artifact_locator,
    _identifier,
    _locator_sha256,
    _non_empty,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.source_state import SourceFingerprint
from daedalus.storage import ArtifactLocator, ArtifactStore


SOURCE_FINGERPRINT_ARTIFACT_KIND = "daedalus.source-fingerprint/1"
BASE_SOURCE_ARTIFACT_KIND = "daedalus.pinned-source-archive/1"
OLLAMA_METADATA_ARTIFACT_KIND = "daedalus.ollama-model-metadata-response/1"


class OffloadObservationError(ValueError):
    """A claimed observation disagrees with the independently read state."""


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and getattr(metadata, "st_file_attributes", 0) & marker)


def _lexical_absolute(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.normpath(os.path.abspath(os.fspath(path))))


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _path_sha256(path: Path, *, role: str) -> str:
    return canonical_sha(
        {
            "domain": "daedalus.observed-host-path/1",
            "role": role,
            "normalized_path": _path_key(path),
        }
    )


def _identity_sha256(path: Path, metadata: os.stat_result, *, role: str) -> str:
    device = getattr(metadata, "st_dev", 0)
    inode = getattr(metadata, "st_ino", 0)
    if isinstance(inode, bool) or not isinstance(inode, int) or inode < 1:
        raise OffloadObservationError(f"{role} has no usable no-follow identity")
    return canonical_sha(
        {
            "domain": "daedalus.observed-filesystem-identity/1",
            "role": role,
            "path_sha256": _path_sha256(path, role=role),
            "st_dev": device,
            "st_ino": inode,
            "file_type": stat.S_IFMT(metadata.st_mode),
        }
    )


def _lstat_real(path: Path, *, role: str, directory: bool | None = None) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise OffloadObservationError(f"{role} is unavailable: {path}") from exc
    if _is_link_or_reparse(metadata):
        raise OffloadObservationError(f"{role} must not be a link or reparse point")
    if directory is True and not stat.S_ISDIR(metadata.st_mode):
        raise OffloadObservationError(f"{role} must be a directory")
    if directory is False and not stat.S_ISREG(metadata.st_mode):
        raise OffloadObservationError(f"{role} must be a regular file")
    return metadata


def _relative_chain(root: Path, target: Path) -> tuple[Path, ...]:
    root = _lexical_absolute(root)
    target = _lexical_absolute(target)
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise OffloadObservationError(f"{target} is outside observed root {root}") from exc
    chain = [root]
    cursor = root
    for component in relative.parts:
        cursor /= component
        chain.append(cursor)
    return tuple(chain)


def _directory_chain_sha256(root: Path, target: Path, *, role: str) -> str:
    rows: list[dict[str, object]] = []
    for index, component in enumerate(_relative_chain(root, target)):
        metadata = _lstat_real(component, role=f"{role}[{index}]", directory=True)
        rows.append(
            {
                "depth": index,
                "path_sha256": _path_sha256(component, role=f"{role}[{index}]"),
                "identity_sha256": _identity_sha256(
                    component, metadata, role=f"{role}[{index}]"
                ),
            }
        )
    return canonical_sha(
        {"domain": "daedalus.observed-directory-chain/1", "role": role, "rows": rows}
    )


def _git_oid(raw: bytes, *, role: str) -> str:
    try:
        value = _git_text(raw, role=role).encode("utf-8").decode("ascii")
    except UnicodeError as exc:
        raise OffloadObservationError(f"Git returned a non-ASCII {role}") from exc
    if len(value) not in {40, 64} or any(char not in "0123456789abcdef" for char in value):
        raise OffloadObservationError(f"Git returned an invalid {role}")
    return value


def _git_text(raw: bytes, *, role: str) -> str:
    if raw.endswith(b"\r\n"):
        body = raw[:-2]
    elif raw.endswith(b"\n"):
        body = raw[:-1]
    else:
        body = raw
    try:
        value = body.decode("utf-8")
    except UnicodeError as exc:
        raise OffloadObservationError(f"Git returned non-UTF-8 {role}") from exc
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise OffloadObservationError(f"Git returned an invalid {role}")
    return value


def _stable_regular_bytes(path: Path, *, role: str) -> tuple[bytes, os.stat_result]:
    try:
        before = os.lstat(path)
        if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise OffloadObservationError(f"{role} must be a no-follow regular file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after_open = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = os.lstat(path)
    except OffloadObservationError:
        raise
    except OSError as exc:
        raise OffloadObservationError(f"{role} could not be read stably") from exc

    def signature(item: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            item.st_dev,
            item.st_ino,
            item.st_mode,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )

    if not stat.S_ISREG(opened.st_mode) or not (
        signature(before) == signature(opened) == signature(after_open) == signature(after)
    ):
        raise OffloadObservationError(f"{role} changed while it was read")
    raw = b"".join(chunks)
    if len(raw) != opened.st_size:
        raise OffloadObservationError(f"{role} byte count changed while it was read")
    return raw, opened


def _git_admin_path(workspace: Path) -> Path:
    """Parse a linked-worktree ``.git`` file without invoking Git."""

    raw, _ = _stable_regular_bytes(workspace / ".git", role="worktree .git control")
    text = _git_text(raw, role="worktree .git control")
    prefix = "gitdir: "
    if not text.startswith(prefix) or len(text) == len(prefix):
        raise OffloadObservationError("worktree .git control has no exact gitdir")
    value = text[len(prefix) :]
    if "\x00" in value or "\n" in value or "\r" in value:
        raise OffloadObservationError("worktree .git control has an invalid gitdir")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    admin = _lexical_absolute(candidate)
    _lstat_real(admin, role="Git admin directory", directory=True)
    return admin


def _common_git_dir(git_admin: Path) -> Path:
    commondir_path = git_admin / "commondir"
    try:
        os.lstat(commondir_path)
    except OSError:
        common = git_admin
    else:
        raw, _ = _stable_regular_bytes(commondir_path, role="Git commondir")
        value = _git_text(raw, role="Git commondir")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = git_admin / candidate
        common = _lexical_absolute(candidate)
    _lstat_real(common, role="Git common directory", directory=True)
    # A linked worktree admin directory must be a real descendant of its
    # common directory.  The chain read also refuses link/reparse components.
    if _path_key(common) == _path_key(git_admin):
        raise OffloadObservationError("candidate workspace must use linked-worktree Git admin")
    _directory_chain_sha256(common, git_admin, role="git-common-to-admin")
    return common


def _ref_path(common: Path, ref_name: str) -> Path:
    if not ref_name.startswith("refs/heads/"):
        raise OffloadObservationError("worktree HEAD must name a local branch")
    parts = ref_name.split("/")
    if any(part in {"", ".", ".."} for part in parts) or "\\" in ref_name:
        raise OffloadObservationError("worktree HEAD contains an unsafe ref path")
    path = common.joinpath(*parts)
    _directory_chain_sha256(common, path.parent, role="git-common-to-ref-parent")
    return path


def _packed_ref(common: Path, ref_name: str) -> str:
    raw, _ = _stable_regular_bytes(common / "packed-refs", role="Git packed refs")
    try:
        text = raw.decode("ascii", "strict")
    except UnicodeError as exc:
        raise OffloadObservationError("Git packed refs must be ASCII") from exc
    matches: list[str] = []
    for line in text.splitlines():
        if not line or line.startswith(("#", "^")):
            continue
        try:
            oid, name = line.split(" ", 1)
        except ValueError as exc:
            raise OffloadObservationError("Git packed refs contains a malformed row") from exc
        if name == ref_name:
            matches.append(_git_oid(oid.encode("ascii"), role="packed branch tip"))
    if len(matches) != 1:
        raise OffloadObservationError("Git branch must have exactly one observable ref")
    return matches[0]


def _head_branch_tip(git_admin: Path, common: Path) -> tuple[str, str]:
    raw, _ = _stable_regular_bytes(git_admin / "HEAD", role="worktree HEAD")
    head = _git_text(raw, role="worktree HEAD")
    prefix = "ref: "
    if not head.startswith(prefix):
        raise OffloadObservationError("candidate worktree must not have detached HEAD")
    ref_name = head[len(prefix) :]
    branch = ref_name.removeprefix("refs/heads/")
    _identifier(branch, "branch")
    loose = _ref_path(common, ref_name)
    try:
        os.lstat(loose)
    except FileNotFoundError:
        tip = _packed_ref(common, ref_name)
    except OSError as exc:
        raise OffloadObservationError("Git branch ref cannot be classified") from exc
    else:
        raw_tip, _ = _stable_regular_bytes(loose, role="Git branch ref")
        tip = _git_oid(raw_tip, role="branch tip")
    return branch, tip


def _parse_index_target(
    raw: bytes, *, object_hash_bytes: int, target_path: bytes
) -> tuple[str, str]:
    checksum_size = object_hash_bytes
    if len(raw) < 12 + checksum_size or raw[:4] != b"DIRC":
        raise OffloadObservationError("Git index has an invalid header")
    version = int.from_bytes(raw[4:8], "big")
    if version not in {2, 3}:
        raise OffloadObservationError("Git index must use supported version 2 or 3")
    entry_count = int.from_bytes(raw[8:12], "big")
    if entry_count > 1_000_000:
        raise OffloadObservationError("Git index entry count is unbounded")
    body_end = len(raw) - checksum_size
    position = 12
    matches: list[tuple[int, int, bytes]] = []
    previous_path: bytes | None = None
    for _ in range(entry_count):
        entry_start = position
        fixed_size = 40 + object_hash_bytes + 2
        if position + fixed_size > body_end:
            raise OffloadObservationError("Git index entry is truncated")
        mode = int.from_bytes(raw[position + 24 : position + 28], "big")
        object_id = raw[position + 40 : position + 40 + object_hash_bytes]
        flags_offset = position + 40 + object_hash_bytes
        flags = int.from_bytes(raw[flags_offset : flags_offset + 2], "big")
        position = flags_offset + 2
        if flags & 0x4000:
            if version != 3 or position + 2 > body_end:
                raise OffloadObservationError("Git index extended flags are malformed")
            position += 2
        terminator = raw.find(b"\x00", position, body_end)
        if terminator < 0:
            raise OffloadObservationError("Git index path is not NUL terminated")
        path_bytes = raw[position:terminator]
        if (
            not path_bytes
            or path_bytes.startswith((b"/", b"\\"))
            or any(part in {b"", b".", b".."} for part in path_bytes.split(b"/"))
        ):
            raise OffloadObservationError("Git index contains an unsafe path")
        declared_length = flags & 0x0FFF
        if declared_length < 0x0FFF and declared_length != len(path_bytes):
            raise OffloadObservationError("Git index path length disagrees with flags")
        if previous_path is not None and path_bytes < previous_path:
            raise OffloadObservationError("Git index entries are not ordered")
        previous_path = path_bytes
        stage = (flags >> 12) & 0x3
        if path_bytes == target_path:
            matches.append((mode, stage, object_id))
        consumed = (terminator + 1) - entry_start
        position = entry_start + ((consumed + 7) & ~7)
        if position > body_end:
            raise OffloadObservationError("Git index entry padding is truncated")

    while position < body_end:
        if position + 8 > body_end:
            raise OffloadObservationError("Git index extension header is truncated")
        signature = raw[position : position + 4]
        length = int.from_bytes(raw[position + 4 : position + 8], "big")
        position += 8
        if position + length > body_end:
            raise OffloadObservationError("Git index extension is truncated")
        if any(byte < 0x20 or byte > 0x7E for byte in signature):
            raise OffloadObservationError("Git index extension signature is invalid")
        if signature[:1].islower():
            raise OffloadObservationError("mandatory Git index extension is unsupported")
        position += length
    if position != body_end:
        raise OffloadObservationError("Git index framing is inconsistent")
    if len(matches) != 1:
        raise OffloadObservationError("target must have exactly one Git index record")
    mode, stage, object_id = matches[0]
    if stage != 0:
        raise OffloadObservationError("target index record must be stage 0")
    if mode not in {0o100644, 0o100755}:
        raise OffloadObservationError("target Git mode must be 100644 or 100755")
    return format(mode, "06o"), object_id.hex()


def _target_index_entry(workspace: Path, target_path: str) -> tuple[str, str]:
    git_admin = _git_admin_path(workspace)
    raw, _ = _stable_regular_bytes(git_admin / "index", role="Git worktree index")
    target_bytes = target_path.encode("utf-8")
    candidates: list[tuple[str, str]] = []
    digest_options = (
        (20, lambda body: hashlib.sha1(body, usedforsecurity=False).digest()),
        (32, lambda body: hashlib.sha256(body).digest()),
    )
    for digest_size, digest_bytes in digest_options:
        if len(raw) <= digest_size:
            continue
        if digest_bytes(raw[:-digest_size]) != raw[-digest_size:]:
            continue
        candidates.append(
            _parse_index_target(
                raw, object_hash_bytes=digest_size, target_path=target_bytes
            )
        )
    if len(candidates) != 1:
        raise OffloadObservationError("Git index checksum/object format is ambiguous")
    return candidates[0]


def _require_git_blob_identity(raw: bytes, object_id: str) -> None:
    framed = b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw
    if len(object_id) == 40:
        actual = hashlib.sha1(framed, usedforsecurity=False).hexdigest()
    elif len(object_id) == 64:
        actual = hashlib.sha256(framed).hexdigest()
    else:  # the index parser admits only these two formats; keep this closed
        raise OffloadObservationError("target Git blob OID has an unknown format")
    if actual != object_id:
        raise OffloadObservationError("target bytes do not match the stage-0 Git blob OID")


def _artifact_inputs_include(locator: ArtifactLocator, required: Sequence[str], *, role: str) -> None:
    provenance = locator.provenance
    actual = set(provenance.get("input_digests", ()))
    missing = sorted(set(required) - actual)
    if missing:
        raise OffloadObservationError(f"{role} CAS provenance misses inputs: {missing}")


def _canonical_fingerprint_bytes(fingerprint: SourceFingerprint) -> bytes:
    return canonical_json(fingerprint.to_dict()).encode("ascii")


@dataclass(frozen=True)
class TaskAttemptWorkspaceAttestation(CanonicalContract):
    """Bind one TaskAttempt to a live, manager-allocated Git worktree."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.task-attempt-workspace-attestation"

    workspace_id: str
    spine_intent_id: int
    spine_intent_sha256: str
    task_id: str
    task_sha256: str
    source_revision: str
    branch: str
    workspace_path_sha256: str
    worktree_root_path_sha256: str
    primary_checkout_path_sha256: str
    workspace_identity_sha256: str
    primary_checkout_identity_sha256: str
    git_admin_identity_sha256: str
    reach_chain_sha256: str
    allocation_record_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("workspace_id", "task_id", "branch"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if (
            isinstance(self.spine_intent_id, bool)
            or not isinstance(self.spine_intent_id, int)
            or self.spine_intent_id < 1
        ):
            raise ValueError("spine_intent_id must be a positive Spine ledger id")
        digest_fields = (
            "spine_intent_sha256",
            "task_sha256",
            "workspace_path_sha256",
            "worktree_root_path_sha256",
            "primary_checkout_path_sha256",
            "workspace_identity_sha256",
            "primary_checkout_identity_sha256",
            "git_admin_identity_sha256",
            "reach_chain_sha256",
            "allocation_record_sha256",
        )
        for name in digest_fields:
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("workspace attestation source_revision must match provenance")
        _require_provenance_inputs(
            self.provenance,
            tuple(getattr(self, name) for name in digest_fields),
            "workspace attestation",
        )

    @staticmethod
    def _capture_material(
        manager: GitWorktreeManager, workspace_path: str | os.PathLike[str]
    ) -> dict[str, str]:
        if not isinstance(manager, GitWorktreeManager):
            raise TypeError("manager must be a GitWorktreeManager")
        first = manager.inspect_allocated_worktree(workspace_path)
        workspace = _lexical_absolute(first.path)
        worktree_root = _lexical_absolute(manager.worktree_root)
        primary = _lexical_absolute(manager.repo_path)

        workspace_metadata = _lstat_real(workspace, role="workspace", directory=True)
        root_metadata = _lstat_real(worktree_root, role="worktree root", directory=True)
        primary_metadata = _lstat_real(primary, role="primary checkout", directory=True)
        reach_chain_sha256 = _directory_chain_sha256(
            worktree_root, workspace, role="worktree-root-to-workspace"
        )

        git_admin = _git_admin_path(workspace)
        common_git_dir = _common_git_dir(git_admin)
        expected_common_git_dir = primary / ".git"
        _lstat_real(
            expected_common_git_dir,
            role="primary checkout Git directory",
            directory=True,
        )
        if _path_key(common_git_dir) != _path_key(expected_common_git_dir):
            raise OffloadObservationError(
                "candidate Git common directory must be the primary checkout .git"
            )
        branch, head = _head_branch_tip(git_admin, common_git_dir)
        git_admin_metadata = _lstat_real(git_admin, role="Git admin directory", directory=True)

        second = manager.inspect_allocated_worktree(workspace)
        if first != second:
            raise OffloadObservationError("worktree allocation changed during attestation")
        if branch != first.branch:
            raise OffloadObservationError("checked-out branch disagrees with live allocation")
        if head != first.branch_tip_at_creation:
            raise OffloadObservationError("worktree branch tip moved after allocation")
        if _path_key(workspace) == _path_key(primary):
            raise OffloadObservationError("workspace must be outside the primary checkout")
        try:
            common = os.path.commonpath((_path_key(workspace), _path_key(primary)))
        except ValueError:
            common = ""
        if common in {_path_key(workspace), _path_key(primary)}:
            raise OffloadObservationError("workspace and primary checkout must be disjoint")

        # Re-read identities after the in-process control-file observations.
        for path, initial, role in (
            (workspace, workspace_metadata, "workspace"),
            (worktree_root, root_metadata, "worktree root"),
            (primary, primary_metadata, "primary checkout"),
            (git_admin, git_admin_metadata, "Git admin directory"),
        ):
            current = _lstat_real(path, role=role, directory=True)
            if _identity_sha256(path, current, role=role) != _identity_sha256(
                path, initial, role=role
            ):
                raise OffloadObservationError(f"{role} identity changed during attestation")
        if reach_chain_sha256 != _directory_chain_sha256(
            worktree_root, workspace, role="worktree-root-to-workspace"
        ):
            raise OffloadObservationError("workspace reach chain changed during attestation")

        return {
            "branch": branch,
            "head": head,
            "workspace_path_sha256": _path_sha256(workspace, role="workspace"),
            "worktree_root_path_sha256": _path_sha256(
                worktree_root, role="worktree-root"
            ),
            "primary_checkout_path_sha256": _path_sha256(
                primary, role="primary-checkout"
            ),
            "workspace_identity_sha256": _identity_sha256(
                workspace, workspace_metadata, role="workspace"
            ),
            "primary_checkout_identity_sha256": _identity_sha256(
                primary, primary_metadata, role="primary checkout"
            ),
            "git_admin_identity_sha256": _identity_sha256(
                git_admin, git_admin_metadata, role="Git admin directory"
            ),
            "reach_chain_sha256": reach_chain_sha256,
            "allocation_record_sha256": hashlib.sha256(
                first.allocation_record_bytes
            ).hexdigest(),
        }

    @classmethod
    def capture(
        cls,
        *,
        manager: GitWorktreeManager,
        workspace_path: str | os.PathLike[str],
        workspace_id: str,
        spine_intent_id: int,
        spine_intent_sha256: str,
        task_id: str,
        task_sha256: str,
        source_revision: str,
        origin: str,
        created_at: str,
        trace_id: str | None = None,
    ) -> "TaskAttemptWorkspaceAttestation":
        material = cls._capture_material(manager, workspace_path)
        revision = _revision(source_revision, "source_revision")
        if material["head"] != revision:
            raise OffloadObservationError("worktree HEAD must equal source_revision")
        intent_sha = _sha256(spine_intent_sha256, "spine_intent_sha256")
        checked_task_sha = _sha256(task_sha256, "task_sha256")
        inputs = (
            intent_sha,
            checked_task_sha,
            *(material[name] for name in (
                "workspace_path_sha256",
                "worktree_root_path_sha256",
                "primary_checkout_path_sha256",
                "workspace_identity_sha256",
                "primary_checkout_identity_sha256",
                "git_admin_identity_sha256",
                "reach_chain_sha256",
                "allocation_record_sha256",
            )),
        )
        return cls(
            workspace_id=workspace_id,
            spine_intent_id=spine_intent_id,
            spine_intent_sha256=intent_sha,
            task_id=task_id,
            task_sha256=checked_task_sha,
            source_revision=revision,
            branch=material["branch"],
            workspace_path_sha256=material["workspace_path_sha256"],
            worktree_root_path_sha256=material["worktree_root_path_sha256"],
            primary_checkout_path_sha256=material["primary_checkout_path_sha256"],
            workspace_identity_sha256=material["workspace_identity_sha256"],
            primary_checkout_identity_sha256=material[
                "primary_checkout_identity_sha256"
            ],
            git_admin_identity_sha256=material["git_admin_identity_sha256"],
            reach_chain_sha256=material["reach_chain_sha256"],
            allocation_record_sha256=material["allocation_record_sha256"],
            provenance=ContractProvenance(
                origin=origin,
                source_revision=revision,
                created_at=created_at,
                input_digests=inputs,
                trace_id=trace_id,
            ),
        )

    def verify_current(
        self, manager: GitWorktreeManager, workspace_path: str | os.PathLike[str]
    ) -> None:
        material = self._capture_material(manager, workspace_path)
        expected = {
            "branch": self.branch,
            "head": self.source_revision,
            "workspace_path_sha256": self.workspace_path_sha256,
            "worktree_root_path_sha256": self.worktree_root_path_sha256,
            "primary_checkout_path_sha256": self.primary_checkout_path_sha256,
            "workspace_identity_sha256": self.workspace_identity_sha256,
            "primary_checkout_identity_sha256": self.primary_checkout_identity_sha256,
            "git_admin_identity_sha256": self.git_admin_identity_sha256,
            "reach_chain_sha256": self.reach_chain_sha256,
            "allocation_record_sha256": self.allocation_record_sha256,
        }
        mismatches = sorted(name for name, value in expected.items() if material[name] != value)
        if mismatches:
            raise OffloadObservationError(
                "workspace attestation no longer matches: " + ", ".join(mismatches)
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskAttemptWorkspaceAttestation":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class TargetBeforeObservation(CanonicalContract):
    """Bind one exact stage-0 regular UTF-8 target before model execution."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.target-before-observation"

    workspace_attestation_sha256: str
    source_revision: str
    target_path: str
    target_kind: str
    content_sha256: str
    byte_length: int
    git_mode: str
    encoding: str
    file_identity_sha256: str
    parent_chain_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in (
            "workspace_attestation_sha256",
            "content_sha256",
            "file_identity_sha256",
            "parent_chain_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(self, "target_path", _portable_target_path(self.target_path))
        if self.target_kind != "existing-regular-utf8-file":
            raise ValueError("target_kind must be exactly 'existing-regular-utf8-file'")
        if self.encoding != "utf-8":
            raise ValueError("encoding must be exactly 'utf-8'")
        if self.git_mode not in {"100644", "100755"}:
            raise ValueError("git_mode must be 100644 or 100755")
        if (
            isinstance(self.byte_length, bool)
            or not isinstance(self.byte_length, int)
            or self.byte_length < 0
        ):
            raise ValueError("byte_length must be a non-negative integer")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("target observation source_revision must match provenance")
        _require_provenance_inputs(
            self.provenance,
            (
                self.workspace_attestation_sha256,
                self.content_sha256,
                self.file_identity_sha256,
                self.parent_chain_sha256,
            ),
            "target-before observation",
        )

    @staticmethod
    def _capture_material(workspace_path: Path, target_path: str) -> dict[str, object]:
        workspace = _lexical_absolute(workspace_path)
        portable = _portable_target_path(target_path)
        target = workspace.joinpath(*portable.split("/"))
        parent_chain_before = _directory_chain_sha256(
            workspace, target.parent, role="workspace-to-target-parent"
        )
        index_before = _target_index_entry(workspace, portable)
        raw, metadata = _stable_regular_bytes(target, role="target")
        try:
            raw.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise OffloadObservationError("target must contain strict UTF-8 bytes") from exc
        _require_git_blob_identity(raw, index_before[1])
        index_after = _target_index_entry(workspace, portable)
        parent_chain_after = _directory_chain_sha256(
            workspace, target.parent, role="workspace-to-target-parent"
        )
        if index_before != index_after:
            raise OffloadObservationError("target Git index record changed during capture")
        if parent_chain_before != parent_chain_after:
            raise OffloadObservationError("target parent chain changed during capture")
        return {
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
            "git_mode": index_before[0],
            "file_identity_sha256": _identity_sha256(target, metadata, role="target file"),
            "parent_chain_sha256": parent_chain_before,
        }

    @classmethod
    def capture(
        cls,
        *,
        manager: GitWorktreeManager,
        workspace_path: str | os.PathLike[str],
        workspace_attestation: TaskAttemptWorkspaceAttestation,
        target_path: str,
        origin: str,
        created_at: str,
        trace_id: str | None = None,
    ) -> "TargetBeforeObservation":
        if not isinstance(workspace_attestation, TaskAttemptWorkspaceAttestation):
            raise TypeError("workspace_attestation must be canonical")
        workspace_attestation.verify_current(manager, workspace_path)
        portable = _portable_target_path(target_path)
        material = cls._capture_material(_lexical_absolute(workspace_path), portable)
        return cls(
            workspace_attestation_sha256=workspace_attestation.digest,
            source_revision=workspace_attestation.source_revision,
            target_path=portable,
            target_kind="existing-regular-utf8-file",
            content_sha256=str(material["content_sha256"]),
            byte_length=int(material["byte_length"]),
            git_mode=str(material["git_mode"]),
            encoding="utf-8",
            file_identity_sha256=str(material["file_identity_sha256"]),
            parent_chain_sha256=str(material["parent_chain_sha256"]),
            provenance=ContractProvenance(
                origin=origin,
                source_revision=workspace_attestation.source_revision,
                created_at=created_at,
                input_digests=(
                    workspace_attestation.digest,
                    str(material["content_sha256"]),
                    str(material["file_identity_sha256"]),
                    str(material["parent_chain_sha256"]),
                ),
                trace_id=trace_id,
            ),
        )

    def verify_current(
        self,
        *,
        manager: GitWorktreeManager,
        workspace_path: str | os.PathLike[str],
        workspace_attestation: TaskAttemptWorkspaceAttestation,
    ) -> None:
        if workspace_attestation.digest != self.workspace_attestation_sha256:
            raise OffloadObservationError("target binds a different workspace attestation")
        workspace_attestation.verify_current(manager, workspace_path)
        material = self._capture_material(_lexical_absolute(workspace_path), self.target_path)
        expected: dict[str, object] = {
            "content_sha256": self.content_sha256,
            "byte_length": self.byte_length,
            "git_mode": self.git_mode,
            "file_identity_sha256": self.file_identity_sha256,
            "parent_chain_sha256": self.parent_chain_sha256,
        }
        mismatches = sorted(name for name, value in expected.items() if material[name] != value)
        if mismatches:
            raise OffloadObservationError(
                "target-before observation no longer matches: " + ", ".join(mismatches)
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TargetBeforeObservation":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class OffloadWorkspaceObservation(CanonicalContract):
    """Bind attestation, exact clean source fingerprint CAS, and target."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.offload-workspace-observation"

    workspace_id: str
    workspace_attestation_sha256: str
    source_revision: str
    base_source_artifact_sha256: str
    source_fingerprint_sha256: str
    source_fingerprint_artifact_sha256: str
    target_before_observation_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _identifier(self.workspace_id, "workspace_id"))
        digest_fields = (
            "workspace_attestation_sha256",
            "base_source_artifact_sha256",
            "source_fingerprint_sha256",
            "source_fingerprint_artifact_sha256",
            "target_before_observation_sha256",
        )
        for name in digest_fields:
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("workspace observation source_revision must match provenance")
        _require_provenance_inputs(
            self.provenance,
            tuple(getattr(self, name) for name in digest_fields),
            "offload workspace observation",
        )

    @classmethod
    def capture(
        cls,
        *,
        manager: GitWorktreeManager,
        workspace_path: str | os.PathLike[str],
        workspace_attestation: TaskAttemptWorkspaceAttestation,
        target_before: TargetBeforeObservation,
        base_source_artifact_locator: ArtifactLocator,
        source_fingerprint: SourceFingerprint,
        source_fingerprint_locator: ArtifactLocator,
        artifact_store: ArtifactStore,
        origin: str,
        created_at: str,
        trace_id: str | None = None,
    ) -> "OffloadWorkspaceObservation":
        if not isinstance(workspace_attestation, TaskAttemptWorkspaceAttestation):
            raise TypeError("workspace_attestation must be canonical")
        if not isinstance(target_before, TargetBeforeObservation):
            raise TypeError("target_before must be canonical")
        if not isinstance(source_fingerprint, SourceFingerprint):
            raise TypeError("source_fingerprint must be a SourceFingerprint")
        if not isinstance(base_source_artifact_locator, ArtifactLocator):
            raise TypeError("base_source_artifact_locator must be an ArtifactLocator")
        if not isinstance(source_fingerprint_locator, ArtifactLocator):
            raise TypeError("source_fingerprint_locator must be an ArtifactLocator")
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")

        workspace_attestation.verify_current(manager, workspace_path)
        target_before.verify_current(
            manager=manager,
            workspace_path=workspace_path,
            workspace_attestation=workspace_attestation,
        )
        if not source_fingerprint.exact_clean_head:
            raise OffloadObservationError("source fingerprint must be exact and clean")
        if source_fingerprint.head != workspace_attestation.source_revision:
            raise OffloadObservationError("source fingerprint HEAD must equal source_revision")

        base_locator = artifact_store.verify(base_source_artifact_locator)
        if base_locator.provenance.get("source_revision") != workspace_attestation.source_revision:
            raise OffloadObservationError("base source CAS revision mismatch")
        expected_base_metadata = {
            "kind": BASE_SOURCE_ARTIFACT_KIND,
            "source_revision": workspace_attestation.source_revision,
        }
        if (
            base_locator.metadata != expected_base_metadata
            or base_locator.to_dict().get("media_type") != "application/x-tar"
        ):
            raise OffloadObservationError("base source CAS metadata mismatch")
        locator = artifact_store.verify(source_fingerprint_locator)
        fingerprint_bytes = _canonical_fingerprint_bytes(source_fingerprint)
        if locator.artifact_sha256 != hashlib.sha256(fingerprint_bytes).hexdigest():
            raise OffloadObservationError("source fingerprint CAS digest mismatch")
        if artifact_store.get_bytes(locator.artifact_sha256) != fingerprint_bytes:
            raise OffloadObservationError("source fingerprint CAS bytes mismatch")
        expected_metadata = {
            "kind": SOURCE_FINGERPRINT_ARTIFACT_KIND,
            "source_fingerprint_sha256": source_fingerprint.fingerprint_sha256,
            "source_revision": workspace_attestation.source_revision,
            "workspace_attestation_sha256": workspace_attestation.digest,
        }
        if locator.metadata != expected_metadata:
            raise OffloadObservationError("source fingerprint CAS metadata mismatch")
        if locator.provenance.get("source_revision") != workspace_attestation.source_revision:
            raise OffloadObservationError("source fingerprint CAS revision mismatch")
        _artifact_inputs_include(
            locator,
            (workspace_attestation.digest, source_fingerprint.fingerprint_sha256),
            role="source fingerprint",
        )

        target_before.verify_current(
            manager=manager,
            workspace_path=workspace_path,
            workspace_attestation=workspace_attestation,
        )
        base_sha = base_locator.artifact_sha256
        inputs = (
            workspace_attestation.digest,
            base_sha,
            source_fingerprint.fingerprint_sha256,
            locator.artifact_sha256,
            target_before.digest,
        )
        return cls(
            workspace_id=workspace_attestation.workspace_id,
            workspace_attestation_sha256=workspace_attestation.digest,
            source_revision=workspace_attestation.source_revision,
            base_source_artifact_sha256=base_sha,
            source_fingerprint_sha256=source_fingerprint.fingerprint_sha256,
            source_fingerprint_artifact_sha256=locator.artifact_sha256,
            target_before_observation_sha256=target_before.digest,
            provenance=ContractProvenance(
                origin=origin,
                source_revision=workspace_attestation.source_revision,
                created_at=created_at,
                input_digests=inputs,
                trace_id=trace_id,
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OffloadWorkspaceObservation":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise OffloadObservationError("Ollama metadata response is not strict UTF-8") from exc

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OffloadObservationError(f"Ollama metadata has duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise OffloadObservationError(f"Ollama metadata contains invalid number {value}")

    try:
        value = json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except OffloadObservationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OffloadObservationError("Ollama metadata response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise OffloadObservationError("Ollama metadata response must be an object")
    return value


@dataclass(frozen=True)
class OllamaModelObservation(CanonicalContract):
    """Bind one exact model record parsed from raw post-begin Ollama bytes."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.ollama-model-observation"

    execution_request_sha256: str
    start_receipt_sha256: str
    execution_plan_sha256: str
    source_revision: str
    runtime_manifest_sha256: str
    provider_id: str
    runtime_id: str
    provider_endpoint: str
    metadata_request_sha256: str
    raw_response_sha256: str
    raw_response_size: int
    raw_response_artifact_locator: str
    selected_record_sha256: str
    model_id: str
    model_sha256: str
    model_size: int
    model_modified_at: str
    model_details_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        digest_fields = (
            "execution_request_sha256",
            "start_receipt_sha256",
            "execution_plan_sha256",
            "runtime_manifest_sha256",
            "metadata_request_sha256",
            "raw_response_sha256",
            "selected_record_sha256",
            "model_sha256",
            "model_details_sha256",
        )
        for name in digest_fields:
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        if _identifier(self.provider_id, "provider_id") != "ollama":
            raise ValueError("provider_id must be exactly 'ollama'")
        if _identifier(self.runtime_id, "runtime_id") != "ollama_http":
            raise ValueError("runtime_id must be exactly 'ollama_http'")
        object.__setattr__(
            self, "provider_endpoint", _loopback_ollama_endpoint(self.provider_endpoint)
        )
        object.__setattr__(self, "model_id", _identifier(self.model_id, "model_id"))
        object.__setattr__(
            self,
            "raw_response_artifact_locator",
            _artifact_locator(
                self.raw_response_artifact_locator, "raw_response_artifact_locator"
            ),
        )
        for name in ("raw_response_size", "model_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        object.__setattr__(
            self,
            "model_modified_at",
            _utc_timestamp(self.model_modified_at, "model_modified_at"),
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("model observation source_revision must match provenance")
        _require_provenance_inputs(
            self.provenance,
            (
                *(getattr(self, name) for name in digest_fields),
                _locator_sha256(self.raw_response_artifact_locator),
            ),
            "Ollama model observation",
        )

    @classmethod
    def capture_from_response_bytes(
        cls,
        *,
        execution_request: EffectExecutionRequest,
        start_result: EffectStartResult,
        execution_plan: OffloadExecutionPlan,
        metadata_request_sha256: str,
        raw_response_bytes: bytes,
        raw_response_locator: ArtifactLocator,
        artifact_store: ArtifactStore,
        origin: str,
        created_at: str,
        trace_id: str | None = None,
    ) -> "OllamaModelObservation":
        if not isinstance(execution_request, EffectExecutionRequest):
            raise TypeError("execution_request must be canonical")
        if not isinstance(start_result, EffectStartResult):
            raise TypeError("start_result must be canonical")
        if not start_result.execute or start_result.completion_capability is None:
            raise OffloadObservationError(
                "model metadata may be captured only for one new live effect start"
            )
        start_receipt = start_result.receipt
        if not isinstance(execution_plan, OffloadExecutionPlan):
            raise TypeError("execution_plan must be canonical")
        if not isinstance(raw_response_bytes, bytes):
            raise TypeError("raw_response_bytes must be bytes")
        if not isinstance(raw_response_locator, ArtifactLocator):
            raise TypeError("raw_response_locator must be an ArtifactLocator")
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")
        if execution_request.digest != start_receipt.execution_request_sha256:
            raise OffloadObservationError("start receipt binds a different execution request")
        if execution_request.execution_id != start_receipt.execution_id:
            raise OffloadObservationError("start receipt binds a different execution id")
        if execution_request.execution_plan_sha256 != execution_plan.digest:
            raise OffloadObservationError("execution request binds a different plan")
        if len(raw_response_bytes) > execution_plan.max_response_bytes:
            raise OffloadObservationError("raw Ollama response exceeds the plan byte cap")

        request_sha = _sha256(metadata_request_sha256, "metadata_request_sha256")
        raw_sha = hashlib.sha256(raw_response_bytes).hexdigest()
        locator = artifact_store.verify(raw_response_locator)
        if locator.artifact_sha256 != raw_sha or locator.byte_length != len(raw_response_bytes):
            raise OffloadObservationError("raw Ollama response CAS identity mismatch")
        if artifact_store.get_bytes(raw_sha) != raw_response_bytes:
            raise OffloadObservationError("raw Ollama response CAS bytes mismatch")
        expected_metadata = {
            "execution_plan_sha256": execution_plan.digest,
            "execution_request_sha256": execution_request.digest,
            "kind": OLLAMA_METADATA_ARTIFACT_KIND,
            "metadata_request_sha256": request_sha,
            "start_receipt_sha256": start_receipt.receipt_sha256,
        }
        if locator.metadata != expected_metadata:
            raise OffloadObservationError("raw Ollama response CAS metadata mismatch")
        if locator.provenance.get("source_revision") != execution_plan.source_revision:
            raise OffloadObservationError("raw Ollama response CAS revision mismatch")
        _artifact_inputs_include(
            locator,
            (
                execution_plan.digest,
                execution_request.digest,
                start_receipt.receipt_sha256,
                request_sha,
            ),
            role="raw Ollama response",
        )

        payload = _strict_json_object(raw_response_bytes)
        models = payload.get("models")
        if not isinstance(models, list):
            raise OffloadObservationError("Ollama metadata must contain a models array")
        candidates: list[dict[str, Any]] = []
        for index, record in enumerate(models):
            if not isinstance(record, dict):
                raise OffloadObservationError(f"Ollama models[{index}] must be an object")
            if record.get("name") == execution_plan.model_id or record.get("model") == execution_plan.model_id:
                candidates.append(record)
        if len(candidates) != 1:
            raise OffloadObservationError(
                "Ollama metadata must contain exactly one record for model_id"
            )
        selected = candidates[0]
        required = {"name", "model", "modified_at", "size", "digest", "details"}
        if not required.issubset(selected):
            raise OffloadObservationError("selected Ollama model record is incomplete")
        if selected["name"] != execution_plan.model_id or selected["model"] != execution_plan.model_id:
            raise OffloadObservationError("selected Ollama model aliases model_id ambiguously")
        digest_value = selected["digest"]
        expected_digest_text = f"sha256:{execution_plan.expected_model_sha256}"
        if digest_value != expected_digest_text:
            raise OffloadObservationError("selected Ollama model digest mismatches plan")
        size = selected["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise OffloadObservationError("selected Ollama model size must be positive")
        details = selected["details"]
        if not isinstance(details, dict):
            raise OffloadObservationError("selected Ollama model details must be an object")
        modified_at = _utc_timestamp(selected["modified_at"], "model.modified_at")
        selected_sha = canonical_sha(selected)
        details_sha = canonical_sha(details)
        inputs = (
            execution_request.digest,
            start_receipt.receipt_sha256,
            execution_plan.digest,
            execution_plan.runtime_manifest_sha256,
            request_sha,
            raw_sha,
            locator.locator_sha256,
            selected_sha,
            execution_plan.expected_model_sha256,
            details_sha,
        )
        return cls(
            execution_request_sha256=execution_request.digest,
            start_receipt_sha256=start_receipt.receipt_sha256,
            execution_plan_sha256=execution_plan.digest,
            source_revision=execution_plan.source_revision,
            runtime_manifest_sha256=execution_plan.runtime_manifest_sha256,
            provider_id=execution_plan.provider_id,
            runtime_id=execution_plan.runtime_id,
            provider_endpoint=execution_plan.provider_endpoint,
            metadata_request_sha256=request_sha,
            raw_response_sha256=raw_sha,
            raw_response_size=len(raw_response_bytes),
            raw_response_artifact_locator=locator.locator_uri,
            selected_record_sha256=selected_sha,
            model_id=execution_plan.model_id,
            model_sha256=execution_plan.expected_model_sha256,
            model_size=size,
            model_modified_at=modified_at,
            model_details_sha256=details_sha,
            provenance=ContractProvenance(
                origin=origin,
                source_revision=execution_plan.source_revision,
                created_at=created_at,
                input_digests=inputs,
                trace_id=trace_id,
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OllamaModelObservation":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


__all__ = [
    "BASE_SOURCE_ARTIFACT_KIND",
    "OLLAMA_METADATA_ARTIFACT_KIND",
    "SOURCE_FINGERPRINT_ARTIFACT_KIND",
    "OffloadObservationError",
    "OffloadWorkspaceObservation",
    "OllamaModelObservation",
    "TargetBeforeObservation",
    "TaskAttemptWorkspaceAttestation",
]
