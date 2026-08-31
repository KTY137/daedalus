"""Contracts for the G1-MUT-02E event-time runner transport repair."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_attempt_event_time_window_mutations as runner


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/run_attempt_event_time_window_mutations.py"
TARGET = ROOT / "daedalus/kernel/attempt_spine_reader.py"
EXPECTED_TESTS = (
    "tests/kernel/test_isolated_attempt_time_tampering.py",
    "tests/kernel/test_isolated_attempt_time_and_preflight.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
    "tests/kernel/test_isolated_attempt_spine_wire_review.py",
)
EXPECTED_MUTATION_IDS = (
    "accept-arbitrary-historical-record-time",
    "accept-record-time-after-event",
    "skip-terminal-time-binding",
)
EXPECTED_MUTATION_DIGEST = (
    "9f45fb294da71fd707f08de8b559a9c64f75908e08b584d6cddef4cfa2d93211"
)
EXPECTED_RUNNER_TEXT_SHA256 = (
    "9ee0814654b99c984e0cf002f71087877db01cf19948c9d3db5ef7cf038ca300"
)


def _mutations() -> tuple[tuple[str, str, str], ...]:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "mutations"
            for target in node.targets
        )
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, tuple)
    return value


def _git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def test_frozen_tests_mutants_and_runner_digest_are_exact() -> None:
    mutations = _mutations()
    encoded = json.dumps(
        mutations,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert runner.TESTS == EXPECTED_TESTS
    assert tuple(mutation[0] for mutation in mutations) == EXPECTED_MUTATION_IDS
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED_MUTATION_DIGEST
    normalized_runner = RUNNER.read_text(encoding="utf-8").encode("utf-8")
    assert (
        hashlib.sha256(normalized_runner).hexdigest()
        == EXPECTED_RUNNER_TEXT_SHA256
    )


def test_every_frozen_anchor_applies_once_to_the_current_crlf_target() -> None:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    crlf_count = original.count(b"\r\n")
    lf_count = original.count(b"\n")
    assert lf_count > 0
    assert crlf_count in {0, lf_count}
    for label, old, new in _mutations():
        mutated = runner._replace_once(source, old, new, label)
        assert mutated != source
        assert "\r\n" in mutated
        assert "\r\r\n" not in mutated
    assert _git_blob_sha1(TARGET.read_bytes()) == _git_blob_sha1(original)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_transport_preserves_the_selected_line_ending_byte_for_byte(
    tmp_path: Path,
    newline: str,
) -> None:
    _, old, new = _mutations()[1]
    source = ("prefix\n" + old + "suffix\n").replace("\n", newline)
    expected = ("prefix\n" + new + "suffix\n").replace("\n", newline)
    mutated = runner._replace_once(source, old, new, "synthetic")
    assert mutated == expected

    target = tmp_path / "subject.py"
    runner._write(target, mutated)
    assert target.read_bytes() == expected.encode("utf-8")


def test_transport_refuses_absent_or_ambiguous_anchors() -> None:
    with pytest.raises(RuntimeError, match="found 0"):
        runner._replace_once("unrelated\r\n", "anchor\n", "replacement\n", "x")
    with pytest.raises(RuntimeError, match="found 2"):
        runner._replace_once("anchor\r\nanchor\r\n", "anchor\n", "x\n", "x")


def test_mutate_then_restore_keeps_the_exact_original_blob(tmp_path: Path) -> None:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    subject = tmp_path / "attempt_spine_reader.py"
    subject.write_bytes(original)
    for label, old, new in _mutations():
        runner._write(subject, runner._replace_once(source, old, new, label))
        assert subject.read_bytes() != original
        subject.write_bytes(original)
        assert subject.read_bytes() == original
    assert _git_blob_sha1(subject.read_bytes()) == _git_blob_sha1(original)
