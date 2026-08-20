"""Deterministic evaluator ladder for higher-twin-nc-v1 fixture trees.

Sealed from the operators: operators never see evaluator internals or
results. Ladder, cheap to dear:

  L0 parse    both code files compile (builtin compile, no .pyc side effects)
  L1 schema   schema.json field set matches the CSV header; cell types parse
  L2 docs     every schema field is documented with matching type and unit,
              and every documented field exists in the schema
  L3 checks   the fixture's standalone behavior checks (subprocess)
  L4 digest   sha256 of the calibration pipeline's stdout (behavioral
              fingerprint; equal digests = equal observable behavior here)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

_INT_RE = re.compile(r"^-?\d+$")
_CHECKS_RE = re.compile(r"CHECKS (\d+)/(\d+)")

#: Subprocess wall limit. Module-level so tests can shrink it; a timeout is a
#: DETERMINISTIC failure outcome, never an exception out of evaluate_tree.
TIMEOUT_S = 60


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_ok(tree: Path) -> bool:
    try:
        for name in ("calib.py", "checks.py"):
            compile(_read(tree / name), name, "exec")
        return True
    except SyntaxError:
        return False


def _schema_ok(tree: Path) -> bool:
    try:
        schema = json.loads(_read(tree / "schema.json"))
        lines = _read(tree / "data" / "events.csv").rstrip("\n").split("\n")
        header = lines[0].split(",")
        by_name = {f["name"]: f for f in schema["fields"]}
        # duplicate columns or duplicate schema entries must not collapse
        # silently through the set/dict comparison
        if len(set(header)) != len(header):
            return False
        if len(by_name) != len(schema["fields"]):
            return False
        if set(header) != set(by_name):
            return False
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) != len(header):
                return False
            cells = dict(zip(header, parts))
            for name, cell in cells.items():
                if by_name[name]["type"] == "integer":
                    if not _INT_RE.match(cell):
                        return False
                else:
                    float(cell)
        return True
    except Exception:
        return False


def _docs_ok(tree: Path) -> bool:
    try:
        schema = json.loads(_read(tree / "schema.json"))
        text = _read(tree / "docs" / "fields.md")
        sections = {}
        current = None
        for line in text.split("\n"):
            m = re.match(r"^## `(.+)`$", line)
            if m:
                current = m.group(1)
                sections[current] = []
            elif current is not None:
                sections[current].append(line)
        names = {f["name"] for f in schema["fields"]}
        if set(sections) != names:
            return False
        for f in schema["fields"]:
            body = "\n".join(sections[f["name"]])
            unit_text = f["unit"] or "none"
            if f"of type {f['type']}." not in body:
                return False
            if f"Unit: {unit_text}." not in body:
                return False
        return True
    except Exception:
        return False


def _run(tree: Path, script: str) -> subprocess.CompletedProcess:
    # Bytes capture: the digest must hash RAW output (errors="replace" would
    # collapse distinct invalid byte sequences into one digest). Decoding
    # happens only where text is parsed. Env is canonicalized so the digest
    # does not depend on locale or hash randomization of the host.
    env = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        PYTHONHASHSEED="0",
    )
    return subprocess.run(
        [sys.executable, script],
        cwd=str(tree),
        env=env,
        capture_output=True,
        timeout=TIMEOUT_S,
    )


def _checks(tree: Path) -> tuple:
    try:
        proc = _run(tree, "checks.py")
    except subprocess.TimeoutExpired:
        return 0, 0
    # exit 0/1 is the checks contract (pass/fail); any other exit is a crash
    # and a stale CHECKS line on stdout must not be believed
    if proc.returncode not in (0, 1):
        return 0, 0
    m = _CHECKS_RE.search(proc.stdout.decode("utf-8", errors="replace"))
    if not m:
        return 0, 0
    passed, total = int(m.group(1)), int(m.group(2))
    if passed > total:
        return 0, 0
    return passed, total


def _pipeline(tree: Path) -> tuple:
    """One pipeline run yields both the digest and the numeric values.

    The digest is the binary fingerprint over RAW bytes (labels, formatting,
    everything; CRLF normalized). On failure, stdout is still part of the
    payload — two failing programs with different output must not collapse
    into one digest. `values` is the parsed calibrated column (the fixture
    contract: data rows are exactly three whitespace-separated tokens);
    non-finite tokens are kept as strings so results stay JSON-safe and
    comparison never hits NaN != NaN.
    """
    try:
        proc = _run(tree, "calib.py")
    except subprocess.TimeoutExpired:
        return f"TIMEOUT:{TIMEOUT_S}s:calib.py", []
    raw_out = proc.stdout.replace(b"\r\n", b"\n")
    raw_err = proc.stderr.replace(b"\r\n", b"\n")
    if proc.returncode == 0:
        payload = raw_out
    else:
        payload = b"EXIT:" + str(proc.returncode).encode("ascii") + b"\n" + raw_out + raw_err
    digest = hashlib.sha256(payload).hexdigest()
    values = []
    if proc.returncode == 0:
        for line in raw_out.decode("utf-8", errors="replace").splitlines():
            tokens = line.split()
            if len(tokens) == 3:
                try:
                    number = float(tokens[2])
                except ValueError:
                    continue
                if math.isfinite(number):
                    values.append(number)
                else:
                    values.append(tokens[2])
    return digest, values


def evaluate_tree(tree: Path) -> dict:
    tree = Path(tree)
    parse_ok = _parse_ok(tree)
    result = {
        "parse_ok": parse_ok,
        "schema_ok": _schema_ok(tree),
        "docs_ok": _docs_ok(tree),
        "checks_passed": 0,
        "checks_total": 0,
        "digest": "",
        "values": [],
    }
    if parse_ok:
        result["checks_passed"], result["checks_total"] = _checks(tree)
        result["digest"], result["values"] = _pipeline(tree)
    return result
