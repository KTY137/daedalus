"""Read an explicitly owner-configured test profile outside candidate trees.

There is intentionally no writer/tool here. The model can select the profile,
not its argv, tests, timeout, acknowledgement or location. This is configuration,
not an isolation guarantee: the existing evaluator's limits remain explicit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daedalus.ariadne.campaign import TestCommandEvaluator, _admit_test_evaluator
from daedalus.gates.repository.tree import read_repository_source
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.killswitch import control_root

PROFILE_NAME = "ariadne-test-evaluator.json"
PROFILE_SCHEMA = "daedalus-owner-ariadne-evaluator/1"
MAX_PROFILE_BYTES = 65_536


@dataclass(frozen=True)
class OwnerTestProfile:
    evaluator: TestCommandEvaluator
    profile_sha256: str


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("owner test profile has duplicate keys")
        result[key] = value
    return result


def load_owner_test_profile(repo_root: str) -> OwnerTestProfile:
    """Return a detached, admitted evaluator. Missing/unsafe profiles refuse.

    The shared source reader bounds the read and checks open-handle identity,
    symlinks and hard links. JSON has a stricter size limit. No fallback to the
    exact-match rehearsal happens when an owner-tests run was requested.
    """
    root = Path(repo_root).resolve(strict=True)
    control = control_root(root)
    if control.is_relative_to(root):
        raise ValueError("owner test profile must be outside the candidate repository")
    source = read_repository_source(control, PROFILE_NAME)
    if source.size > MAX_PROFILE_BYTES:
        raise ValueError("owner test profile exceeds its JSON size limit")
    data = json.loads(source.source.decode("utf-8"), object_pairs_hook=_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON")))
    expected = {"schema", "argv", "timeout_s", "test_roots", "acknowledge_unsandboxed_execution"}
    if type(data) is not dict or set(data) != expected or data["schema"] != PROFILE_SCHEMA:
        raise ValueError("owner test profile has invalid fields or schema")
    if data["acknowledge_unsandboxed_execution"] is not True:
        raise ValueError("owner must acknowledge the existing candidate process/network limitations")
    if type(data["argv"]) is not list or type(data["test_roots"]) is not list:
        raise ValueError("owner test argv and test_roots must be arrays")
    if type(data["timeout_s"]) is not int or not 1 <= data["timeout_s"] <= 120:
        raise ValueError("computer campaign test timeout must be between 1 and 120 seconds")
    evaluator = _admit_test_evaluator(TestCommandEvaluator(
        argv=tuple(data["argv"]), timeout_s=data["timeout_s"], test_roots=tuple(data["test_roots"]),
    ))
    return OwnerTestProfile(evaluator=evaluator, profile_sha256=canonical_sha(data))
