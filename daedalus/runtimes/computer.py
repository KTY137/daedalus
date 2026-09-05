"""Trusted computer tools behind canonical persisted effect admission.

The model supplies data. Policy is loaded from the kernel control root, and
every operation is re-admitted immediately before the private adapter runs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from daedalus.atomic import ExclusiveFileLock
from daedalus.kernel.artifacts import store_canonical_json
from daedalus.kernel.effects import EffectLeaseError
from daedalus.kernel.offload_lease import acquire_effect_lease, WaveLeaseDenied
from daedalus.kernel.policy.computer import (
    ComputerRefused, ComputerPolicy, VISION_TOOLS, DESKTOP_TOOLS,
    BROWSER_TOOLS, PATH_IO_RELEASE_REFUSAL, RELEASE_DISABLED_TOOLS,
    RELEASE_OBSERVATION_ONLY_TOOLS, admit_operation, load_policy, policy_path,
    refuse_workspace_path_io,
)
from daedalus.limit_policy import load_from_env as load_limit_policy
from daedalus.sensitivity import secret_floor_rule
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.killswitch import KillSwitch, LoopHalted, control_root


ENTRYPOINT = "python.ikarus_computer"
# Bind the executing code at import, not a later edited file on disk. Frozen
# distributions bind their containing executable instead of absent .py files.
_SOURCE_REVISION = hashlib.sha256(
    (Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)).read_bytes()
).hexdigest()


def _schema(fields: dict[str, Any], required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": fields, "required": list(required), "additionalProperties": False}


_STRING = {"type": "string"}
_NUMBER = {"type": "number"}
_SHA256_STRING = {"type": "string", "minLength": 64, "maxLength": 64, "pattern": "^[0-9a-f]{64}$"}
TOOL_SPECS = {
    "file.list": ("List up to 200 entries inside the computer workspace.", _schema({"path": _STRING})),
    "file.read": ("Read a UTF-8 file and report its content hash.", _schema({"path": _STRING}, ("path",))),
    "file.write": ("Create a UTF-8 file: omit expected_sha256 for a NEW file. Replacing requires its exact expected_sha256 from file.read. Never invent a hash. Read back to verify.", _schema({"path": _STRING, "text": _STRING, "expected_sha256": _SHA256_STRING}, ("path", "text"))),
    "file.mkdir": ("Create a directory inside the workspace.", _schema({"path": _STRING}, ("path",))),
    "file.move": ("Move one regular file into a nonexistent destination; source hash is required.", _schema({"source": _STRING, "destination": _STRING, "expected_sha256": _SHA256_STRING}, ("source", "destination", "expected_sha256"))),
    "vision.inspect": ("Measure an image with local OpenCV. Supply path OR a fresh desktop observation_id.", _schema({"path": _STRING, "observation_id": _STRING})),
    "vision.match": ("Find a unique image template with local OpenCV. Supply path OR desktop observation_id, and template path. Ambiguity is a refusal.", _schema({"path": _STRING, "observation_id": _STRING, "template": _STRING, "threshold": _NUMBER}, ("template",))),
    "vision.changes": ("Find changed regions between two image files.", _schema({"before": _STRING, "after": _STRING}, ("before", "after"))),
    "vision.ocr": ("Read image text locally. Supply path OR a fresh desktop observation_id; word image_rect coordinates can ground desktop clicks.", _schema({"path": _STRING, "observation_id": _STRING})),
    "desktop.observe": ("Observe only the enabled foreground application window.", _schema({})),
    "desktop.click": ("Click a freshly observed window pixel; expected describes the result to verify.", _schema({"observation_id": _STRING, "x": _NUMBER, "y": _NUMBER, "expected": _STRING}, ("observation_id", "x", "y", "expected"))),
    "desktop.type": ("Type text into the freshly observed application.", _schema({"observation_id": _STRING, "text": _STRING, "expected": _STRING}, ("observation_id", "text", "expected"))),
    "desktop.key": ("Press one permitted navigation/editing key in the observed window.", _schema({"observation_id": _STRING, "key": _STRING, "expected": _STRING}, ("observation_id", "key", "expected"))),
    "app.launch": ("Launch a named application with the exact owner-configured arguments.", _schema({"application": _STRING}, ("application",))),
    "browser.navigate": ("Open a page on an explicitly enabled origin in an isolated browser.", _schema({"url": _STRING}, ("url",))),
    "browser.read": ("Observe current browser DOM and receive a fresh observation token.", _schema({})),
    "browser.click": ("Click an observed non-submit element; read again to verify.", _schema({"observation_id": _STRING, "selector": _STRING}, ("observation_id", "selector"))),
    "browser.fill": ("Fill a text field in the observed page, without submitting.", _schema({"observation_id": _STRING, "selector": _STRING, "text": _STRING}, ("observation_id", "selector", "text"))),
}


def _release_tool_spec(tool: str) -> tuple[str, dict[str, Any]] | None:
    """Project only executable v0.1.6 tool shapes into the model capability."""
    if tool in RELEASE_DISABLED_TOOLS:
        return None
    description, parameters = TOOL_SPECS[tool]
    parameters = json.loads(json.dumps(parameters))
    if tool in RELEASE_OBSERVATION_ONLY_TOOLS:
        parameters["properties"].pop("path", None)
        parameters["required"] = ["observation_id"]
        description = (
            "Inspect a fresh policy-scoped desktop observation with local OpenCV."
            if tool == "vision.inspect"
            else "Read text from a fresh policy-scoped desktop observation with local Windows OCR."
        )
    return description, parameters


def _validate_arguments(tool: str, args: dict) -> None:
    if tool not in TOOL_SPECS or type(args) is not dict:
        raise ComputerRefused("unknown tool or malformed arguments")
    schema = TOOL_SPECS[tool][1]
    if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
        raise ComputerRefused("tool arguments do not match its schema")
    if tool in {"vision.inspect", "vision.match", "vision.ocr"} and (("path" in args) == ("observation_id" in args)):
        raise ComputerRefused("vision requires exactly one path or desktop observation_id")
    for key, value in args.items():
        kind = schema["properties"][key]["type"]
        if kind == "string" and not isinstance(value, str):
            raise ComputerRefused(f"{key} must be text")
        if key == "expected_sha256" and (len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)):
            raise ComputerRefused("expected_sha256 must be an observed lowercase SHA-256")
        if kind == "number" and (type(value) not in (int, float) or not __import__("math").isfinite(value)):
            raise ComputerRefused(f"{key} must be finite")


def _release_unavailable_reason(policy: ComputerPolicy, tool: str) -> str:
    """Return the same static prerequisite refusal used by projection/execution."""
    reason = ""
    if tool in RELEASE_OBSERVATION_ONLY_TOOLS:
        if "desktop.observe" not in policy.tools:
            reason = "Observation-only release mode requires desktop.observe"
        elif os.name != "nt":
            reason = "Windows desktop observation required"
        elif importlib.util.find_spec("mss") is None:
            reason = "Install daedalus[computer] for capture"
    if tool in VISION_TOOLS and importlib.util.find_spec("cv2") is None:
        reason = "Install daedalus[computer] for OpenCV"
    if tool == "vision.ocr":
        from .computer_ocr import WindowsOCR
        ocr = WindowsOCR.availability()
        if not ocr["available"]:
            reason = ocr["reason"]
    if tool in DESKTOP_TOOLS and os.name != "nt":
        reason = "Windows adapter required"
    elif tool.startswith("desktop.") and importlib.util.find_spec("mss") is None:
        reason = "Install daedalus[computer] for capture"
    if tool in BROWSER_TOOLS and importlib.util.find_spec("playwright") is None:
        reason = "Install daedalus[computer] and Playwright Chromium"
    return reason


class ComputerService:
    def __init__(self, authority_root: Path, workspace: Path | None = None):
        self.authority_root = Path(authority_root).resolve()
        self.control = control_root(self.authority_root)
        self._policy = load_policy(self.authority_root)
        if workspace is not None and Path(workspace).resolve() != self._policy.workspace:
            raise ComputerRefused("caller cannot override the owner-configured workspace")
        self.policy_digest = self._policy.digest
        self.limit_policy = load_limit_policy()
        self._switch = KillSwitch(repo_root=self.authority_root)
        self._deadline = (time.monotonic() + self._policy.timeout_s
                          if self.limit_policy.enforces("wall_time") else None)
        self._desktop = None
        self._browser = None
        self._active_authorization = None
        self._active_operation = None
        self._cancellation_probe: Callable[[], bool] | None = None

    def set_cancellation_probe(self, probe: Callable[[], bool] | None) -> None:
        """Bind the current mission's cooperative stop signal to host checkpoints."""
        if probe is not None and not callable(probe):
            raise ComputerRefused("cancellation probe must be callable")
        self._cancellation_probe = probe

    def capabilities(self) -> dict:
        available: list[dict] = []
        unavailable: dict[str, str] = {}
        for tool in self._policy.tools:
            projected = _release_tool_spec(tool)
            if projected is None:
                # Reported, not dropped: a configured policy whose every tool is
                # release-locked was indistinguishable from no policy at all
                # (measured 2026-09-05, mission computer-loop-measure-02).
                unavailable[tool] = PATH_IO_RELEASE_REFUSAL
                continue
            reason = _release_unavailable_reason(self._policy, tool)
            if reason:
                unavailable[tool] = reason
            else:
                description, parameters = projected
                if tool == "app.launch":
                    parameters["properties"]["application"]["enum"] = list(dict(self._policy.applications))
                if tool == "browser.navigate":
                    description += " Enabled origins: " + ", ".join(self._policy.origins)
                available.append({"name": tool, "description": description, "parameters": parameters})
        return {"enabled": bool(available), "tools": available, "unavailable": unavailable,
                "path_io_release_lock": PATH_IO_RELEASE_REFUSAL,
                "workspace": str(self._policy.workspace), "policy_sha256": self.policy_digest,
                "planner_provider": self._policy.planner_provider, "planner_model": self._policy.planner_model,
                "allow_remote_context": self._policy.allow_remote_context,
                "max_steps": self._policy.max_steps, "timeout_s": self._policy.timeout_s,
                "persistent_goals": "canonical mission receipts; interrupted effects require reconciliation",
                "scheduled_tasks": "durable queue and finite repeated jobs with cancellation; matching File Bridge watcher or /computer run-due required",
                "planning": "advisory plans, bounded proposal correction and repeated-observation stall detection; existing policy limits apply",
                "product_context": "explicit owner notes; retained skill metadata is unavailable under the v0.1.6 path-I/O release lock",
                "browser_limits": "static pages only; JavaScript, submission and downloads unavailable",
                "desktop_validation": "live foreground input not yet measured; application support requires verification"}

    def _admit_release_capability(self, tool: str, arguments: dict) -> None:
        """Refuse projected/static/state prerequisites before a lease is issued."""
        if _release_tool_spec(tool) is None:
            raise ComputerRefused(PATH_IO_RELEASE_REFUSAL)
        reason = _release_unavailable_reason(self._policy, tool)
        if reason:
            raise ComputerRefused(reason)
        if tool in RELEASE_OBSERVATION_ONLY_TOOLS:
            if self._desktop is None:
                raise ComputerRefused("a current policy-scoped desktop observation is required")
            self._desktop.require_fresh_observation(arguments["observation_id"])

    def check_cancelled(self) -> None:
        self._switch.checkpoint()
        if self._cancellation_probe is not None and self._cancellation_probe():
            raise ComputerRefused("computer task cancellation requested")
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise ComputerRefused("computer task deadline exceeded")
        if load_policy(self.authority_root).digest != self.policy_digest:
            raise ComputerRefused("computer policy changed; a new task is required")
        if self._active_authorization is not None:
            self._active_authorization.verify()
            admit_operation(self.authority_root, self._active_operation)

    def execute(self, tool: str, arguments: dict, *, mission_id: str, attempt_id: str) -> dict:
        """Single registered computer effect entrypoint; no effect on denial."""
        started = None
        granted = None
        execution = None
        external_started = False
        try:
            _validate_arguments(tool, arguments)
            # Detach arguments from caller-owned mutable containers before admission.
            arguments = json.loads(json.dumps(arguments, allow_nan=False))
            operation = {"tool": tool, "arguments": arguments, "policy_sha256": self.policy_digest}
            self.check_cancelled()
            admit_operation(self.authority_root, operation)
            self._admit_release_capability(tool, arguments)
            operation_digest = canonical_sha(operation)
            identity = canonical_sha({"mission": mission_id, "attempt": attempt_id})[:32]
            # Source identity explicitly describes trusted adapter code, not a
            # fictional source repository for a general computer task.
            source_revision = _SOURCE_REVISION
            with ExclusiveFileLock(self.control / "computer-execution.lock", timeout_s=1,
                                   label="computer operation"):
                granted = acquire_effect_lease(
                    self.authority_root, entrypoint_id=ENTRYPOINT,
                    source_revision=source_revision, mission_id=mission_id, attempt_id=attempt_id,
                    positions=1, tools=(tool,), timeout_s=self._policy.timeout_s,
                    operation_sha256=operation_digest, computer_operation=operation,
                    lease_id="computer-" + identity, switch=self._switch,
                    evidence_root=self.control / "computer-effect-evidence",
                    limit_policy=self.limit_policy,
                )
                if isinstance(granted, WaveLeaseDenied):
                    raise ComputerRefused("; ".join(granted.reasons))
                execution = granted.execution_for(0, tools=(tool,), operation_sha256=operation_digest)
                required = ("lease_subject", "lease_execution:" + execution.execution_id)
                if any(not granted.evidence_records.get(key) for key in required):
                    raise ComputerRefused("effect subject or execution evidence was not retained")
                ignored = f"disjointness: {ENTRYPOINT} declares no containment contract, so this grant retains no primary-checkout disjointness record"
                if any(error != ignored for error in granted.evidence_errors):
                    raise ComputerRefused("effect evidence unavailable before start")
                started = granted.authorization.begin_effect(execution)
                if not started.execute:
                    return {"ok": False, "state": "reconciliation_required", "error": "execution already started or completed; no repeated effect"}
                self._active_authorization = granted.authorization
                self._active_operation = operation
                self.check_cancelled()
                external_started = True
                result = self._dispatch(tool, arguments)
                self.check_cancelled()
                # Secret-floor filtering is performed before results enter CAS
                # or the planner, including arbitrary web/application text.
                rendered = json.dumps(result, ensure_ascii=False, allow_nan=False)
                if secret_floor_rule("computer-result.json", rendered):
                    result = {"withheld": True, "reason": "secret floor", "postcondition_verified": False}
                output = {"schema": "daedalus-computer-result/1", "tool": tool,
                          "operation_sha256": operation_digest, "result": result,
                          "mission_id": mission_id, "attempt_id": attempt_id,
                          "policy_sha256": self.policy_digest,
                          "host_mutation": tool in {"file.write", "file.mkdir", "file.move", "app.launch", "desktop.click", "desktop.type", "desktop.key", "browser.click", "browser.fill"},
                          "filesystem_scope_kind": "computer-policy-workspace-relative"}
                artifact = store_canonical_json(self.control / "computer-artifacts", output)
                terminal = granted.authorization.finish_effect(started.receipt, outcome="COMPLETED",
                    output_digests=(artifact.sha256,), detail_sha256=artifact.sha256)
                retained = granted.retain_terminal_record(execution)
                if retained is None:
                    raise ComputerRefused("terminal evidence could not be retained")
                return {"ok": True, "state": "completed", "result": result,
                        "evidence": {"artifact": artifact.to_dict(), "lease_sha256": granted.lease.digest,
                                     "start_sha256": started.receipt.receipt_sha256,
                                     "terminal_sha256": terminal.receipt_sha256,
                                     "binding": {"subject_record_sha256": granted.evidence_records["lease_subject"],
                                                 "execution_record_sha256": granted.evidence_records["lease_execution:" + execution.execution_id],
                                                 "execution_request_sha256": execution.digest,
                                                 "execution_id": execution.execution_id,
                                                 "source_revision": source_revision,
                                                 "attempt_id": attempt_id,
                                                 "operation_sha256": operation_digest,
                                                 "terminal_record_sha256": retained["record_sha256"]}}}
        except (Exception, KeyboardInterrupt) as exc:
            # A failure after entering an adapter is an unknown external outcome.
            # Keep STARTED for reconciliation; never retry or invent failure.
            if started is not None and started.execute and not external_started:
                try:
                    granted.authorization.finish_effect(started.receipt, outcome="CANCELLED",
                        detail_sha256=canonical_sha({"error": type(exc).__name__}))
                    granted.retain_terminal_record(execution)
                except Exception:
                    pass
            return {"ok": False, "state": "reconciliation_required" if external_started else "blocked",
                    "error": str(exc)[:1200], "error_type": type(exc).__name__}
        finally:
            self._active_authorization = None
            self._active_operation = None

    def _read_bytes(self, value: str) -> bytes:
        refuse_workspace_path_io()
        path = self._policy.path(value, must_exist=True)
        if not path.is_file() or path.stat().st_size > self._policy.max_file_bytes:
            raise ComputerRefused("file is not regular or exceeds configured size")
        with path.open("rb") as stream:
            data = stream.read(self._policy.max_file_bytes + 1)
        if len(data) > self._policy.max_file_bytes:
            raise ComputerRefused("file exceeds configured size")
        return data

    def _dispatch(self, tool: str, args: dict) -> dict:
        if tool.startswith("file."):
            return self._file(tool, args)
        if tool.startswith("vision."):
            from daedalus.runtimes.computer_vision import OpenCVVision, ImageCoordinateFrame
            from daedalus.runtimes.computer_ocr import WindowsOCR
            vision = OpenCVVision(ocr_adapter=WindowsOCR(self.check_cancelled) if tool == "vision.ocr" else None)
            if tool == "vision.changes":
                return vision.detect_changes(self._read_bytes(args["before"]), self._read_bytes(args["after"]))
            frame = None
            if "observation_id" in args:
                if self._desktop is None or "desktop.observe" not in self._policy.tools:
                    raise ComputerRefused("a current policy-scoped desktop observation is required")
                data, native_frame = self._desktop.capture_png(args["observation_id"])
                frame = ImageCoordinateFrame(
                    coordinate_space="desktop", origin_x=native_frame["origin_x"],
                    origin_y=native_frame["origin_y"], monitor_id=str(native_frame.get("monitor_id", "")),
                    window_id=str(native_frame["window_id"]),
                    captured_at=native_frame.get("captured_at"),
                )
            else:
                data = self._read_bytes(args["path"])
            if tool == "vision.match":
                return vision.match_template(data, self._read_bytes(args["template"]), threshold=args.get("threshold", .9), frame=frame)
            return (vision.read_text if tool == "vision.ocr" else vision.inspect)(data, frame=frame)
        if tool in DESKTOP_TOOLS:
            from daedalus.runtimes.computer_desktop import DesktopAdapter
            if self._desktop is None:
                self._desktop = DesktopAdapter(self._policy, self.check_cancelled, self.control)
            return self._desktop.execute(tool, args)
        if tool in BROWSER_TOOLS:
            from daedalus.runtimes.computer_browser import BrowserAdapter
            if self._browser is None:
                self._browser = BrowserAdapter(self._policy, self.check_cancelled, self.control)
            return self._browser.execute(tool, args)
        raise ComputerRefused("unknown computer tool")

    def _file(self, tool: str, args: dict) -> dict:
        refuse_workspace_path_io()
        policy = self._policy
        path = policy.path(args.get("path", "."))
        if tool == "file.list":
            if not path.is_dir():
                raise ComputerRefused("directory does not exist")
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
                if len(entries) >= 200:
                    break
                relative = child.relative_to(policy.workspace).as_posix()
                try:
                    safe = policy.path(relative, must_exist=True)
                except ComputerRefused:
                    continue
                entries.append({"path": relative, "kind": "directory" if safe.is_dir() else "file"})
            return {"entries": entries, "limit": 200, "postcondition_verified": True}
        if tool == "file.read":
            data = self._read_bytes(args["path"])
            text = data.decode("utf-8")
            if secret_floor_rule(args["path"], text):
                raise ComputerRefused("file text withheld by secret floor")
            return {"path": args["path"], "text": text, "sha256": hashlib.sha256(data).hexdigest(), "postcondition_verified": True}
        if tool == "file.mkdir":
            self.check_cancelled()
            path.mkdir(exist_ok=True)
            return {"path": args["path"], "postcondition_verified": path.is_dir()}
        if tool == "file.move":
            source = policy.path(args["source"], must_exist=True)
            destination = policy.path(args["destination"])
            data = self._read_bytes(args["source"])
            digest = hashlib.sha256(data).hexdigest()
            if destination.exists() or digest != args["expected_sha256"]:
                raise ComputerRefused("move source changed or destination exists")
            self.check_cancelled()
            source.rename(destination)
            return {"path": args["destination"], "sha256": digest,
                    "postcondition_verified": not source.exists() and hashlib.sha256(self._read_bytes(args["destination"])).hexdigest() == digest}
        if tool == "file.write":
            data = args["text"].encode("utf-8")
            if len(data) > policy.max_file_bytes or secret_floor_rule(args["path"], args["text"]):
                raise ComputerRefused("file content exceeds size or secret policy")
            if path.exists():
                old = self._read_bytes(args["path"])
                if hashlib.sha256(old).hexdigest() != args.get("expected_sha256"):
                    raise ComputerRefused("replacing a file requires its current expected_sha256")
            elif "expected_sha256" in args:
                raise ComputerRefused("expected file no longer exists")
            self.check_cancelled()
            if path.exists():
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    self.check_cancelled()
                    policy.path(args["path"])
                    if hashlib.sha256(self._read_bytes(args["path"])).hexdigest() != args.get("expected_sha256"):
                        raise ComputerRefused("file changed before replacement")
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                with path.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            digest = hashlib.sha256(data).hexdigest()
            return {"path": args["path"], "sha256": digest, "bytes": len(data),
                    "postcondition_verified": hashlib.sha256(self._read_bytes(args["path"])).hexdigest() == digest}
        raise ComputerRefused("unknown file tool")

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()


