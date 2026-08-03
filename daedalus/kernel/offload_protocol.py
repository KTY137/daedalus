"""Deterministic prompt/request protocol for one Gate-0 Ollama rewrite.

This module is pure.  It performs no provider, filesystem, ledger, or process
effect.  The frozen bytes are built from the canonical Attempt and observed
target, then their hashes are compared with :class:`OffloadExecutionPlan`
before an executor may consume effect authority.

The model remains a proposer.  Structured decoding narrows its output shape;
it does not make the output evidence.  A later independent gate must judge the
candidate bytes written into the isolated TaskAttempt worktree.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from daedalus.kernel.contracts import OffloadExecutionPlan
from daedalus.kernel.offload_observations import TargetBeforeObservation
from daedalus.schemas import AttemptContract
from daedalus.spine.envelope import canonical_json


OFFLOAD_SYSTEM_TEMPLATE = (
    "You are a bounded source-rewrite proposer. Rewrite only the supplied "
    "existing target to satisfy the instruction. Preserve unrelated behavior. "
    "Return only the schema-constrained JSON value. Do not claim that tests "
    "passed; an independent evaluator runs after your proposal."
)


class OffloadProtocolError(ValueError):
    """Frozen protocol bytes are invalid or disagree with the plan."""


@dataclass(frozen=True, slots=True)
class OffloadProtocolBundle:
    """Exact pre-plan bytes and their deterministic identities."""

    prompt_template_bytes: bytes
    prompt_bytes: bytes
    response_schema_bytes: bytes
    ollama_request_bytes: bytes

    @property
    def prompt_template_sha256(self) -> str:
        return hashlib.sha256(self.prompt_template_bytes).hexdigest()

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt_bytes).hexdigest()

    @property
    def response_schema_sha256(self) -> str:
        return hashlib.sha256(self.response_schema_bytes).hexdigest()

    @property
    def ollama_request_sha256(self) -> str:
        return hashlib.sha256(self.ollama_request_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class ParsedOffloadCandidate:
    """One inert candidate extracted from a complete raw Ollama response."""

    target_path: str
    content_bytes: bytes
    raw_response_sha256: str
    assistant_content_sha256: str

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content_bytes).hexdigest()


def _ascii_json_bytes(value: object) -> bytes:
    return canonical_json(value).encode("ascii")


def _strict_json(raw: bytes, *, role: str) -> Any:
    if not isinstance(raw, bytes):
        raise OffloadProtocolError(f"{role} must be bytes")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise OffloadProtocolError(f"{role} must be strict UTF-8 JSON") from exc

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OffloadProtocolError(
                    f"{role} contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise OffloadProtocolError(f"{role} contains invalid number {value}")

    try:
        return json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except OffloadProtocolError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OffloadProtocolError(f"{role} is not valid JSON") from exc


def _response_schema(target_path: str) -> dict[str, object]:
    return {
        "additionalProperties": False,
        "properties": {
            "content": {"type": "string"},
            "target_path": {"const": target_path, "type": "string"},
        },
        "required": ["target_path", "content"],
        "type": "object",
    }


def freeze_offload_protocol(
    *,
    attempt: AttemptContract,
    target_before: TargetBeforeObservation,
    target_before_bytes: bytes,
    model_id: str,
    num_ctx: int,
    num_predict: int,
    seed: int,
    temperature_milli: int,
    keep_alive: str,
) -> OffloadProtocolBundle:
    """Build the sole supported request shape from canonical observed inputs."""

    if not isinstance(attempt, AttemptContract):
        raise OffloadProtocolError("attempt must be an AttemptContract")
    if not isinstance(target_before, TargetBeforeObservation):
        raise OffloadProtocolError(
            "target_before must be a TargetBeforeObservation"
        )
    if not isinstance(target_before_bytes, bytes):
        raise OffloadProtocolError("target_before_bytes must be bytes")
    try:
        target_text = target_before_bytes.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise OffloadProtocolError("target_before_bytes must be strict UTF-8") from exc
    if hashlib.sha256(target_before_bytes).hexdigest() != target_before.content_sha256:
        raise OffloadProtocolError("target_before_bytes digest mismatches observation")
    if len(target_before_bytes) != target_before.byte_length:
        raise OffloadProtocolError("target_before_bytes size mismatches observation")
    if target_before.source_revision != attempt.base_revision:
        raise OffloadProtocolError("target and attempt source revisions differ")
    if target_before.target_path not in attempt.writable_paths:
        raise OffloadProtocolError("target is outside the Attempt writable paths")
    if len(attempt.writable_paths) != 1:
        raise OffloadProtocolError("bounded offload requires one writable target")
    if (
        isinstance(num_ctx, bool)
        or not isinstance(num_ctx, int)
        or isinstance(num_predict, bool)
        or not isinstance(num_predict, int)
        or num_predict < 1
        or num_predict >= num_ctx
    ):
        raise OffloadProtocolError(
            "num_predict must be positive and smaller than num_ctx"
        )
    if isinstance(temperature_milli, bool) or temperature_milli != 0:
        raise OffloadProtocolError("temperature_milli must be exactly 0")
    if keep_alive != "0":
        raise OffloadProtocolError("keep_alive must be exactly '0'")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise OffloadProtocolError("seed must be a non-negative integer")
    if not isinstance(model_id, str) or not model_id:
        raise OffloadProtocolError("model_id must be non-empty")

    template_bytes = OFFLOAD_SYSTEM_TEMPLATE.encode("utf-8")
    user_payload = canonical_json(
        {
            "instruction": attempt.instruction,
            "source_revision": attempt.base_revision,
            "target_before_sha256": target_before.content_sha256,
            "target_path": target_before.target_path,
            "target_text": target_text,
        }
    )
    messages = [
        {"content": OFFLOAD_SYSTEM_TEMPLATE, "role": "system"},
        {"content": user_payload, "role": "user"},
    ]
    prompt_bytes = _ascii_json_bytes(messages)
    # Byte-count <= token-count is deliberately conservative: byte-fallback
    # tokenizers can consume one token per byte.  Refuse rather than let Ollama
    # head-truncate the system instruction or source content.
    available_input_tokens = num_ctx - num_predict
    if len(prompt_bytes) > available_input_tokens:
        raise OffloadProtocolError(
            "canonical prompt bytes exceed the conservative input-token budget"
        )

    response_schema = _response_schema(target_before.target_path)
    response_schema_bytes = _ascii_json_bytes(response_schema)
    request = {
        "format": response_schema,
        "keep_alive": keep_alive,
        "messages": messages,
        "model": model_id,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "seed": seed,
            "temperature": temperature_milli / 1000,
        },
        "stream": False,
    }
    return OffloadProtocolBundle(
        prompt_template_bytes=template_bytes,
        prompt_bytes=prompt_bytes,
        response_schema_bytes=response_schema_bytes,
        ollama_request_bytes=_ascii_json_bytes(request),
    )


def verify_offload_protocol(
    *,
    plan: OffloadExecutionPlan,
    attempt: AttemptContract,
    target_before: TargetBeforeObservation,
    target_before_bytes: bytes,
    bundle: OffloadProtocolBundle,
) -> None:
    """Rebuild and compare every byte before any effect authority is consumed."""

    if not isinstance(plan, OffloadExecutionPlan):
        raise OffloadProtocolError("plan must be an OffloadExecutionPlan")
    if not isinstance(bundle, OffloadProtocolBundle):
        raise OffloadProtocolError("bundle must be an OffloadProtocolBundle")
    expected = freeze_offload_protocol(
        attempt=attempt,
        target_before=target_before,
        target_before_bytes=target_before_bytes,
        model_id=plan.model_id,
        num_ctx=plan.num_ctx,
        num_predict=plan.num_predict,
        seed=plan.seed,
        temperature_milli=plan.temperature_milli,
        keep_alive=plan.keep_alive,
    )
    mismatches = [
        name
        for name in (
            "prompt_template_bytes",
            "prompt_bytes",
            "response_schema_bytes",
            "ollama_request_bytes",
        )
        if getattr(bundle, name) != getattr(expected, name)
    ]
    digest_mismatches = [
        name
        for name, actual, expected_digest in (
            (
                "prompt_template_sha256",
                bundle.prompt_template_sha256,
                plan.prompt_template_sha256,
            ),
            ("prompt_sha256", bundle.prompt_sha256, plan.prompt_sha256),
            (
                "response_schema_sha256",
                bundle.response_schema_sha256,
                plan.response_schema_sha256,
            ),
            (
                "ollama_request_sha256",
                bundle.ollama_request_sha256,
                plan.ollama_request_sha256,
            ),
        )
        if actual != expected_digest
    ]
    failures = sorted((*mismatches, *digest_mismatches))
    if failures:
        raise OffloadProtocolError(
            "offload protocol binding mismatch: " + ", ".join(failures)
        )


def parse_offload_chat_response(
    *,
    raw_response_bytes: bytes,
    plan: OffloadExecutionPlan,
    target_before: TargetBeforeObservation,
) -> ParsedOffloadCandidate:
    """Extract one strict candidate from a complete native Ollama response."""

    if not isinstance(plan, OffloadExecutionPlan):
        raise OffloadProtocolError("plan must be an OffloadExecutionPlan")
    if not isinstance(target_before, TargetBeforeObservation):
        raise OffloadProtocolError(
            "target_before must be a TargetBeforeObservation"
        )
    if not isinstance(raw_response_bytes, bytes):
        raise OffloadProtocolError("raw_response_bytes must be bytes")
    if len(raw_response_bytes) > plan.max_response_bytes:
        raise OffloadProtocolError("raw chat response exceeds the plan byte cap")
    payload = _strict_json(raw_response_bytes, role="Ollama chat response")
    if not isinstance(payload, dict):
        raise OffloadProtocolError("Ollama chat response must be an object")
    if payload.get("model") != plan.model_id:
        raise OffloadProtocolError("Ollama chat response model mismatches plan")
    if payload.get("done") is not True:
        raise OffloadProtocolError("Ollama chat response must be complete")
    if "error" in payload:
        raise OffloadProtocolError("Ollama chat response contains an error")
    done_reason = payload.get("done_reason")
    if done_reason is not None and done_reason != "stop":
        raise OffloadProtocolError(
            "Ollama chat response did not finish with stop"
        )
    message = payload.get("message")
    if not isinstance(message, dict) or set(message) != {"role", "content"}:
        raise OffloadProtocolError(
            "Ollama chat message must contain only role and content"
        )
    if message.get("role") != "assistant" or not isinstance(
        message.get("content"), str
    ):
        raise OffloadProtocolError("Ollama chat message is not assistant text")
    assistant_content = message["content"]
    candidate_payload = _strict_json(
        assistant_content.encode("utf-8"), role="assistant candidate"
    )
    if not isinstance(candidate_payload, dict) or set(candidate_payload) != {
        "content",
        "target_path",
    }:
        raise OffloadProtocolError(
            "assistant candidate must contain exactly target_path and content"
        )
    if candidate_payload.get("target_path") != target_before.target_path:
        raise OffloadProtocolError("assistant candidate targets a different path")
    content = candidate_payload.get("content")
    if not isinstance(content, str):
        raise OffloadProtocolError("assistant candidate content must be text")
    if "\x00" in content:
        raise OffloadProtocolError("assistant candidate content contains NUL")
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > plan.max_response_bytes:
        raise OffloadProtocolError("assistant candidate exceeds the plan byte cap")
    return ParsedOffloadCandidate(
        target_path=target_before.target_path,
        content_bytes=content_bytes,
        raw_response_sha256=hashlib.sha256(raw_response_bytes).hexdigest(),
        assistant_content_sha256=hashlib.sha256(
            assistant_content.encode("utf-8")
        ).hexdigest(),
    )


__all__ = [
    "OFFLOAD_SYSTEM_TEMPLATE",
    "OffloadProtocolBundle",
    "OffloadProtocolError",
    "ParsedOffloadCandidate",
    "freeze_offload_protocol",
    "parse_offload_chat_response",
    "verify_offload_protocol",
]
