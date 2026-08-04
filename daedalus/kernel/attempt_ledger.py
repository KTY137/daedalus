"""Canonical Event-Store facade for restart-safe isolated Attempts."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from typing import Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.source_trees import SourceTreeStore, StoredSourceTree
from daedalus.schemas import AttemptContract, ContractProvenance, _sha256
from daedalus.spine.durability import (
    Gate0DurabilityError,
    Gate0DurabilityStatus,
    enforce_gate0_durability,
)
from daedalus.spine.envelope import canonical_json
from daedalus.spine.ledger import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTENDED,
    Intent,
    IntentAlreadyResolved,
    SpineLedger,
)

from .attempt_clock import AttemptLifecycleClock
from .attempt_contracts import (
    _ATTEMPT_EVENT_SCHEMA,
    _ATTEMPT_INTENT_KIND,
    _ATTEMPT_TERMINAL_SCHEMA,
    _MAX_REPORT_BYTES,
    _effect_key,
    _strict_json,
    _timestamp_value,
    AttemptBeginResult,
    AttemptBindingMismatch,
    AttemptCompletion,
    AttemptReplay,
    AttemptStartRecord,
    AttemptStateError,
    AttemptTerminalReceipt,
)
from .attempt_spine_reader import read_attempt_intents


class AttemptLedger:
    """Attempt lifecycle facade over the repository's single canonical event spine."""

    def __init__(
        self,
        path: str | os.PathLike[str] | SpineLedger,
        source_store: SourceTreeStore,
    ) -> None:
        if not isinstance(source_store, SourceTreeStore):
            raise AttemptStateError("source_store must be SourceTreeStore")
        self.source_store = source_store
        self.spine = path if isinstance(path, SpineLedger) else SpineLedger(path)
        if getattr(self.spine, "read_only", False):
            raise AttemptStateError(
                "attempt lifecycle requires a writable canonical event spine"
            )
        try:
            self.durability_status: Gate0DurabilityStatus = (
                enforce_gate0_durability(self.spine)
            )
        except Gate0DurabilityError as exc:
            raise AttemptStateError(
                "attempt lifecycle requires the Gate-0 Event-Store durability profile"
            ) from exc
        self.path = self.spine.path
        self._clock = AttemptLifecycleClock()
        self._install_single_start_invariant()

    def _install_single_start_invariant(self) -> None:
        """Install the Attempt index through the admitted canonical writer.

        A second SQLite connection would have its own per-connection durability
        settings and could silently fall back to ``synchronous=NORMAL``.  The
        index is therefore installed through the exact already-admitted
        ``SpineLedger`` transaction seam.
        """
        try:
            with self.spine._txn() as connection:
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_attempt_lifecycle_effect_key "
                    "ON intents(effect_key) "
                    "WHERE kind = 'attempt.lifecycle'"
                )
        except (sqlite3.DatabaseError, AttributeError) as exc:
            raise AttemptStateError(
                "canonical event spine cannot enforce one attempt start"
            ) from exc

    @staticmethod
    def _decode_start_intent(intent: Intent) -> AttemptStartRecord:
        if intent.kind != _ATTEMPT_INTENT_KIND:
            raise AttemptStateError("attempt effect key belongs to another intent kind")
        parsed = _strict_json(intent.payload_json, "persisted attempt start event")
        if canonical_json(parsed) != intent.payload_json:
            raise AttemptStateError("persisted attempt start event is noncanonical")
        expected_payload_sha = hashlib.sha256(
            intent.payload_json.encode("ascii")
        ).hexdigest()
        if intent.payload_sha != expected_payload_sha:
            raise AttemptStateError("persisted attempt start payload digest is invalid")
        if (
            set(parsed) != {"schema", "start"}
            or parsed.get("schema") != _ATTEMPT_EVENT_SCHEMA
        ):
            raise AttemptStateError("persisted attempt start event has wrong shape")
        raw_start = parsed.get("start")
        if not isinstance(raw_start, Mapping):
            raise AttemptStateError("persisted attempt start is not an object")
        try:
            start = AttemptStartRecord.from_dict(raw_start)
        except (TypeError, ValueError, KeyError) as exc:
            raise AttemptStateError("persisted attempt start is malformed") from exc
        canonical = {"schema": _ATTEMPT_EVENT_SCHEMA, "start": start.to_dict()}
        if dict(parsed) != canonical:
            raise AttemptStateError("persisted attempt start event is noncanonical")
        if intent.effect_key != _effect_key(start.attempt_id):
            raise AttemptStateError("persisted attempt effect key does not bind its start")
        if _timestamp_value(start.started_at, "started_at") > _timestamp_value(
            intent.created_ts, "intent.created_ts"
        ):
            raise AttemptStateError(
                "trusted attempt start time follows its Event-Store start event"
            )
        return start

    def _intent_for(self, attempt_id: str) -> Intent | None:
        rows = read_attempt_intents(
            self.path,
            effect_key=_effect_key(attempt_id),
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise AttemptStateError("attempt has multiple canonical event-spine starts")
        return rows[0]

    @staticmethod
    def _decode_terminal_result(
        intent: Intent,
        start: AttemptStartRecord,
    ) -> AttemptTerminalReceipt:
        result = intent.result
        if not isinstance(result, Mapping):
            raise AttemptStateError("persisted attempt terminal result is not an object")
        if set(result) != {"schema", "receipt"}:
            raise AttemptStateError("persisted attempt terminal result has wrong shape")
        if result.get("schema") != _ATTEMPT_TERMINAL_SCHEMA:
            raise AttemptStateError("persisted attempt terminal result has wrong schema")
        raw_receipt = result.get("receipt")
        if not isinstance(raw_receipt, Mapping):
            raise AttemptStateError("persisted attempt terminal receipt is not an object")
        try:
            receipt = AttemptTerminalReceipt.from_dict(raw_receipt)
        except (TypeError, ValueError, KeyError) as exc:
            raise AttemptStateError("persisted attempt terminal receipt is malformed") from exc
        canonical = {
            "schema": _ATTEMPT_TERMINAL_SCHEMA,
            "receipt": receipt.to_dict(),
        }
        if dict(result) != canonical:
            raise AttemptStateError("persisted attempt terminal result is noncanonical")
        if intent.effect_id != receipt.digest:
            raise AttemptStateError("terminal event effect_id does not bind receipt digest")
        if receipt.start_sha256 != start.digest:
            raise AttemptStateError("terminal receipt does not bind persisted start")
        if intent.resolved_ts is None:
            raise AttemptStateError("terminal attempt event is missing resolution time")
        if _timestamp_value(receipt.completed_at, "completed_at") > _timestamp_value(
            intent.resolved_ts, "intent.resolved_ts"
        ):
            raise AttemptStateError(
                "trusted attempt completion time follows its Event-Store terminal event"
            )
        return receipt

    def _completion_for(
        self,
        intent: Intent,
        start: AttemptStartRecord,
    ) -> AttemptCompletion | None:
        if intent.state == STATE_INTENDED:
            return None
        if intent.state == STATE_FAILED:
            raise AttemptStateError(
                "attempt lifecycle intent was failed outside its contract"
            )
        if intent.state != STATE_COMPLETED:
            raise AttemptStateError(
                f"unknown attempt lifecycle state: {intent.state}"
            )
        receipt = self._decode_terminal_result(intent, start)
        self.source_store.read_bytes(receipt.report, max_bytes=_MAX_REPORT_BYTES)
        if receipt.candidate_tree is not None:
            candidate = self.source_store.load_tree(receipt.candidate_tree)
            if candidate.source_revision != receipt.source_revision:
                raise AttemptStateError(
                    "persisted candidate tree revision differs from terminal receipt"
                )
        return AttemptCompletion(start=start, receipt=receipt)

    def begin(
        self,
        attempt: AttemptContract,
        input_tree: StoredSourceTree,
        *,
        start_id: str,
        workspace_parent_sha256: str,
        workspace_relative_path: str,
        started_at: str | None = None,
    ) -> AttemptBeginResult:
        """Persist one start using trusted kernel time.

        ``started_at`` is retained only as a source-compatibility adapter for
        the unmerged predecessor API. Its value is deliberately ignored and
        never enters a security record.
        """
        del started_at
        if not isinstance(attempt, AttemptContract):
            raise AttemptBindingMismatch("attempt must be a canonical AttemptContract")
        if not isinstance(input_tree, StoredSourceTree):
            raise AttemptBindingMismatch("input_tree must be StoredSourceTree")
        loaded = self.source_store.load_tree(input_tree.ref)
        if loaded != input_tree.manifest:
            raise AttemptBindingMismatch(
                "input tree manifest differs from the ledger CAS object"
            )
        if loaded.source_revision != attempt.base_revision:
            raise AttemptBindingMismatch(
                "input source tree revision must equal attempt base revision"
            )
        parent_digest = _sha256(
            workspace_parent_sha256,
            "workspace_parent_sha256",
        )
        trusted_started_at = self._clock.now()
        start = AttemptStartRecord(
            start_id=start_id,
            attempt_id=attempt.attempt_id,
            attempt_sha256=attempt.digest,
            source_revision=attempt.base_revision,
            input_tree=input_tree.ref,
            workspace_parent_sha256=parent_digest,
            workspace_relative_path=workspace_relative_path,
            started_at=trusted_started_at,
            provenance=ContractProvenance(
                origin="kernel.attempt-ledger.begin",
                source_revision=attempt.base_revision,
                created_at=trusted_started_at,
                input_digests=tuple(
                    sorted(
                        {
                            attempt.digest,
                            input_tree.ref.sha256,
                            parent_digest,
                        }
                    )
                ),
                trace_id=attempt.attempt_id,
            ),
        )
        existing = self._intent_for(attempt.attempt_id)
        created = False
        if existing is None:
            payload = {"schema": _ATTEMPT_EVENT_SCHEMA, "start": start.to_dict()}
            try:
                existing = self.spine.record_intent(
                    _ATTEMPT_INTENT_KIND,
                    payload,
                    effect_key=_effect_key(attempt.attempt_id),
                    trace_id=attempt.attempt_id,
                )
                created = True
            except sqlite3.IntegrityError:
                existing = self._intent_for(attempt.attempt_id)
                if existing is None:
                    raise AttemptStateError(
                        "concurrent attempt start conflicted without persisted winner"
                    )
        persisted = self._decode_start_intent(existing)
        if not persisted.same_subject(start):
            raise AttemptReplay(
                "attempt_id was already started with different material"
            )
        completion = self._completion_for(existing, persisted)
        return AttemptBeginResult(
            start=persisted,
            execute=created,
            completion=completion,
        )

    def complete(
        self,
        start: AttemptStartRecord,
        *,
        receipt_id: str,
        outcome: str,
        report: ArtifactRef,
        candidate_tree: StoredSourceTree | None,
        completed_at: str | None = None,
    ) -> AttemptCompletion:
        """Persist one terminal receipt using trusted monotonic kernel time.

        ``completed_at`` is a compatibility-only predecessor argument. Caller
        time is ignored; terminal time is generated by the lifecycle clock and
        forced to follow the persisted start.
        """
        del completed_at
        if not isinstance(start, AttemptStartRecord):
            raise AttemptBindingMismatch("start must be AttemptStartRecord")
        if not isinstance(report, ArtifactRef):
            raise AttemptBindingMismatch("report must be ArtifactRef")
        self.source_store.read_bytes(report, max_bytes=_MAX_REPORT_BYTES)
        candidate_ref = None
        if candidate_tree is not None:
            if not isinstance(candidate_tree, StoredSourceTree):
                raise AttemptBindingMismatch(
                    "candidate_tree must be StoredSourceTree or null"
                )
            loaded_candidate = self.source_store.load_tree(candidate_tree.ref)
            if loaded_candidate != candidate_tree.manifest:
                raise AttemptBindingMismatch(
                    "candidate tree manifest differs from the ledger CAS object"
                )
            if loaded_candidate.source_revision != start.source_revision:
                raise AttemptBindingMismatch(
                    "candidate source tree revision must equal attempt source revision"
                )
            candidate_ref = candidate_tree.ref
        trusted_completed_at = self._clock.now(minimum=start.started_at)
        receipt = AttemptTerminalReceipt(
            receipt_id=receipt_id,
            start_sha256=start.digest,
            attempt_id=start.attempt_id,
            attempt_sha256=start.attempt_sha256,
            source_revision=start.source_revision,
            input_tree_sha256=start.input_tree.sha256,
            outcome=outcome,
            report=report,
            candidate_tree=candidate_ref,
            completed_at=trusted_completed_at,
            provenance=ContractProvenance(
                origin="kernel.attempt-ledger.complete",
                source_revision=start.source_revision,
                created_at=trusted_completed_at,
                input_digests=tuple(
                    sorted(
                        {
                            start.digest,
                            start.attempt_sha256,
                            start.input_tree.sha256,
                            report.sha256,
                            *(
                                (candidate_ref.sha256,)
                                if candidate_ref is not None
                                else ()
                            ),
                        }
                    )
                ),
                trace_id=start.attempt_id,
            ),
        )
        intent = self._intent_for(start.attempt_id)
        if intent is None:
            raise AttemptStateError("attempt start is not persisted")
        persisted_start = self._decode_start_intent(intent)
        if persisted_start != start:
            raise AttemptBindingMismatch("submitted start differs from persisted start")
        existing = self._completion_for(intent, persisted_start)
        if existing is not None:
            if not existing.receipt.same_subject(receipt):
                raise AttemptReplay("attempt already has a different terminal receipt")
            return existing
        result = {
            "schema": _ATTEMPT_TERMINAL_SCHEMA,
            "receipt": receipt.to_dict(),
        }
        try:
            terminal = self.spine.mark_completed(
                intent.id,
                effect_id=receipt.digest,
                result=result,
            )
        except IntentAlreadyResolved:
            terminal = self._intent_for(start.attempt_id)
            if terminal is None:
                raise AttemptStateError(
                    "resolved attempt disappeared from event spine"
                )
        completion = self._completion_for(terminal, persisted_start)
        if completion is None:
            raise AttemptStateError(
                "terminal event spine resolution was not retained"
            )
        if not completion.receipt.same_subject(receipt):
            raise AttemptReplay("attempt already has a different terminal receipt")
        return completion

    def pending(self) -> tuple[AttemptStartRecord, ...]:
        starts = [
            self._decode_start_intent(intent)
            for intent in read_attempt_intents(self.path)
            if intent.state == STATE_INTENDED
        ]
        return tuple(sorted(starts, key=lambda start: start.attempt_id))


__all__ = ["AttemptLedger"]