def computer_status(authority_root: Path) -> dict:
    try:
        service = ComputerService(authority_root)
        return {**service.capabilities(), "configuration_path": str(policy_path(authority_root)),
                "configuration": service._policy.to_dict()}
    except (ComputerRefused, OSError, ValueError) as exc:
        return {"enabled": False, "tools": [], "error": str(exc),
                "configuration_path": str(policy_path(authority_root)),
                "setup": "Use /computer setup to initialize separate computer control state."}


def setup_computer(authority_root: Path, *, owner_confirmed: bool = False) -> dict:
    """Explicit interface setup; never exposed in the model's tool inventory.

    Fresh setup stores no tool grants. Programs or browser origins require
    owner configuration; this function never widens an existing policy or
    clears an operator's stop marker.
    """
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision, begin_effect

    if owner_confirmed is not True:
        raise ComputerRefused("explicit owner setup is required")
    root = Path(authority_root).resolve()
    control = control_root(root)
    destination = policy_path(root)
    if destination.exists():
        return {"ok": True, "created": False, **computer_status(root)}
    workspace = control.parent.parent / "computer-workspaces" / control.name
    # Do not write dormant unsafe grants into a fresh policy. Owners may add
    # independently admitted non-path tools later with /computer configure.
    policy = ComputerPolicy(workspace=workspace, tools=())
    receipt = begin_effect(
        "python.ikarus_computer_setup",
        REGISTRY_BY_ID["python.ikarus_computer_setup"].effects,
        (process_guard_boundary_decision(), GuardDecision("computer.configuration", True,
            f"explicit owner setup; fixed workspace; absent policy; sha256={policy.digest}")),
    )
    with ExclusiveFileLock(control / "computer-setup.lock", timeout_s=1):
        if destination.exists():
            return {"ok": True, "created": False, **computer_status(root)}
        # Initial setup may arm a previously unused switch. An existing sticky
        # stop refuses force=False, so setup cannot resume stopped work.
        switch = KillSwitch(repo_root=root)
        if not switch.read_state().running:
            switch.arm(force=False, note="explicit Ikarus computer setup")
        started = store_canonical_json(control / "computer-artifacts", {
            "schema": "daedalus-computer-setup/1", "phase": "admitted",
            "boundary": receipt.to_dict(), "policy_sha256": policy.digest,
        })
        workspace.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            json.dump(policy.to_dict(), stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        load_policy(root)
        finished = store_canonical_json(control / "computer-artifacts", {
            "schema": "daedalus-computer-setup/1", "phase": "completed",
            "start_sha256": started.sha256, "policy_sha256": policy.digest,
        })
    return {"ok": True, "created": True, "evidence": finished.to_dict(), **computer_status(root)}
