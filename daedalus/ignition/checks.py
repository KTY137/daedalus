"""The three Gate-1 evaluators: tests, schema conformance, knowledge links.

WHY THESE THREE AND NOT A GATE FUNCTION
---------------------------------------
Plan §10 Gate 1 requires that "tests, schema checks and link checks produce an
EvidencePacket". Each of the three answers a different plane pair:

* the **pytest** check runs the target project's own conformance tests -- the
  Code/Type propagation, judged by executing it;
* the **schema** check compares the Data plane against itself (a CSV header and
  the JSON Schema that constrains it) -- the half-finished rename this catches
  is invisible to any test that only imports the module;
* the **link** check resolves every relative Markdown link in the Knowledge
  plane against the tree -- the plane that has no runtime and therefore no
  other way to be wrong loudly.

EVERY EVALUATOR HERE IS AUTHORED OUTSIDE THE CANDIDATE. Nothing in this module
is read from, imported from, or configurable by the tree it judges: the
criteria are the constants below and the code in this file. That is the
property :mod:`daedalus.spine.receipts` calls "the criterion came from outside
the candidate", and it is what makes a ``deterministic`` assurance honest for
these reports. The one exception is deliberate and named: the pytest check
EXECUTES a test file, and that file is seeded into the target project's base
revision by :mod:`daedalus.ignition.gate1` from :data:`CONFORMANCE_TEST_SOURCE`
below -- so it is in the tree, but no work item may write it, and the attempt
spine's target-scope containment is what enforces that.

NOTHING HERE DECIDES ANYTHING. A :class:`CheckReport` is a measurement with its
raw output retained. Whether it becomes evidence, and with what assurance, is
decided by the caller against the attempt records -- never here.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.spine.envelope import canonical_sha

#: Where :mod:`daedalus.ignition.gate1` seeds the conformance suite inside the
#: ignition target project. Outside every work item's declared ``target_paths``
#: on purpose -- see the module docstring.
CONFORMANCE_TEST_PATH = "tests/test_event_field.py"

#: The Gate-1 conformance suite, as source rather than as a file under
#: ``daedalus/`` -- a real ``test_*.py`` inside the package would be collected
#: by this repository's own suite, where ``ignition_app`` does not exist. Its
#: sha256 is the criterion identity a receipt names.
CONFORMANCE_TEST_SOURCE = '''\
"""Gate-1 conformance suite for the ignition target project.

Seeded into the base revision by daedalus.ignition.gate1 BEFORE any work item
runs, and never listed in a work item's target_paths, so no candidate edit can
reach the criterion that judges it.
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

FIELD = "bias_voltage"
RETIRED = "voltage"


def test_type_exposes_the_renamed_field():
    from ignition_app import parse_event

    event = parse_event({"id": "1", FIELD: "125.0"})
    assert getattr(event, FIELD) == 125.0
    assert not hasattr(event, RETIRED)


def test_csv_header_carries_the_renamed_field():
    with (ROOT / "data" / "events.csv").open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert FIELD in header
    assert RETIRED not in header


