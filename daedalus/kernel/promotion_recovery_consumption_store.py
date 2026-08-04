"""Pre-provisioned store boundary for promotion recovery consumption.

This module is a narrow strangler around ``PromotionRecoveryConsumptionLedger``.
It separates explicit schema publication from normal ledger construction and
ensures normal writer opens use SQLite ``mode=rw`` so a missing store cannot be
created accidentally. It does not issue an owner decision, consume one by
itself, cancel an Effect Lease, invoke Git, mutate a checkout, or promote.

The historical ledger remains available for compatibility. Production caller
migration and canonical Effect-Lease/runtime/sandbox composition are separate
reviewed packets.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .promotion_recovery_consumption import (
    PromotionRecoveryConsumptionLedger,
    PromotionRecoveryConsumptionStateError,
)


class PromotionRecoveryConsumptionStoreError(RuntimeError):
    """Fail-closed error for pre-provisioned store operations."""


_TABLE = "promotion_recovery_consumptions_v1"
_SCHEMA_VERSION = 1
_COLUMNS = (
    "decision_sha256",
    "decision_id",
    "owner_id",
    "key_id",
    "nonce",
    "operation",
    "promotion_authorization_sha256",
    "recovery_plan_sha256",
    "effect_start_receipt_sha256",
    "source_revision",
    "issued_at",
    "expires_at",
    "signature_sha256",
    "expectation_sha256",
    "verified_sha256",
    "consumed_at",
    "consumption_sha256",
    "decision_json",
    "expectation_json",
    "consumption_json",
)
_UNIQUE_CONSTRAINTS = tuple(
    sorted(
        (
            ("decision_sha256",),
            ("decision_id",),
            ("promotion_authorization_sha256",),
            ("recovery_plan_sha256",),
            ("effect_start_receipt_sha256",),
            ("expectation_sha256",),
            ("verified_sha256",),
            ("consumption_sha256",),
            ("owner_id", "key_id", "nonce"),
        )
    )
)
_UNIQUE_INDEX_CONTRACT = tuple(
    sorted(
        (
            (("decision_sha256",), "pk", 0),
            (("decision_id",), "u", 0),
            (("promotion_authorization_sha256",), "u", 0),
            (("recovery_plan_sha256",), "u", 0),
            (("effect_start_receipt_sha256",), "u", 0),
            (("expectation_sha256",), "u", 0),
            (("verified_sha256",), "u", 0),
            (("consumption_sha256",), "u", 0),
            (("owner_id", "key_id", "nonce"), "u", 0),
        )
    )
)
_SCHEMA_SQL = f"""
CREATE TABLE {_TABLE} (
    decision_sha256 TEXT NOT NULL PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    key_id TEXT NOT NULL,
    nonce TEXT NOT NULL,
    operation TEXT NOT NULL,
    promotion_authorization_sha256 TEXT NOT NULL UNIQUE,
    recovery_plan_sha256 TEXT NOT NULL UNIQUE,
    effect_start_receipt_sha256 TEXT NOT NULL UNIQUE,
    source_revision TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    signature_sha256 TEXT NOT NULL,
    expectation_sha256 TEXT NOT NULL UNIQUE,
    verified_sha256 TEXT NOT NULL UNIQUE,
    consumed_at TEXT NOT NULL,
    consumption_sha256 TEXT NOT NULL UNIQUE,
    decision_json TEXT NOT NULL,
    expectation_json TEXT NOT NULL,
    consumption_json TEXT NOT NULL,
    UNIQUE(owner_id, key_id, nonce)
)
""".strip()


def _normalized_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


_SCHEMA_DESCRIPTOR = {
    "schema_version": _SCHEMA_VERSION,
    "table": _TABLE,
    "columns": list(_COLUMNS),
    "sql": _normalized_sql(_SCHEMA_SQL),
    "unique_index_contract": [
        {"columns": list(columns), "origin": origin, "partial": partial}
        for columns, origin, partial in _UNIQUE_INDEX_CONTRACT
    ],
}
SCHEMA_SHA256 = hashlib.sha256(
    json.dumps(
        _SCHEMA_DESCRIPTOR,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
).hexdigest()


@dataclass(frozen=True)
class PromotionRecoveryConsumptionStoreStatus:
    """Strict immutable projection of one initialized store."""

    path: str
    file_device: int
    file_inode: int
    file_size: int
    file_mtime_ns: int
    schema_version: int
    columns: tuple[str, ...]
    unique_constraints: tuple[tuple[str, ...], ...]
    schema_sha256: str

    @property
    def identity(self) -> tuple[int, int]:
        return (self.file_device, self.file_inode)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "file_device": self.file_device,
            "file_inode": self.file_inode,
            "file_size": self.file_size,
            "file_mtime_ns": self.file_mtime_ns,
            "schema_version": self.schema_version,
            "columns": list(self.columns),
            "unique_constraints": [list(item) for item in self.unique_constraints],
            "schema_sha256": self.schema_sha256,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normal(value: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(value))))


def _lexical_path(path: str | os.PathLike[str]) -> Path:
    if isinstance(path, bool):
        raise TypeError("recovery consumption store path must be path-like")
    try:
        value = Path(path)
    except TypeError as exc:
        raise TypeError("recovery consumption store path must be path-like") from exc
    if not value.name or value.name in {".", ".."}:
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store requires a file name"
        )
    return Path(os.path.abspath(os.fspath(value)))


def _resolved_parent(path: Path) -> Path:
    lexical_parent = path.parent
    try:
        resolved_parent = lexical_parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store parent must already exist"
        ) from exc
    try:
        mode = resolved_parent.stat().st_mode
    except OSError as exc:
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store parent is unavailable"
        ) from exc
    if not stat.S_ISDIR(mode):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store parent must be a directory"
        )
    if _normal(lexical_parent) != _normal(resolved_parent):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store parent may not traverse symlinks"
        )
    return resolved_parent


def _existing_store(path: str | os.PathLike[str]) -> tuple[Path, os.stat_result]:
    lexical = _lexical_path(path)
    _resolved_parent(lexical)
    if os.path.lexists(lexical) and lexical.is_symlink():
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store may not be a symlink"
        )
    try:
        resolved = lexical.resolve(strict=True)
        before = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store is unavailable"
        ) from exc
    if _normal(lexical) != _normal(resolved):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store path may not be redirected"
        )
    if not stat.S_ISREG(before.st_mode):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store must be a regular file"
        )
    return resolved, before


def _connection_contract(
    connection: sqlite3.Connection,
) -> tuple[int, tuple[str, ...], tuple[tuple[str, ...], ...]]:
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store failed integrity_check"
            )
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        object_rows = connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        if len(object_rows) != 1:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store contains unexpected schema objects"
            )
        object_type, object_name, object_sql = object_rows[0]
        if object_type != "table" or object_name != _TABLE:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store table identity does not match"
            )
        if not isinstance(object_sql, str) or _normalized_sql(object_sql) != (
            _normalized_sql(_SCHEMA_SQL)
        ):
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store table SQL does not match"
            )

        table_rows = connection.execute(f"PRAGMA table_info({_TABLE})").fetchall()
        columns = tuple(str(row[1]) for row in table_rows)
        if columns != _COLUMNS:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store columns do not match the exact contract"
            )
        if any(str(row[2]).upper() != "TEXT" for row in table_rows):
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store column types do not match the contract"
            )
        if tuple(int(row[3]) for row in table_rows) != (1,) * len(_COLUMNS):
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store nullability does not match the contract"
            )
        if any(row[4] is not None for row in table_rows):
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store defaults do not match the contract"
            )
        if tuple(int(row[5]) for row in table_rows) != (1,) + (0,) * (
            len(_COLUMNS) - 1
        ):
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store primary key does not match the contract"
            )

        unique_index_contract: list[tuple[tuple[str, ...], str, int]] = []
        for row in connection.execute(f"PRAGMA index_list({_TABLE})").fetchall():
            if int(row[2]) != 1:
                raise PromotionRecoveryConsumptionStoreError(
                    "recovery consumption store contains a nonunique index"
                )
            index_name = str(row[1])
            columns_for_index = tuple(
                str(item[2])
                for item in connection.execute(
                    f"PRAGMA index_info({json.dumps(index_name)})"
                ).fetchall()
            )
            if not columns_for_index:
                raise PromotionRecoveryConsumptionStoreError(
                    "recovery consumption store has an empty unique index"
                )
            unique_index_contract.append(
                (columns_for_index, str(row[3]), int(row[4]))
            )
        projected_contract = tuple(sorted(unique_index_contract))
        if projected_contract != _UNIQUE_INDEX_CONTRACT:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store unique indexes do not match"
            )
        unique_constraints = tuple(
            columns for columns, _origin, _partial in projected_contract
        )
        if unique_constraints != _UNIQUE_CONSTRAINTS:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store unique constraints do not match"
            )
        if schema_version != _SCHEMA_VERSION:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store schema version does not match"
            )
        return schema_version, columns, unique_constraints
    except PromotionRecoveryConsumptionStoreError:
        raise
    except (sqlite3.Error, TypeError, ValueError, IndexError) as exc:
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store schema could not be verified"
        ) from exc


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro",
            uri=True,
            isolation_level=None,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store reader did not enter query-only mode"
            )
        return connection
    except PromotionRecoveryConsumptionStoreError:
        if connection is not None:
            connection.close()
        raise
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store could not be opened read-only"
        ) from exc


def inspect_promotion_recovery_consumption_store(
    path: str | os.PathLike[str],
) -> PromotionRecoveryConsumptionStoreStatus:
    """Verify one existing store without creating or mutating it."""

    resolved, before = _existing_store(path)
    connection = _open_read_only(resolved)
    try:
        schema_version, columns, unique_constraints = _connection_contract(connection)
    finally:
        connection.close()
    try:
        after = resolved.stat()
    except OSError as exc:
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store disappeared during inspection"
        ) from exc
    before_identity = (int(before.st_dev), int(before.st_ino))
    after_identity = (int(after.st_dev), int(after.st_ino))
    if before_identity != after_identity:
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store identity changed during inspection"
        )
    if int(before.st_size) != int(after.st_size):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store size changed during inspection"
        )
    if int(before.st_mtime_ns) != int(after.st_mtime_ns):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store modification time changed during inspection"
        )
    return PromotionRecoveryConsumptionStoreStatus(
        path=str(resolved),
        file_device=int(after.st_dev),
        file_inode=int(after.st_ino),
        file_size=int(after.st_size),
        file_mtime_ns=int(after.st_mtime_ns),
        schema_version=schema_version,
        columns=columns,
        unique_constraints=unique_constraints,
        schema_sha256=SCHEMA_SHA256,
    )


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_identity(path: Path) -> tuple[int, int]:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption publication target must remain a regular file"
        )
    return (int(metadata.st_dev), int(metadata.st_ino))


def _remove_own_publication(
    target: Path,
    published_identity: tuple[int, int] | None,
) -> None:
    if published_identity is None:
        return
    try:
        current_identity = _file_identity(target)
    except (FileNotFoundError, OSError, PromotionRecoveryConsumptionStoreError):
        return
    if current_identity != published_identity:
        return
    try:
        target.unlink()
    except OSError:
        pass


def initialize_promotion_recovery_consumption_store(
    path: str | os.PathLike[str],
) -> PromotionRecoveryConsumptionStoreStatus:
    """Create and atomically publish one exact empty store.

    The parent directory must already exist and may not be reached through a
    symlink. Publication uses a same-directory hard link so an existing target
    is never replaced. This function is intentionally effectful and is not yet
    claimed as centrally leased production wiring.
    """

    lexical = _lexical_path(path)
    parent = _resolved_parent(lexical)
    target = parent / lexical.name
    if os.path.lexists(target):
        raise PromotionRecoveryConsumptionStoreError(
            "recovery consumption store target already exists"
        )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".initializing",
        dir=parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    published_identity: tuple[int, int] | None = None
    connection: sqlite3.Connection | None = None
    try:
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        connection = sqlite3.connect(
            temporary.as_uri() + "?mode=rw",
            uri=True,
            isolation_level=None,
            timeout=30,
        )
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_SCHEMA_SQL)
        connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        connection.execute("COMMIT")
        _connection_contract(connection)
        connection.close()
        connection = None
        _fsync_file(temporary)
        temporary_identity = _file_identity(temporary)
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store target appeared during publication"
            ) from exc
        except OSError as exc:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption store could not be published atomically"
            ) from exc
        published_identity = temporary_identity
        if _file_identity(target) != published_identity:
            raise PromotionRecoveryConsumptionStoreError(
                "recovery consumption publication identity does not match"
            )
        _fsync_file(target)
        return inspect_promotion_recovery_consumption_store(target)
    except Exception:
        if connection is not None:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            connection.close()
        _remove_own_publication(target, published_identity)
        raise
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


class PreprovisionedPromotionRecoveryConsumptionLedger(
    PromotionRecoveryConsumptionLedger
):
    """Compatibility-preserving ledger that requires an initialized store."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        status = inspect_promotion_recovery_consumption_store(path)
        self.path = Path(status.path)
        self._clock = clock or _utc_now
        self._store_identity = status.identity
        self._store_schema_sha256 = status.schema_sha256

    @property
    def store_status(self) -> PromotionRecoveryConsumptionStoreStatus:
        status = inspect_promotion_recovery_consumption_store(self.path)
        self._require_same_store(status)
        return status

    def _require_same_store(
        self,
        status: PromotionRecoveryConsumptionStoreStatus,
    ) -> None:
        if status.identity != self._store_identity:
            raise PromotionRecoveryConsumptionStateError(
                "recovery consumption store identity changed after admission"
            )
        if status.schema_sha256 != self._store_schema_sha256:
            raise PromotionRecoveryConsumptionStateError(
                "recovery consumption store schema changed after admission"
            )

    def _connect_verified(self, *, read_only: bool) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            status = inspect_promotion_recovery_consumption_store(self.path)
            self._require_same_store(status)
            mode = "ro" if read_only else "rw"
            connection = sqlite3.connect(
                self.path.as_uri() + f"?mode={mode}",
                uri=True,
                isolation_level=None,
                timeout=30,
            )
            connection.row_factory = sqlite3.Row
            if read_only:
                connection.execute("PRAGMA query_only=ON")
                if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
                    raise PromotionRecoveryConsumptionStoreError(
                        "recovery consumption reader did not enter query-only mode"
                    )
            else:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("PRAGMA busy_timeout=30000")
                if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 0:
                    raise PromotionRecoveryConsumptionStoreError(
                        "recovery consumption writer is unexpectedly query-only"
                    )
            _connection_contract(connection)
            after = inspect_promotion_recovery_consumption_store(self.path)
            self._require_same_store(after)
            return connection
        except PromotionRecoveryConsumptionStateError:
            if connection is not None:
                connection.close()
            raise
        except (PromotionRecoveryConsumptionStoreError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise PromotionRecoveryConsumptionStateError(
                "pre-provisioned recovery consumption store open refused"
            ) from exc

    def _connect_writer(self) -> sqlite3.Connection:
        return self._connect_verified(read_only=False)

    def _connect_read_only(self) -> sqlite3.Connection:
        return self._connect_verified(read_only=True)
