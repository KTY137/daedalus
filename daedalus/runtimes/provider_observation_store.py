"""Pre-provisioned provider-observation binding store.

This additive strangler separates explicit no-clobber schema publication from
ordinary ``ProviderObservationBindingLedger`` construction.  The store is bound
inside its own SQLite metadata to one exact source revision, isolated attempt
root, Primary-Checkout root and target path.  Replay reads are opened with
SQLite ``mode=ro`` and ``query_only``; writer opens use ``mode=rw`` and can
never create or repair a missing database.

The historical auto-initializing ledger remains available for compatibility.
Canonical effect registration, guard composition and broker migration are
separate reviewed packets.  Nothing in this module grants an Effect Lease,
executes a provider, mutates a checkout, promotes, or closes a Gate.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from daedalus.kernel.contracts.base import _identifier, _revision
from daedalus.runtimes.provider_observation import (
    ProviderObservationAuthorityBindingError,
    ProviderObservationAuthorityStateError,
    ProviderObservationBindingLedger,
    _normalize_keyring,
    _secret_bytes,
    observation_keyring_digest,
)
from daedalus.spine.envelope import canonical_sha


class ProviderObservationStoreError(RuntimeError):
    """A pre-provisioned provider-observation store failed closed."""


_BINDINGS_TABLE = "provider_observation_bindings"
_METADATA_TABLE = "provider_observation_store_metadata_v1"
_SCHEMA_VERSION = 1
_BINDING_COLUMNS = (
    "execution_id",
    "record_json",
    "record_sha256",
    "record_hmac_sha256",
)
_METADATA_COLUMNS = (
    "singleton",
    "target_sha256",
    "source_revision",
    "schema_sha256",
)
_BINDINGS_SQL = """
CREATE TABLE provider_observation_bindings (
    execution_id TEXT NOT NULL PRIMARY KEY,
    record_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    record_hmac_sha256 TEXT NOT NULL
)
""".strip()
_METADATA_SQL = """
CREATE TABLE provider_observation_store_metadata_v1 (
    singleton INTEGER NOT NULL PRIMARY KEY CHECK(singleton = 1),
    target_sha256 TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    schema_sha256 TEXT NOT NULL
)
""".strip()


def _normalized_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


_SCHEMA_DESCRIPTOR = {
    "schema_version": _SCHEMA_VERSION,
    "bindings_table": _BINDINGS_TABLE,
    "bindings_columns": list(_BINDING_COLUMNS),
    "bindings_sql": _normalized_sql(_BINDINGS_SQL),
    "metadata_table": _METADATA_TABLE,
    "metadata_columns": list(_METADATA_COLUMNS),
    "metadata_sql": _normalized_sql(_METADATA_SQL),
}
SCHEMA_SHA256 = hashlib.sha256(
    json.dumps(
        _SCHEMA_DESCRIPTOR,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
).hexdigest()


def _path_text(value: str | os.PathLike[str], label: str) -> str:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be path-like")
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise TypeError(f"{label} must be path-like") from exc
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if not isinstance(raw, str) or not raw:
        raise TypeError(f"{label} must be a non-empty path")
    if "\x00" in raw or "\n" in raw or "\r" in raw:
        raise ValueError(f"{label} contains forbidden characters")
    if not Path(raw).is_absolute():
        raise ValueError(f"{label} must be absolute")
    return os.path.normpath(os.path.abspath(raw))


def _normal(value: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(value))))


def _real_directory(value: str | os.PathLike[str], label: str) -> Path:
    lexical = Path(_path_text(value, label))
    if os.path.lexists(lexical) and lexical.is_symlink():
        raise ProviderObservationStoreError(f"{label} may not be a symlink")
    try:
        resolved = lexical.resolve(strict=True)
        mode = resolved.stat().st_mode
    except (OSError, RuntimeError) as exc:
        raise ProviderObservationStoreError(
            f"{label} must be an existing directory"
        ) from exc
    if not stat.S_ISDIR(mode):
        raise ProviderObservationStoreError(f"{label} must be a directory")
    if _normal(lexical) != _normal(resolved):
        raise ProviderObservationStoreError(
            f"{label} may not traverse symlink components"
        )
    return resolved


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((_normal(child), _normal(parent))) == _normal(parent)
    except ValueError:
        return False


def _roots_overlap(first: Path, second: Path) -> bool:
    return _is_within(first, second) or _is_within(second, first)


@dataclass(frozen=True)
class ProviderObservationStoreTarget:
    """Exact revision-bound isolated target for one binding store."""

    path: str
    attempt_root: str
    primary_checkout_root: str
    source_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _path_text(self.path, "path"))
        object.__setattr__(
            self, "attempt_root", _path_text(self.attempt_root, "attempt_root")
        )
        object.__setattr__(
            self,
            "primary_checkout_root",
            _path_text(self.primary_checkout_root, "primary_checkout_root"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        _validated_target_path(self, require_exists=None)

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ProviderObservationStoreStatus:
    """Read-only exact projection of one initialized store."""

    target_sha256: str
    path: str
    source_revision: str
    file_device: int
    file_inode: int
    file_nlink: int
    file_size: int
    file_mtime_ns: int
    schema_version: int
    schema_sha256: str

    @property
    def identity(self) -> tuple[int, int]:
        return (self.file_device, self.file_inode)

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _validated_target_path(
    target: ProviderObservationStoreTarget,
    *,
    require_exists: bool | None,
) -> tuple[Path, os.stat_result | None]:
    if type(target) is not ProviderObservationStoreTarget:
        raise ProviderObservationStoreError(
            "target must be an exact ProviderObservationStoreTarget"
        )
    attempt_root = _real_directory(target.attempt_root, "attempt_root")
    primary_root = _real_directory(
        target.primary_checkout_root, "primary_checkout_root"
    )
    if _roots_overlap(attempt_root, primary_root):
        raise ProviderObservationStoreError(
            "attempt root and Primary Checkout must be disjoint"
        )

    lexical = Path(target.path)
    if not lexical.name or lexical.name in {".", ".."}:
        raise ProviderObservationStoreError("store target requires a file name")
    parent = _real_directory(lexical.parent, "store parent")
    if not _is_within(parent, attempt_root):
        raise ProviderObservationStoreError(
            "store target must remain below the isolated attempt root"
        )
    if _is_within(lexical, primary_root):
        raise ProviderObservationStoreError(
            "store target may not be inside the Primary Checkout"
        )

    exists = os.path.lexists(lexical)
    if require_exists is True and not exists:
        raise ProviderObservationStoreError("provider-observation store is missing")
    if require_exists is False and exists:
        raise ProviderObservationStoreError(
            "provider-observation store target already exists"
        )
    if not exists:
        return lexical, None
    if lexical.is_symlink():
        raise ProviderObservationStoreError(
            "provider-observation store may not be a symlink"
        )
    try:
        resolved = lexical.resolve(strict=True)
        result = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise ProviderObservationStoreError(
            "provider-observation store is unavailable"
        ) from exc
    if _normal(lexical) != _normal(resolved):
        raise ProviderObservationStoreError(
            "provider-observation store path may not be redirected"
        )
    if not stat.S_ISREG(result.st_mode):
        raise ProviderObservationStoreError(
            "provider-observation store must be a regular file"
        )
    if result.st_nlink != 1:
        raise ProviderObservationStoreError(
            "provider-observation store may not have hard-link aliases"
        )
    return resolved, result


def _refuse_existing_sidecars(path: Path) -> None:
    for suffix in ("-journal", "-wal", "-shm"):
        if os.path.lexists(Path(str(path) + suffix)):
            raise ProviderObservationStoreError(
                "provider-observation SQLite sidecar already exists"
            )


def _open_sqlite(path: Path, *, mode: str, query_only: bool) -> sqlite3.Connection:
    if mode not in {"ro", "rw"}:
        raise ValueError("SQLite mode must be ro or rw")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            path.as_uri() + f"?mode={mode}",
            uri=True,
            isolation_level=None,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        if query_only:
            connection.execute("PRAGMA query_only=ON")
            if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
                raise ProviderObservationStoreError(
                    "provider-observation read connection is not query-only"
                )
        return connection
    except ProviderObservationStoreError:
        if connection is not None:
            connection.close()
        raise
    except (sqlite3.Error, TypeError, ValueError, IndexError) as exc:
        if connection is not None:
            connection.close()
        raise ProviderObservationStoreError(
            "provider-observation store could not be opened"
        ) from exc


def _exact_table_contract(
    connection: sqlite3.Connection,
    *,
    table: str,
    sql: str,
    columns: tuple[str, ...],
    types: tuple[str, ...],
    not_null: tuple[int, ...],
    primary_key: tuple[int, ...],
) -> None:
    row = connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name=?",
        (table,),
    ).fetchone()
    if row is None or row[0] != "table" or row[1] != table:
        raise ProviderObservationStoreError(
            "provider-observation table identity does not match"
        )
    if not isinstance(row[2], str) or _normalized_sql(row[2]) != _normalized_sql(sql):
        raise ProviderObservationStoreError(
            "provider-observation table SQL does not match"
        )
    info = connection.execute(f"PRAGMA table_info({table})").fetchall()
    if tuple(str(item[1]) for item in info) != columns:
        raise ProviderObservationStoreError(
            "provider-observation table columns do not match"
        )
    if tuple(str(item[2]).upper() for item in info) != types:
        raise ProviderObservationStoreError(
            "provider-observation table types do not match"
        )
    if tuple(int(item[3]) for item in info) != not_null:
        raise ProviderObservationStoreError(
            "provider-observation table nullability does not match"
        )
    if tuple(int(item[5]) for item in info) != primary_key:
        raise ProviderObservationStoreError(
            "provider-observation table primary key does not match"
        )


def _verify_schema(
    connection: sqlite3.Connection,
    target: ProviderObservationStoreTarget,
) -> None:
    try:
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise ProviderObservationStoreError(
                "provider-observation store failed quick_check"
            )
        version = connection.execute("PRAGMA user_version").fetchone()
        if version is None or int(version[0]) != _SCHEMA_VERSION:
            raise ProviderObservationStoreError(
                "provider-observation store schema version does not match"
            )
        objects = connection.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        if tuple((str(row[0]), str(row[1])) for row in objects) != (
            ("table", _BINDINGS_TABLE),
            ("table", _METADATA_TABLE),
        ):
            raise ProviderObservationStoreError(
                "provider-observation store contains unexpected schema objects"
            )
        _exact_table_contract(
            connection,
            table=_BINDINGS_TABLE,
            sql=_BINDINGS_SQL,
            columns=_BINDING_COLUMNS,
            types=("TEXT", "TEXT", "TEXT", "TEXT"),
            not_null=(1, 1, 1, 1),
            primary_key=(1, 0, 0, 0),
        )
        _exact_table_contract(
            connection,
            table=_METADATA_TABLE,
            sql=_METADATA_SQL,
            columns=_METADATA_COLUMNS,
            types=("INTEGER", "TEXT", "TEXT", "TEXT"),
            not_null=(1, 1, 1, 1),
            primary_key=(1, 0, 0, 0),
        )
        rows = connection.execute(
            f"SELECT singleton, target_sha256, source_revision, schema_sha256 "
            f"FROM {_METADATA_TABLE} ORDER BY singleton"
        ).fetchall()
        if len(rows) != 1:
            raise ProviderObservationStoreError(
                "provider-observation store metadata cardinality does not match"
            )
        row = rows[0]
        if (
            int(row[0]) != 1
            or str(row[1]) != target.digest
            or str(row[2]) != target.source_revision
            or str(row[3]) != SCHEMA_SHA256
        ):
            raise ProviderObservationStoreError(
                "provider-observation store metadata binding does not match"
            )
    except ProviderObservationStoreError:
        raise
    except (sqlite3.Error, TypeError, ValueError, IndexError) as exc:
        raise ProviderObservationStoreError(
            "provider-observation store schema could not be verified"
        ) from exc


def _fsync_file(path: Path) -> None:
    # Windows flushes through FlushFileBuffers, which needs write access; a
    # read-only handle fails with EBADF. POSIX accepts a read-only descriptor.
    flags = os.O_WRONLY if os.name == "nt" else os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _same_identity(path: Path, expected: os.stat_result) -> bool:
    try:
        current = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(current.st_mode) and (
        current.st_dev,
        current.st_ino,
    ) == (expected.st_dev, expected.st_ino)


def inspect_provider_observation_binding_store(
    target: ProviderObservationStoreTarget,
) -> ProviderObservationStoreStatus:
    """Inspect an existing store without creating or repairing anything."""

    path, before = _validated_target_path(target, require_exists=True)
    assert before is not None
    _refuse_existing_sidecars(path)
    connection = _open_sqlite(path, mode="ro", query_only=True)
    try:
        _verify_schema(connection, target)
    finally:
        connection.close()
    path_after, after = _validated_target_path(target, require_exists=True)
    assert after is not None
    _refuse_existing_sidecars(path_after)
    if _normal(path) != _normal(path_after) or (
        before.st_dev,
        before.st_ino,
    ) != (after.st_dev, after.st_ino):
        raise ProviderObservationStoreError(
            "provider-observation store changed during inspection"
        )
    return ProviderObservationStoreStatus(
        target_sha256=target.digest,
        path=str(path_after),
        source_revision=target.source_revision,
        file_device=after.st_dev,
        file_inode=after.st_ino,
        file_nlink=after.st_nlink,
        file_size=after.st_size,
        file_mtime_ns=after.st_mtime_ns,
        schema_version=_SCHEMA_VERSION,
        schema_sha256=SCHEMA_SHA256,
    )


def initialize_provider_observation_binding_store(
    target: ProviderObservationStoreTarget,
) -> ProviderObservationStoreStatus:
    """Publish one exact empty store without clobbering an existing target."""

    path, _ = _validated_target_path(target, require_exists=False)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".provider-observation.tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    connection: sqlite3.Connection | None = None
    published_identity: os.stat_result | None = None
    completed = False
    try:
        connection = _open_sqlite(temporary, mode="rw", query_only=False)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_BINDINGS_SQL)
        connection.execute(_METADATA_SQL)
        connection.execute(
            f"INSERT INTO {_METADATA_TABLE} "
            "(singleton, target_sha256, source_revision, schema_sha256) "
            "VALUES (1, ?, ?, ?)",
            (target.digest, target.source_revision, SCHEMA_SHA256),
        )
        connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        connection.commit()
        _verify_schema(connection, target)
        connection.close()
        connection = None

        _fsync_file(temporary)
        temporary_identity = temporary.stat()
        os.link(temporary, path)
        published_identity = temporary_identity
        published = path.stat()
        if (published.st_dev, published.st_ino) != (
            temporary_identity.st_dev,
            temporary_identity.st_ino,
        ):
            raise ProviderObservationStoreError(
                "published provider-observation store identity does not match"
            )
        temporary.unlink()
        _fsync_file(path)
        _fsync_directory(path.parent)
        status = inspect_provider_observation_binding_store(target)
        completed = True
        return status
    except ProviderObservationStoreError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise ProviderObservationStoreError(
            "provider-observation store initialization failed"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
        if (
            not completed
            and published_identity is not None
            and _same_identity(path, published_identity)
        ):
            try:
                path.unlink()
                _fsync_directory(path.parent)
            except OSError:
                pass
        try:
            temporary.unlink()
        except OSError:
            pass


class PreprovisionedProviderObservationBindingLedger(
    ProviderObservationBindingLedger
):
    """Compatibility ledger that never initializes or repairs its store."""

    def __init__(
        self,
        target: ProviderObservationStoreTarget,
        *,
        authority_id: str,
        authority_keyring: Mapping[str, bytes | str],
        observation_keyring: Mapping[str, bytes | str],
        record_secret: bytes | str,
    ) -> None:
        if type(target) is not ProviderObservationStoreTarget:
            raise ProviderObservationAuthorityBindingError(
                "target must be an exact ProviderObservationStoreTarget"
            )
        try:
            status = inspect_provider_observation_binding_store(target)
            normalized_authority_id = _identifier(authority_id, "authority_id")
            normalized_authority_keyring = dict(
                _normalize_keyring(authority_keyring, label="authority_keyring")
            )
            normalized_observation_keyring = dict(
                _normalize_keyring(
                    observation_keyring, label="observation_keyring"
                )
            )
            normalized_record_secret = _secret_bytes(
                record_secret, "record_secret"
            )
        except (ProviderObservationStoreError, TypeError, ValueError) as exc:
            raise ProviderObservationAuthorityBindingError(
                "pre-provisioned provider-observation ledger is malformed"
            ) from exc

        self.path = Path(status.path)
        self.authority_id = normalized_authority_id
        self._authority_keyring = normalized_authority_keyring
        self._observation_keyring = normalized_observation_keyring
        self._record_secret = normalized_record_secret
        self.observation_keyring_sha256 = observation_keyring_digest(
            self._observation_keyring
        )
        self._store_target = target
        self._store_identity = status.identity
        self._store_schema_sha256 = status.schema_sha256

    @property
    def store_target_sha256(self) -> str:
        return self._store_target.digest

    def _require_current_store(self) -> ProviderObservationStoreStatus:
        try:
            status = inspect_provider_observation_binding_store(self._store_target)
        except ProviderObservationStoreError as exc:
            raise ProviderObservationAuthorityStateError(
                "provider-observation store is unavailable"
            ) from exc
        if status.identity != self._store_identity:
            raise ProviderObservationAuthorityStateError(
                "provider-observation store identity changed"
            )
        if status.schema_sha256 != self._store_schema_sha256:
            raise ProviderObservationAuthorityStateError(
                "provider-observation store schema changed"
            )
        return status

    def _connect(self) -> sqlite3.Connection:
        before = self._require_current_store()
        connection: sqlite3.Connection | None = None
        try:
            _refuse_existing_sidecars(self.path)
            connection = _open_sqlite(self.path, mode="rw", query_only=False)
            _verify_schema(connection, self._store_target)
            after = self._require_current_store()
            if before.identity != after.identity:
                raise ProviderObservationAuthorityStateError(
                    "provider-observation store changed while opening writer"
                )
            return connection
        except ProviderObservationAuthorityStateError:
            if connection is not None:
                connection.close()
            raise
        except ProviderObservationStoreError as exc:
            if connection is not None:
                connection.close()
            raise ProviderObservationAuthorityStateError(
                "provider-observation writer connection failed"
            ) from exc

    def _connect_read_only(self) -> sqlite3.Connection:
        before = self._require_current_store()
        connection: sqlite3.Connection | None = None
        try:
            _refuse_existing_sidecars(self.path)
            connection = _open_sqlite(self.path, mode="ro", query_only=True)
            _verify_schema(connection, self._store_target)
            after = self._require_current_store()
            if before.identity != after.identity:
                raise ProviderObservationAuthorityStateError(
                    "provider-observation store changed while opening reader"
                )
            return connection
        except ProviderObservationAuthorityStateError:
            if connection is not None:
                connection.close()
            raise
        except ProviderObservationStoreError as exc:
            if connection is not None:
                connection.close()
            raise ProviderObservationAuthorityStateError(
                "provider-observation read connection failed"
            ) from exc

    def load(self, execution_id: str):
        """Load one authenticated binding through an exact read-only connection."""

        try:
            normalized_execution = _identifier(execution_id, "execution_id")
        except ValueError as exc:
            raise ProviderObservationAuthorityBindingError(
                "execution_id is malformed"
            ) from exc
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect_read_only()
            row = connection.execute(
                "SELECT * FROM provider_observation_bindings WHERE execution_id=?",
                (normalized_execution,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding SQLite read failed"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        if row is None:
            return None
        return self._authenticate_row(row)


__all__ = [
    "PreprovisionedProviderObservationBindingLedger",
    "ProviderObservationStoreError",
    "ProviderObservationStoreStatus",
    "ProviderObservationStoreTarget",
    "SCHEMA_SHA256",
    "initialize_provider_observation_binding_store",
    "inspect_provider_observation_binding_store",
]
