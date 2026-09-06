"""Deterministic, reviewable Tcl emission for AMD Vivado and Vitis HLS.

Nothing in this module touches the filesystem, starts a process, or claims a
vendor verdict.  Every public renderer is a pure function of its arguments and
returns canonical UTF-8 text with LF line endings, so the same inputs always
produce the same bytes and the same SHA-256.

The emitted scripts are *artifacts for review and for a later, separately
admitted effectful packet*.  Daedalus does not execute them here: the emitting
CLI path spawns no process, and on the emitting host no AMD toolchain is
installed at all.  The syntax check reported alongside a script is a
Tcl-completeness check (the semantics of Tcl's ``info complete``) implemented
in Python.  It is evidence that the text is a syntactically closed Tcl script.
It is never evidence that Vivado or Vitis HLS accepts it.
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


TCL_EMIT_SCHEMA = "daedalus-chip-tcl-emit/1"
TCL_SYNTAX_CHECKER = "daedalus-tcl-info-complete/1"

VIVADO_TARGET = "vivado-project"
VITIS_HLS_TARGET = "vitis-hls"
PARSE_HARNESS_TARGET = "parse-harness"

TARGETS = (VIVADO_TARGET, VITIS_HLS_TARGET)

#: Emission scopes for the Vivado target.  ``full`` is synthesis through
#: bitstream in one script; the narrower scopes stop earlier.
VIVADO_SCOPES = ("inspect", "synth", "impl", "full")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PART = re.compile(r"^[A-Za-z0-9_.:+-]{1,200}$")
_RUN_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_TOP = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,199}$")
_SOLUTION = re.compile(r"^[A-Za-z0-9_.-]{1,200}$")
_CLOCK_PERIOD = re.compile(r"^[0-9]{1,6}(?:\.[0-9]{1,6})?$")
_RELATIVE = re.compile(r"^[A-Za-z0-9_.+-][A-Za-z0-9 _.+/-]{0,400}$")
_COMMAND_WORD = re.compile(r"^[a-z_][a-z0-9_]*$")
_PROC_LINE = re.compile(r"^proc\s+([A-Za-z_][A-Za-z0-9_]*)\s")

_HLS_KERNEL_SUFFIXES = (".cpp", ".cc", ".cxx", ".c")

#: Tcl builtins the emitted scripts and the harness may use.  A vendor command
#: is by definition not in this set, so the harness stubs exactly the
#: difference and a test can assert that no undeclared command word appears.
TCL_BUILTINS = frozenset(
    {
        "catch",
        "close",
        "concat",
        "dict",
        "else",
        "elseif",
        "eval",
        "exit",
        "expr",
        "fconfigure",
        "file",
        "foreach",
        "format",
        "global",
        "if",
        "incr",
        "info",
        "lappend",
        "lindex",
        "list",
        "llength",
        "lsort",
        "open",
        "proc",
        "puts",
        "read",
        "rename",
        "return",
        "set",
        "string",
        "switch",
        "unset",
        "while",
    }
)

#: Every AMD Vivado command the Vivado renderer may emit.
VIVADO_COMMANDS: tuple[str, ...] = (
    "add_files",
    "close_design",
    "close_project",
    "create_project",
    "current_fileset",
    "current_project",
    "get_property",
    "get_runs",
    "launch_runs",
    "open_project",
    "open_run",
    "report_drc",
    "report_methodology",
    "report_route_status",
    "report_timing_summary",
    "report_utilization",
    "reset_run",
    "set_property",
    "wait_on_run",
    "write_bitstream",
    "write_checkpoint",
)

#: Every AMD Vitis HLS command the HLS renderer may emit.
VITIS_HLS_COMMANDS: tuple[str, ...] = (
    "add_files",
    "close_project",
    "create_clock",
    "csynth_design",
    "open_project",
    "open_solution",
    "set_part",
    "set_top",
)


class TclEmitError(ValueError):
    """A value cannot enter a deterministic emitted Tcl artifact."""


# ---------------------------------------------------------------------------
# Tcl completeness ("info complete") without a Tcl interpreter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TclCompleteness:
    """Result of the pure-Python Tcl completeness scan."""

    complete: bool
    detail: str
    open_construct: str
    open_offset: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checker": TCL_SYNTAX_CHECKER,
            "complete": self.complete,
            "detail": self.detail,
            "open_construct": self.open_construct,
            "open_offset": self.open_offset,
            # An emitted script is never run by the emitting command, and a
            # closed Tcl script is not a vendor verdict.  Both stay false so a
            # reader cannot mistake this row for a build result.
            "executed": False,
            "vendor_acceptance_claimed": False,
        }


_CONSTRUCT_LABEL = {"{": "brace", "[": "bracket", '"': "quote"}


def tcl_completeness(text: str) -> TclCompleteness:
    """Mirror Tcl's ``info complete`` for one script.

    The scan follows the rules the Tcl parser uses to decide whether a script
    has an unterminated construct: braces and double quotes only open at the
    start of a word, ``[`` always opens a command substitution, ``#`` only
    starts a comment at a command position, a backslash always escapes the
    next character, and inside a brace-quoted word nothing but braces and
    backslashes is significant.  Verified case-by-case against ``tclsh``
    8.6.12; the corpus lives in ``tests/test_chip_design_tcl_emit.py``.
    """

    if not isinstance(text, str):
        raise TclEmitError("tcl completeness input must be a string")
    stack: list[tuple[str, int]] = []
    index = 0
    length = len(text)
    at_word_start = True
    at_command_start = True
    while index < length:
        character = text[index]
        if stack and stack[-1][0] == "{":
            if character == "\\":
                index += 2
                continue
            if character == "{":
                stack.append(("{", index))
            elif character == "}":
                stack.pop()
                at_word_start = False
                at_command_start = False
            index += 1
            continue
        if character == "\\":
            index += 2
            at_word_start = False
            at_command_start = False
            continue
        if stack and stack[-1][0] == '"':
            if character == '"':
                stack.pop()
                at_word_start = False
                at_command_start = False
            elif character == "[":
                stack.append(("[", index))
                at_word_start = True
                at_command_start = True
            index += 1
            continue
        if character in " \t\r":
            at_word_start = True
            index += 1
            continue
        if character in "\n;":
            at_word_start = True
            at_command_start = True
            index += 1
            continue
        if character == "#" and at_command_start:
            index += 1
            while index < length:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == "\n":
                    break
                index += 1
            continue
        if character == "{" and at_word_start:
            stack.append(("{", index))
        elif character == '"' and at_word_start:
            stack.append(('"', index))
        elif character == "[":
            stack.append(("[", index))
            at_word_start = True
            at_command_start = True
            index += 1
            continue
        elif character == "]" and stack and stack[-1][0] == "[":
            stack.pop()
        at_word_start = False
        at_command_start = False
        index += 1
    if not stack:
        return TclCompleteness(complete=True, detail="", open_construct="", open_offset=None)
    construct, offset = stack[0]
    label = _CONSTRUCT_LABEL[construct]
    return TclCompleteness(
        complete=False,
        detail=f"unterminated {label} opened at byte offset {offset}",
        open_construct=label,
        open_offset=offset,
    )


def tcl_info_complete(text: str) -> bool:
    """Boolean form of :func:`tcl_completeness`."""

    return tcl_completeness(text).complete


# ---------------------------------------------------------------------------
# Value contracts
# ---------------------------------------------------------------------------


def tcl_brace_literal(value: str, *, name: str) -> str:
    """Return ``value`` for use inside a Tcl ``{...}`` literal, or refuse it.

    A brace literal is the only quoting an emitted script uses for data, so a
    value that could escape one is refused instead of being escaped.  That
    keeps the emitted text obvious to a reviewer and keeps rendering total.
    """

    if not isinstance(value, str):
        raise TclEmitError(f"{name} must be a string")
    if not value:
        raise TclEmitError(f"{name} must not be empty")
    for forbidden, label in (
        ("\x00", "NUL"),
        ("\n", "newline"),
        ("\r", "carriage return"),
        ("{", "open brace"),
        ("}", "close brace"),
        ("\\", "backslash"),
        ("$", "dollar sign"),
        ("[", "open bracket"),
        ("]", "close bracket"),
        ('"', "double quote"),
    ):
        if forbidden in value:
            raise TclEmitError(f"{name} must not contain a {label}")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise TclEmitError(f"{name} must not contain a control character")
    if len(value) > 4096:
        raise TclEmitError(f"{name} exceeds the emitted-literal length bound")
    return value


def tcl_path_literal(value: str, *, name: str) -> str:
    """Normalize one path to the forward-slash form Tcl accepts everywhere."""

    if not isinstance(value, str):
        raise TclEmitError(f"{name} must be a string")
    normalized = value.replace("\\", "/")
    if len(normalized) > 2:
        normalized = normalized[:2] + re.sub(r"/{2,}", "/", normalized[2:])
    return tcl_brace_literal(normalized, name=name)


def _digest(value: object, *, name: str) -> str:
    text = str(value)
    if not _SHA256.fullmatch(text):
        raise TclEmitError(f"{name} must be a lowercase 64-hex SHA-256")
    return text


def _pattern(value: object, pattern: re.Pattern[str], *, name: str) -> str:
    text = str(value)
    if not pattern.fullmatch(text):
        raise TclEmitError(f"{name} is not a valid emitted {name.replace('_', ' ')}")
    return text


def _relative_posix(value: object, *, name: str) -> str:
    text = str(value).replace("\\", "/")
    if not _RELATIVE.fullmatch(text) or ".." in text.split("/") or text.startswith("/"):
        raise TclEmitError(f"{name} is not a bounded project-relative POSIX path")
    return tcl_brace_literal(text, name=name)


# ---------------------------------------------------------------------------
# Emitted script value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmittedTclScript:
    """One canonical Tcl artifact plus its identity and syntax evidence."""

    target: str
    scope: str
    text: str
    bound_identities: tuple[tuple[str, str], ...]
    commands: tuple[str, ...]

    @property
    def data(self) -> bytes:
        return self.text.encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def byte_length(self) -> int:
        return len(self.data)

    @property
    def line_count(self) -> int:
        return self.text.count("\n")

    @property
    def syntax_check(self) -> TclCompleteness:
        return tcl_completeness(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TCL_EMIT_SCHEMA,
            "target": self.target,
            "scope": self.scope,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "line_count": self.line_count,
            "commands": list(self.commands),
            "bound_identities": {name: value for name, value in self.bound_identities},
            "syntax_check": self.syntax_check.to_dict(),
        }


def emitted_command_words(text: str) -> tuple[str, ...]:
    """Return the distinct line-leading command words of an emitted script.

    Every renderer writes one command per line, so a line's first word is its
    command word.  Continuation, data, and block-closing lines start with a
    character that is not a lowercase identifier and are skipped.
    """

    words: set[str] = set()
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        head = stripped.split(None, 1)[0]
        if _COMMAND_WORD.fullmatch(head):
            words.add(head)
    return tuple(sorted(words))


def emitted_defined_procs(text: str) -> tuple[str, ...]:
    """Return the proc names an emitted script defines for itself."""

    names: set[str] = set()
    for line in text.split("\n"):
        match = _PROC_LINE.match(line.strip())
        if match:
            names.add(match.group(1))
    return tuple(sorted(names))


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _banner(
    *,
    title: str,
    target: str,
    scope: str,
    invocation: str,
    identities: Sequence[tuple[str, str]],
) -> list[str]:
    width = max((len(name) for name, _ in identities), default=0) + 1
    lines = [
        f"# {title}",
        "#",
        f"# schema:     {TCL_EMIT_SCHEMA}",
        f"# target:     {target}",
        f"# scope:      {scope}",
        "# emitter:    daedalus.chip_design.tcl_emit",
        f"# invocation: {invocation}",
        "#",
        "# Bound identities. This script is a plan for exactly these inputs; if a",
        "# digest below no longer matches, re-emit instead of editing this file.",
    ]
    for name, value in identities:
        lines.append(f"#   {(name + ':').ljust(width)} {value}")
    lines.extend(
        [
            "#",
            "# Daedalus emitted this text and did not run it. The emitting command",
            "# spawns no process. A passing Tcl completeness check is not evidence",
            "# that AMD Vivado or Vitis HLS accepts this script, and this file is",
            "# neither a build result nor a promotion.",
            "",
        ]
    )
    return lines


def _fail_proc(prefix: str) -> list[str]:
    return [
        "proc daedalus_fail {message code} {",
        f'    puts stderr "{prefix} code=$code message=$message"',
        "    catch {close_design}",
        "    catch {close_project}",
        "    exit $code",
        "}",
        "",
    ]


def _summary_lines(path_variable: str, rows: Sequence[tuple[str, str]]) -> list[str]:
    lines = [f"set daedalus_summary [open ${path_variable} w]"]
    for key, expression in rows:
        lines.append(f'puts $daedalus_summary "{key}={expression}"')
    lines.append("close $daedalus_summary")
    return lines


# ---------------------------------------------------------------------------
# AMD Vivado project flow
# ---------------------------------------------------------------------------


def render_vivado_project_flow(
    *,
    scope: str,
    project_file: str,
    project_root: str,
    output_dir: str,
    part: str,
    board_part: str,
    top: str,
    synth_run: str,
    impl_run: str,
    jobs: int,
    design_sources: Sequence[str],
    constraint_sources: Sequence[str],
    project_sha256: str,
    manifest_sha256: str,
    source_identity_sha256: str,
    plan_sha256: str,
    trusted_tcl_sha256: str,
) -> EmittedTclScript:
    """Render the canonical Vivado batch-mode flow for one inspected project."""

    if scope not in VIVADO_SCOPES:
        raise TclEmitError(f"scope must be one of {', '.join(VIVADO_SCOPES)}")
    if isinstance(jobs, bool) or not isinstance(jobs, int) or not 1 <= jobs <= 64:
        raise TclEmitError("jobs must be an integer between 1 and 64")
    project_literal = tcl_path_literal(project_file, name="project_file")
    root_literal = tcl_path_literal(project_root, name="project_root")
    output_literal = tcl_path_literal(output_dir, name="output_dir")
    part_literal = _pattern(part, _PART, name="part")
    top_literal = _pattern(top, _TOP, name="top")
    synth_literal = _pattern(synth_run, _RUN_NAME, name="synth_run")
    impl_literal = _pattern(impl_run, _RUN_NAME, name="impl_run")
    board_literal = _pattern(board_part, _PART, name="board_part") if board_part else ""
    design = tuple(_relative_posix(value, name="design_source") for value in design_sources)
    constraints = tuple(
        _relative_posix(value, name="constraint_source") for value in constraint_sources
    )
    if not design:
        raise TclEmitError("a Vivado flow needs at least one design source")
    if len(set(design)) != len(design) or len(set(constraints)) != len(constraints):
        raise TclEmitError("emitted source lists must not repeat a path")

    identities = (
        ("project_sha256", _digest(project_sha256, name="project_sha256")),
        ("manifest_sha256", _digest(manifest_sha256, name="manifest_sha256")),
        (
            "source_identity_sha256",
            _digest(source_identity_sha256, name="source_identity_sha256"),
        ),
        ("plan_sha256", _digest(plan_sha256, name="plan_sha256")),
        ("trusted_tcl_sha256", _digest(trusted_tcl_sha256, name="trusted_tcl_sha256")),
    )

    wants_synth = scope in {"synth", "impl", "full"}
    wants_impl = scope in {"impl", "full"}

    lines: list[str] = []
    lines.extend(
        _banner(
            title="Daedalus emitted AMD Vivado project flow.",
            target=VIVADO_TARGET,
            scope=scope,
            invocation="vivado -mode batch -nojournal -nolog -notrace -source <this file>",
            identities=identities,
        )
    )
    lines.extend(
        [
            f"set daedalus_project_file {{{project_literal}}}",
            f"set daedalus_project_root {{{root_literal}}}",
            f"set daedalus_output_dir {{{output_literal}}}",
            f"set daedalus_part {{{part_literal}}}",
            f"set daedalus_board_part {{{board_literal}}}",
            f"set daedalus_top {{{top_literal}}}",
            f"set daedalus_synth_run {{{synth_literal}}}",
            f"set daedalus_impl_run {{{impl_literal}}}",
            f"set daedalus_jobs {jobs}",
            f"set daedalus_project_sha256 {{{identities[0][1]}}}",
            f"set daedalus_plan_sha256 {{{identities[3][1]}}}",
            "",
            "set daedalus_design_sources [list \\",
        ]
    )
    lines.extend(f"    {{{value}}} \\" for value in design)
    lines.append("]")
    lines.append("set daedalus_constraint_sources [list \\")
    lines.extend(f"    {{{value}}} \\" for value in constraints)
    lines.append("]")
    lines.append("")
    lines.extend(_fail_proc("DAEDALUS_VIVADO_EMITTED_ERROR"))
    lines.extend(
        [
            "proc daedalus_expect {label actual expected} {",
            "    if {$actual ne $expected} {",
            '        daedalus_fail "$label is $actual, expected $expected" 20',
            "    }",
            "}",
            "",
            "proc daedalus_require_complete_run {run label} {",
            "    set progress [get_property PROGRESS [get_runs $run]]",
            "    set status [get_property STATUS [get_runs $run]]",
            '    if {$progress ne "100%"} {',
            '        daedalus_fail "$label stopped at $progress: $status" 21',
            "    }",
            "}",
            "",
            "file mkdir $daedalus_output_dir",
            "",
            "if {[file exists $daedalus_project_file]} {",
            "    open_project $daedalus_project_file",
            "} else {",
            "    create_project -force -part $daedalus_part \\",
            "        [file rootname [file tail $daedalus_project_file]] \\",
            "        [file dirname $daedalus_project_file]",
            "    foreach daedalus_source $daedalus_design_sources {",
            "        add_files -norecurse \\",
            "            [file join $daedalus_project_root $daedalus_source]",
            "    }",
            "    foreach daedalus_constraint $daedalus_constraint_sources {",
            "        add_files -fileset constrs_1 -norecurse \\",
            "            [file join $daedalus_project_root $daedalus_constraint]",
            "    }",
            "    set_property top $daedalus_top [current_fileset]",
            "}",
            "",
            'daedalus_expect "project part" \\',
            "    [get_property PART [current_project]] $daedalus_part",
            'daedalus_expect "top module" \\',
            "    [get_property TOP [current_fileset]] $daedalus_top",
            'if {$daedalus_board_part ne ""} {',
            '    daedalus_expect "board part" \\',
            "        [get_property BOARD_PART [current_project]] $daedalus_board_part",
            "}",
            "",
        ]
    )
    if wants_synth:
        lines.extend(
            [
                "reset_run $daedalus_synth_run",
                "launch_runs $daedalus_synth_run -jobs $daedalus_jobs",
                "wait_on_run $daedalus_synth_run",
                'daedalus_require_complete_run $daedalus_synth_run "synthesis"',
                "open_run $daedalus_synth_run -name $daedalus_synth_run",
                "write_checkpoint -force \\",
                "    [file join $daedalus_output_dir synth_design.dcp]",
                "report_utilization -file \\",
                "    [file join $daedalus_output_dir utilization.rpt]",
                "report_timing_summary -file \\",
                "    [file join $daedalus_output_dir timing_summary.rpt]",
                "report_drc -file [file join $daedalus_output_dir drc.rpt]",
                "report_methodology -file \\",
                "    [file join $daedalus_output_dir methodology.rpt]",
                "close_design",
                "",
            ]
        )
    if wants_impl:
        lines.extend(
            [
                "reset_run $daedalus_impl_run",
                "launch_runs $daedalus_impl_run -jobs $daedalus_jobs",
                "wait_on_run $daedalus_impl_run",
                'daedalus_require_complete_run $daedalus_impl_run "implementation"',
                "open_run $daedalus_impl_run",
                "write_checkpoint -force [file join $daedalus_output_dir design.dcp]",
                "report_utilization -file \\",
                "    [file join $daedalus_output_dir utilization.rpt]",
                "report_timing_summary -file \\",
                "    [file join $daedalus_output_dir timing_summary.rpt]",
                "report_drc -file [file join $daedalus_output_dir drc.rpt]",
                "report_methodology -file \\",
                "    [file join $daedalus_output_dir methodology.rpt]",
                "report_route_status -file \\",
                "    [file join $daedalus_output_dir route_status.rpt]",
                "write_bitstream -force [file join $daedalus_output_dir design.bit]",
                "if {![file exists [file join $daedalus_output_dir design.bit]]} {",
                '    daedalus_fail "bitstream was not written" 22',
                "}",
                "close_design",
                "",
            ]
        )
    summary_name = {
        "inspect": "inspect_summary.txt",
        "synth": "synth_summary.txt",
        "impl": "impl_summary.txt",
        "full": "impl_summary.txt",
    }[scope]
    lines.append(
        f"set daedalus_summary_path [file join $daedalus_output_dir {summary_name}]"
    )
    summary_rows: list[tuple[str, str]] = [
        ("schema", TCL_EMIT_SCHEMA),
        ("scope", scope),
        ("part", "$daedalus_part"),
        ("top", "$daedalus_top"),
        ("project_sha256", "$daedalus_project_sha256"),
        ("plan_sha256", "$daedalus_plan_sha256"),
    ]
    if wants_synth:
        summary_rows.append(
            ("synth_progress", "[get_property PROGRESS [get_runs $daedalus_synth_run]]")
        )
    if wants_impl:
        summary_rows.append(
            ("impl_progress", "[get_property PROGRESS [get_runs $daedalus_impl_run]]")
        )
    lines.extend(_summary_lines("daedalus_summary_path", summary_rows))
    lines.extend(
        [
            "",
            "close_project",
            f'puts "DAEDALUS_VIVADO_EMITTED_OK scope={scope}"',
            "exit 0",
            "",
        ]
    )
    return EmittedTclScript(
        target=VIVADO_TARGET,
        scope=scope,
        text="\n".join(lines),
        bound_identities=identities,
        commands=VIVADO_COMMANDS,
    )


# ---------------------------------------------------------------------------
# AMD Vitis HLS csynth flow
# ---------------------------------------------------------------------------


def render_vitis_hls_flow(
    *,
    kernel_file: str,
    kernel_sha256: str,
    top: str,
    part: str,
    solution: str,
    clock_period: str,
    project_dir: str,
    output_dir: str,
    plan_sha256: str,
) -> EmittedTclScript:
    """Render the canonical Vitis HLS C synthesis script for one kernel."""

    kernel_literal = tcl_path_literal(kernel_file, name="kernel_file")
    if not kernel_literal.lower().endswith(_HLS_KERNEL_SUFFIXES):
        raise TclEmitError(
            "kernel_file must be a C/C++ translation unit "
            f"({', '.join(_HLS_KERNEL_SUFFIXES)})"
        )
    project_literal = tcl_path_literal(project_dir, name="project_dir")
    output_literal = tcl_path_literal(output_dir, name="output_dir")
    top_literal = _pattern(top, _TOP, name="top")
    part_literal = _pattern(part, _PART, name="part")
    solution_literal = _pattern(solution, _SOLUTION, name="solution")
    period_literal = _pattern(clock_period, _CLOCK_PERIOD, name="clock_period")
    identities = (
        ("kernel_sha256", _digest(kernel_sha256, name="kernel_sha256")),
        ("plan_sha256", _digest(plan_sha256, name="plan_sha256")),
    )

    lines: list[str] = []
    lines.extend(
        _banner(
            title="Daedalus emitted AMD Vitis HLS C synthesis flow.",
            target=VITIS_HLS_TARGET,
            scope="csynth",
            invocation="vitis_hls -f <this file>",
            identities=identities,
        )
    )
    lines.extend(
        [
            f"set daedalus_kernel {{{kernel_literal}}}",
            f"set daedalus_project_dir {{{project_literal}}}",
            f"set daedalus_output_dir {{{output_literal}}}",
            f"set daedalus_top {{{top_literal}}}",
            f"set daedalus_part {{{part_literal}}}",
            f"set daedalus_solution {{{solution_literal}}}",
            f"set daedalus_clock_period {period_literal}",
            f"set daedalus_kernel_sha256 {{{identities[0][1]}}}",
            f"set daedalus_plan_sha256 {{{identities[1][1]}}}",
            "",
        ]
    )
    lines.extend(_fail_proc("DAEDALUS_VITIS_HLS_EMITTED_ERROR"))
    lines.extend(
        [
            "if {![file exists $daedalus_kernel]} {",
            '    daedalus_fail "kernel source is missing: $daedalus_kernel" 30',
            "}",
            "file mkdir $daedalus_output_dir",
            "",
            "open_project -reset $daedalus_project_dir",
            "add_files $daedalus_kernel",
            "set_top $daedalus_top",
            "open_solution -reset $daedalus_solution -flow_target vivado",
            "set_part $daedalus_part",
            "create_clock -period $daedalus_clock_period -name default",
            "csynth_design",
            "",
            "set daedalus_report [file join $daedalus_project_dir \\",
            "    $daedalus_solution syn report ${daedalus_top}_csynth.rpt]",
            "if {![file exists $daedalus_report]} {",
            '    daedalus_fail "csynth report is missing: $daedalus_report" 31',
            "}",
            "file copy -force $daedalus_report \\",
            "    [file join $daedalus_output_dir csynth.rpt]",
            "",
            "set daedalus_summary_path \\",
            "    [file join $daedalus_output_dir hls_summary.txt]",
        ]
    )
    lines.extend(
        _summary_lines(
            "daedalus_summary_path",
            [
                ("schema", TCL_EMIT_SCHEMA),
                ("scope", "csynth"),
                ("part", "$daedalus_part"),
                ("top", "$daedalus_top"),
                ("solution", "$daedalus_solution"),
                ("clock_period", "$daedalus_clock_period"),
                ("kernel_sha256", "$daedalus_kernel_sha256"),
                ("plan_sha256", "$daedalus_plan_sha256"),
            ],
        )
    )
    lines.extend(
        [
            "",
            "close_project",
            'puts "DAEDALUS_VITIS_HLS_EMITTED_OK scope=csynth"',
            "exit 0",
            "",
        ]
    )
    return EmittedTclScript(
        target=VITIS_HLS_TARGET,
        scope="csynth",
        text="\n".join(lines),
        bound_identities=identities,
        commands=VITIS_HLS_COMMANDS,
    )


# ---------------------------------------------------------------------------
# Contained parse harness
# ---------------------------------------------------------------------------


def render_parse_harness(script: EmittedTclScript) -> EmittedTclScript:
    """Render a self-contained ``tclsh`` harness that parses an emitted script.

    The subject script is carried inside the harness as base64, so the harness
    reads no file and needs no path: it decodes the exact bytes the emitter
    produced.  Every vendor command becomes a recording stub, and the
    effectful Tcl surfaces the emitted scripts use (``file
    mkdir``/``copy``/``delete``/``rename``, ``open`` and ``exit``) are replaced
    too, so running it with ``tclsh`` starts no vendor tool and writes nothing.
    It reports Tcl completeness, the number of stubbed vendor calls, and
    whether evaluating the script raised a Tcl error.

    This harness is a reviewable artifact.  Daedalus never runs it: the CLI
    that emits it spawns no process and opens no file.  A green harness result
    proves the text is parseable Tcl whose command words all resolve.  It is
    not evidence that AMD Vivado or Vitis HLS accepts the script.

    ``binary decode base64`` requires Tcl 8.6 or newer.
    """

    if not isinstance(script, EmittedTclScript):
        raise TclEmitError("parse harness input must be an EmittedTclScript")
    if script.target == PARSE_HARNESS_TARGET:
        raise TclEmitError("a parse harness cannot be its own subject")
    stubs = tuple(sorted(set(script.commands) - TCL_BUILTINS - {"get_property"}))
    if not stubs:
        raise TclEmitError("parse harness needs at least one vendor command to stub")
    encoded = base64.b64encode(script.data).decode("ascii")
    identities = (
        ("script_sha256", script.sha256),
        ("script_target", script.target),
        ("script_scope", script.scope),
    )
    lines: list[str] = []
    lines.extend(
        _banner(
            title="Daedalus emitted Tcl parse harness (no vendor command runs).",
            target=PARSE_HARNESS_TARGET,
            scope=script.scope,
            invocation="tclsh <this file>",
            identities=identities,
        )
    )
    lines.append("# The subject script is embedded below as base64, so this harness reads")
    lines.append("# no file and cannot be pointed at different bytes than the emitter saw.")
    lines.append("set daedalus_script_base64 {")
    lines.extend(encoded[offset : offset + 76] for offset in range(0, len(encoded), 76))
    lines.append("}")
    lines.extend(
        [
            f"set daedalus_expected_sha256 {{{script.sha256}}}",
            "set daedalus_calls [list]",
            "",
            "proc daedalus_record {name args} {",
            "    global daedalus_calls",
            "    lappend daedalus_calls $name",
            '    return ""',
            "}",
            "",
            "foreach daedalus_command [list \\",
        ]
    )
    lines.extend(f"    {name} \\" for name in stubs)
    lines.extend(
        [
            "] {",
            "    proc $daedalus_command {args} \\",
            '        "daedalus_record [list $daedalus_command]"',
            "}",
            "",
            "# Vendor property reads answer with the value the emitted script expects,",
            "# so the parse walks the success path instead of stopping at check one.",
            "proc get_property {property args} {",
            "    daedalus_record get_property",
            "    set key [string toupper $property]",
            '    if {$key eq "PART" && [info exists ::daedalus_part]} {',
            "        return $::daedalus_part",
            "    }",
            '    if {$key eq "TOP" && [info exists ::daedalus_top]} {',
            "        return $::daedalus_top",
            "    }",
            '    if {$key eq "BOARD_PART" && [info exists ::daedalus_board_part]} {',
            "        return $::daedalus_board_part",
            "    }",
            '    if {$key eq "PROGRESS"} {',
            '        return "100%"',
            "    }",
            '    if {$key eq "STATUS"} {',
            '        return "daedalus-stub-complete"',
            "    }",
            '    return ""',
            "}",
            "",
            "# Effectful Tcl surfaces are replaced so the harness writes nothing.",
            "rename file daedalus_real_file",
            "proc file {args} {",
            "    set subcommand [lindex $args 0]",
            "    switch -- $subcommand {",
            "        mkdir - copy - delete - rename {",
            "            daedalus_record file_$subcommand",
            '            return ""',
            "        }",
            "        exists {",
            "            return 1",
            "        }",
            "        default {",
            "            return [daedalus_real_file {*}$args]",
            "        }",
            "    }",
            "}",
            "",
            "rename open daedalus_real_open",
            "proc open {args} {",
            "    daedalus_record open",
            '    if {$::tcl_platform(platform) eq "windows"} {',
            "        return [daedalus_real_open NUL w]",
            "    }",
            "    return [daedalus_real_open /dev/null w]",
            "}",
            "",
            "rename exit daedalus_real_exit",
            "proc exit {{code 0}} {",
            "    global daedalus_exit_code",
            "    set daedalus_exit_code $code",
            "    return -code error -errorcode {DAEDALUS EXIT} \\",
            '        "daedalus-intercepted-exit"',
            "}",
            "",
            "set daedalus_body [binary decode base64 $daedalus_script_base64]",
            "set daedalus_complete [info complete $daedalus_body]",
            "",
            "set daedalus_exit_code {}",
            "set daedalus_error {}",
            "if {[catch {eval $daedalus_body} daedalus_result daedalus_options]} {",
            "    set daedalus_code [dict get $daedalus_options -errorcode]",
            '    if {[lindex $daedalus_code 0] ne "DAEDALUS"} {',
            "        set daedalus_error $daedalus_result",
            "    }",
            "}",
            "",
            'puts "DAEDALUS_TCL_PARSE sha256_expected=$daedalus_expected_sha256"',
            'puts "DAEDALUS_TCL_PARSE embedded_bytes=[string length $daedalus_body]"',
            'puts "DAEDALUS_TCL_PARSE complete=$daedalus_complete"',
            'puts "DAEDALUS_TCL_PARSE stub_calls=[llength $daedalus_calls]"',
            'puts "DAEDALUS_TCL_PARSE intercepted_exit=$daedalus_exit_code"',
            'puts "DAEDALUS_TCL_PARSE tcl_error=$daedalus_error"',
            'puts "DAEDALUS_TCL_PARSE vendor_acceptance_claimed=0"',
            'if {!$daedalus_complete || $daedalus_error ne ""} {',
            "    daedalus_real_exit 1",
            "}",
            "daedalus_real_exit 0",
            "",
        ]
    )
    return EmittedTclScript(
        target=PARSE_HARNESS_TARGET,
        scope=script.scope,
        text="\n".join(lines),
        bound_identities=identities,
        commands=stubs,
    )


def expected_emitted_outputs(scope: str) -> tuple[str, ...]:
    """Names the emitted Vivado script writes into its output directory."""

    if scope not in VIVADO_SCOPES:
        raise TclEmitError(f"scope must be one of {', '.join(VIVADO_SCOPES)}")
    if scope == "inspect":
        return ("inspect_summary.txt",)
    synth = {
        "synth_design.dcp",
        "utilization.rpt",
        "timing_summary.rpt",
        "drc.rpt",
        "methodology.rpt",
    }
    if scope == "synth":
        return tuple(sorted(synth | {"synth_summary.txt"}))
    return tuple(
        sorted(
            synth
            | {"route_status.rpt", "design.dcp", "design.bit", "impl_summary.txt"}
        )
    )


def emitted_script_payload(
    script: EmittedTclScript,
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical plan-payload row for one emitted script.

    The script travels *inside* the payload as ``text``.  Emission deliberately
    writes no file: the emitting command is effect-free, and the one admitted
    effect boundary of this CLI is ``run_admitted_eda``/``begin_effect``.  An
    operator who wants a file redirects the raw form to one themselves.
    """

    payload = {**script.to_dict(), "text": script.text}
    if extra:
        payload.update(dict(extra))
    return payload


__all__ = [
    "EmittedTclScript",
    "PARSE_HARNESS_TARGET",
    "TARGETS",
    "TCL_BUILTINS",
    "TCL_EMIT_SCHEMA",
    "TCL_SYNTAX_CHECKER",
    "TclCompleteness",
    "TclEmitError",
    "VITIS_HLS_COMMANDS",
    "VITIS_HLS_TARGET",
    "VIVADO_COMMANDS",
    "VIVADO_SCOPES",
    "VIVADO_TARGET",
    "emitted_command_words",
    "emitted_defined_procs",
    "emitted_script_payload",
    "expected_emitted_outputs",
    "render_parse_harness",
    "render_vitis_hls_flow",
    "render_vivado_project_flow",
    "tcl_brace_literal",
    "tcl_completeness",
    "tcl_info_complete",
    "tcl_path_literal",
]