def test_repository_parses_every_csv_row():
    from ignition_app import parse_event

    with (ROOT / "data" / "events.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for row in rows:
        assert getattr(parse_event(row), FIELD) == float(row[FIELD])


def test_wiki_documents_the_renamed_field():
    text = (ROOT / "wiki" / "Event.md").read_text(encoding="utf-8")
    assert FIELD in text
    assert not re.search(r"(?<![A-Za-z0-9_])" + RETIRED + r"(?![A-Za-z0-9_])", text)


def test_wiki_links_resolve():
    text = (ROOT / "wiki" / "Event.md").read_text(encoding="utf-8")
    targets = re.findall(r"]\(([^)\s]+)\)", text)
    assert targets
    for target in targets:
        assert ((ROOT / "wiki") / target).resolve().exists(), target
'''

CONFORMANCE_TEST_SHA256 = canonical_sha({"source": CONFORMANCE_TEST_SOURCE})

#: The node the Code/Type work item alone is required to turn green. The
#: repository node needs BOTH work items, so it is the composed candidate's
#: criterion, not one attempt's.
CODE_TYPE_NODE_IDS = (f"{CONFORMANCE_TEST_PATH}::test_type_exposes_the_renamed_field",)

#: The nodes the Data/Knowledge work item alone must turn green: the CSV header
#: (data plane) and the wiki page with its links (knowledge plane). None of the
#: three imports ``ignition_app`` at module level, so this work item's gate can
#: run them on a tree where the code plane is still un-renamed.
#:
#: WHY THIS EXISTS (2026-08-23). Until now the data/knowledge gate ran only
#: :func:`schema_check` and :func:`link_check`, whose criterion is code in THIS
#: module rather than a file in the judged tree. The attempt therefore declared
#: no ``gate_criterion_paths``, and ``evaluator_assurance`` correctly refused to
#: call the verdict deterministic: nothing outside the candidate stated it. The
#: seeded conformance suite is exactly that outside statement -- it lives at
#: ``tests/test_event_field.py``, which no work item may write -- so the gate
#: now EXECUTES it and names it. The schema and link checks stay, as the
#: measurements they always were.
DATA_KNOWLEDGE_NODE_IDS = (
    f"{CONFORMANCE_TEST_PATH}::test_csv_header_carries_the_renamed_field",
    f"{CONFORMANCE_TEST_PATH}::test_wiki_documents_the_renamed_field",
    f"{CONFORMANCE_TEST_PATH}::test_wiki_links_resolve",
)

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

_JSON_TYPES: Mapping[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
}


@dataclass(frozen=True)
class CheckReport:
    """One evaluator's measurement, with its raw output retained."""

    kind: str            # pytest | schema | link
    evaluator: str       # the identifier an EvidenceItem will carry
    passed: bool
    #: Files IN THE JUDGED TREE that state the criterion -- the ones whose
    #: content a candidate could rewrite to change the verdict in its own
    #: favour. Only the pytest check has any: it executes a test file. The
    #: schema and link checks state their criterion in THIS module (a CSV
    #: header set must equal the schema's property set; every relative link
    #: must resolve), so their criterion is code no candidate can reach and
    #: this tuple is empty. Both artefacts they compare are subjects.
    #:
    #: THE DISTINCTION IS LOAD-BEARING and was got wrong once: labelling
    #: ``schemas/event.schema.json`` a criterion made the Gate-1 packet
    #: unverified, because that path is inside the data work item's declared
    #: write scope. It is inside that scope -- the rename is supposed to change
    #: it -- but it is not what decides the verdict.
    criterion_paths: tuple[str, ...]
    subject_paths: tuple[str, ...]     # what was judged
    detail: Mapping[str, Any]
    output: str

    @property
    def output_bytes(self) -> bytes:
        return self.output.encode("utf-8")

    @property
    def output_sha256(self) -> str:
        """The digest of the RAW output bytes -- the spine's own convention.

        ``GateResult.output_sha256`` is ``sha256(output)`` and the attempt spine
        stores exactly those bytes under exactly that digest, so an evidence
        item's ``output_sha256`` and the blob its ``evidence_locator`` resolves
        to are the same object. A digest of the structured summary instead would
        name something no store holds. That summary keeps its own stable digest
        in :attr:`report_sha256`, which is what a replay comparison uses,
        because raw pytest output carries per-run durations.
        """

        return hashlib.sha256(self.output_bytes).hexdigest()

    @property
    def report_sha256(self) -> str:
        """The digest of the structured verdict -- stable across replays."""

        return canonical_sha(
            {
                "schema": "daedalus-ignition-check/1",
                "kind": self.kind,
                "evaluator": self.evaluator,
                "passed": self.passed,
                "criterion_paths": list(self.criterion_paths),
                "subject_paths": list(self.subject_paths),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "evaluator": self.evaluator,
            "passed": self.passed,
            "criterion_paths": list(self.criterion_paths),
            "subject_paths": list(self.subject_paths),
            "report_sha256": self.report_sha256,
            "detail": json.loads(json.dumps(self.detail, sort_keys=True, default=str)),
        }


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


# --------------------------------------------------------------------------- #
# pytest                                                                       #
# --------------------------------------------------------------------------- #
def pytest_check(
    root: str | Path,
    node_ids: Sequence[str] = (),
    *,
    timeout_s: float = 120.0,
    label: str = "pytest",
) -> CheckReport:
    """Execute the target project's conformance suite inside ``root``.

    WRITES NOTHING INTO THE TREE IT JUDGES, and that is load-bearing rather than
    tidy: this runs as an attempt gate, and ``TaskAttempt`` refuses a green
    verdict whose gate left an untracked file behind (``_post_gate_artifact_
    stable``). ``PYTHONDONTWRITEBYTECODE`` suppresses ``__pycache__`` and
    ``-p no:cacheprovider`` suppresses ``.pytest_cache``; without both, a
    passing suite would still fail the attempt.
    """

    tree = Path(root).resolve()
    targets = list(node_ids) or [CONFORMANCE_TEST_PATH]
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        "--no-header",
        *targets,
    ]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(tree),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        returncode: int | None = completed.returncode
        text = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        returncode = None
        text = f"pytest timed out after {timeout_s}s: {exc}"
    passed = returncode == 0
    return CheckReport(
        kind="pytest",
        evaluator=f"ignition-{label}",
        passed=passed,
        criterion_paths=(CONFORMANCE_TEST_PATH,),
        subject_paths=tuple(targets),
        detail={
            "argv": [str(part) for part in argv[1:]],
            "returncode": returncode,
            "node_ids": [str(node) for node in targets],
            "conformance_test_sha256": CONFORMANCE_TEST_SHA256,
            "output_tail": text[-4000:],
        },
        output=text,
    )


# --------------------------------------------------------------------------- #
# schema                                                                       #
# --------------------------------------------------------------------------- #
def schema_check(
    root: str | Path,
    *,
    csv_path: str = "data/events.csv",
    schema_path: str = "schemas/event.schema.json",
) -> CheckReport:
    """Check one CSV table against the JSON Schema that claims to constrain it.

    Deliberately NOT a JSON Schema library call. The failure this exists to
    catch is a half-finished cross-plane rename -- the CSV renamed and the
    schema not, or the reverse -- and that is a comparison of the two field
    SETS, which a per-row validator against a schema with
    ``additionalProperties: false`` reports only as an opaque row failure. Both
    are checked here: the sets must agree exactly, and every row must then type
    check.
    """

    tree = Path(root).resolve()
    problems: list[str] = []
    schema_file = tree / schema_path
    csv_file = tree / csv_path
    schema: dict[str, Any] = {}
    header: list[str] = []
    rows: list[dict[str, str]] = []

    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported as a failed check
        problems.append(f"schema unreadable: {type(exc).__name__}: {exc}")
    try:
        with csv_file.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = list(next(reader, []))
        with csv_file.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:  # noqa: BLE001 - reported as a failed check
        problems.append(f"csv unreadable: {type(exc).__name__}: {exc}")

    properties = dict(schema.get("properties") or {})
    required = list(schema.get("required") or [])
    if properties and header:
        missing = sorted(set(properties) - set(header))
        extra = sorted(set(header) - set(properties))
        if missing:
            problems.append(
                f"schema declares field(s) the CSV header does not carry: {', '.join(missing)}"
            )
        if extra:
            problems.append(
                f"CSV header carries field(s) the schema does not declare: {', '.join(extra)}"
            )
        for name in required:
            if name not in header:
                problems.append(f"required field {name!r} is absent from the CSV header")
    for index, row in enumerate(rows):
        for name, spec in properties.items():
            if name not in row:
                continue
            declared = str((spec or {}).get("type") or "")
            raw = row[name]
            if declared in {"number", "integer"}:
                try:
                    float(raw) if declared == "number" else int(raw)
                except (TypeError, ValueError):
                    problems.append(
                        f"row {index}: field {name!r} value {raw!r} is not a {declared}"
                    )
            elif declared == "string" and not isinstance(raw, str):
                problems.append(f"row {index}: field {name!r} is not a string")

    passed = not problems
    lines = [
        f"schema check: {csv_path} against {schema_path}",
        f"csv header: {', '.join(header) or '<none>'}",
        f"schema properties: {', '.join(sorted(properties)) or '<none>'}",
        f"rows: {len(rows)}",
        f"verdict: {'passed' if passed else 'failed'}",
        *(f"  - {problem}" for problem in problems),
    ]
    return CheckReport(
        kind="schema",
        evaluator="ignition-schema-check",
        passed=passed,
        # No criterion inside the tree: the rule is the set comparison below,
        # which lives in this module. Both compared artefacts are subjects.
        criterion_paths=(),
        subject_paths=(csv_path, schema_path),
        detail={
            "csv_header": header,
            "schema_properties": sorted(properties),
            "schema_required": sorted(required),
            "row_count": len(rows),
            "problems": problems,
        },
        output="\n".join(lines),
    )


# --------------------------------------------------------------------------- #
# links                                                                        #
# --------------------------------------------------------------------------- #
def link_check(
    root: str | Path,
    *,
    knowledge_paths: Sequence[str] = ("wiki/Event.md",),
) -> CheckReport:
    """Resolve every relative Markdown link in the Knowledge plane."""

    tree = Path(root).resolve()
    checked: list[dict[str, Any]] = []
    problems: list[str] = []
    for rel in knowledge_paths:
        document = tree / rel
        try:
            text = document.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - reported as a failed check
            problems.append(f"{rel}: unreadable: {type(exc).__name__}: {exc}")
            continue
        for target in _MD_LINK.findall(text):
            if "://" in target or target.startswith("#") or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target.split("#", 1)[0]).resolve()
            exists = resolved.exists()
            try:
                shown = _rel(tree, resolved)
            except ValueError:
                shown = str(resolved)
                exists = False
                problems.append(f"{rel}: link {target!r} escapes the project tree")
            checked.append({"document": rel, "target": target, "resolves_to": shown, "exists": exists})
            if not exists:
                problems.append(f"{rel}: link {target!r} does not resolve to a file in the tree")

    passed = not problems and bool(checked)
    if not checked and not problems:
        problems.append("no relative Markdown links were found; the check judged nothing")
        passed = False
    lines = [
        f"link check over {len(knowledge_paths)} knowledge document(s)",
        f"links checked: {len(checked)}",
        *(f"  {row['document']} -> {row['target']} => {'ok' if row['exists'] else 'MISSING'}" for row in checked),
        f"verdict: {'passed' if passed else 'failed'}",
        *(f"  - {problem}" for problem in problems),
    ]
    return CheckReport(
        kind="link",
        evaluator="ignition-link-check",
        passed=passed,
        # As for the schema check: the criterion is "every relative link
        # resolves", stated here. The documents and their targets are subjects.
        criterion_paths=(),
        subject_paths=tuple(sorted(
            {*knowledge_paths, *(row["resolves_to"] for row in checked)}
        )),
        detail={"links": checked, "problems": problems},
        output="\n".join(lines),
    )


def check_manifest(reports: Sequence[CheckReport]) -> dict[str, Any]:
    """A stable summary of a run's checks -- kinds present, verdicts, digests."""

    return {
        "kinds": sorted({report.kind for report in reports}),
        "reports": [
            {
                "kind": report.kind,
                "evaluator": report.evaluator,
                "passed": report.passed,
                "output_sha256": report.output_sha256,
                "report_sha256": report.report_sha256,
            }
            for report in reports
        ],
    }


def render_reports(reports: Sequence[CheckReport]) -> str:
    """The raw text of several checks, for one gate output blob."""

    buffer = io.StringIO()
    for report in reports:
        buffer.write(f"=== {report.evaluator} ({report.kind}) ===\n")
        buffer.write(report.output)
        buffer.write("\n\n")
    return buffer.getvalue()


__all__ = [
    "CODE_TYPE_NODE_IDS",
    "DATA_KNOWLEDGE_NODE_IDS",
    "CONFORMANCE_TEST_PATH",
    "CONFORMANCE_TEST_SHA256",
    "CONFORMANCE_TEST_SOURCE",
    "CheckReport",
    "check_manifest",
    "link_check",
    "pytest_check",
    "render_reports",
    "schema_check",
]
