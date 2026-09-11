G1-IKARUS-25 file-tool fence lift (repaired), round 2 evidence regenerated from the working tree at HEAD 585b7ea4e141. Advisory council evidence.
WHAT THE LIFT DOES: file.list/read/mkdir/move and file.write of NEW files now run through the handle-anchored adapter (daedalus.runtimes.computer_files.WorkspaceFiles) behind policy admission, EffectLease and receipts; file.write WITH expected_sha256 (replacement of an existing file) and path-based vision (vision.match/vision.changes) stay fenced; file tools are Windows-only (POSIX reports unavailable).
WHAT WAS JUST REPAIRED: (1) a refusal raised AFTER the adapter returned (post-dispatch checkpoint: cancellation, deadline, policy drift, re-admission) is no longer classified as no-effect -- the lease stays STARTED for reconciliation; (2) every failure after an effect receipt exists persists a digest-bound failure record (daedalus-computer-failure/1) and the CANCELLED terminal binds that record's sha256; (3) the projected file.write schema, capabilities()['path_io_release_lock'] and the kernel fence all read RELEASE_REPLACE_FENCED at call time.
Since the first round, the adapter's `_replace` rollback also reports a host OSError as uncertain (computer_files.py @ sha256 7120cf2a535f80a2489273081185e7bbf21c20c9c2f31451d069f5aa4a1a21e3).

=== FULL DIFF: daedalus/kernel/policy/computer.py ===
diff --git a/daedalus/kernel/policy/computer.py b/daedalus/kernel/policy/computer.py
index 5d6c3fa7..70926541 100644
--- a/daedalus/kernel/policy/computer.py
+++ b/daedalus/kernel/policy/computer.py
@@ -27,15 +27,32 @@ BROWSER_TOOLS = ("browser.navigate", "browser.read", "browser.click", "browser.f
 ALL_COMPUTER_TOOLS = frozenset(FILE_TOOLS + VISION_TOOLS + DESKTOP_TOOLS + BROWSER_TOOLS)
 # v0.1.6 release fence.  ``Path.resolve`` plus a later pathname operation is
 # not a write-root boundary: another process can replace a checked ancestor
-# with a symlink/junction between those two operations.  Keep legacy policy
-# files readable so owners can remove old grants, but never turn those grants
-# into runtime authority.  Observation-backed vision does not open a workspace
-# path and remains a separate, explicitly constrained capability.
+# with a symlink/junction between those two operations.  G1-IKARUS-24/25
+# replaced the pathname file helpers with the handle-anchored adapter
+# (``daedalus.runtimes.computer_files``), so the five file tools are admitted
+# again; path-based vision still opens a workspace pathname and stays fenced,
+# and observation-backed vision remains a separate, explicitly constrained
+# capability.  Replacing an existing file runs the adapter's two-rename
+# protocol, whose crash window has no service-owned reconciliation yet, so
+# that one shape stays fenced with its own reason.  Keep legacy policy files
+# readable so owners can remove old grants, but never turn those grants into
+# runtime authority.
 PATH_IO_RELEASE_REFUSAL = (
     "workspace path tools are disabled in v0.1.6 until handle-relative, "
     "reparse-safe I/O is independently verified"
 )
-RELEASE_DISABLED_TOOLS = frozenset(FILE_TOOLS + ("vision.match", "vision.changes"))
+FILE_REPLACE_RELEASE_REFUSAL = (
+    "replacing an existing file is disabled in v0.1.6 until the two-rename "
+    "replacement has a service-owned crash reconciliation; create a new file or move"
+)
+RELEASE_DISABLED_TOOLS = frozenset(("vision.match", "vision.changes"))
+# Release constant: replacement stays fenced until the two-rename protocol has
+# a service-owned crash reconciliation (G1-IKARUS-24 HOLD, G1-IKARUS-25, design
+# G1-IKARUS-27). Only a release packet lowers it. The runtime reads it at call
+# time so the projected schema, the capability claim and this fence cannot
+# disagree; the adapter suite lowers it per test through monkeypatch (restored
+# automatically) to exercise the protocol below the fence.
+RELEASE_REPLACE_FENCED = True
 RELEASE_OBSERVATION_ONLY_TOOLS = frozenset(("vision.inspect", "vision.ocr"))
 _PROTECTED = frozenset({".git", ".agentenv", ".codex", "agents.md", "computer-policy.json",
                         "ikarus_ariadne_master_plan.md", "ikarus_ariadne_master_plan.amendments.jsonl"})
@@ -72,6 +89,8 @@ def enforce_release_tool_fence(tool: str, arguments: Mapping[str, Any]) -> None:
     """
     if tool in RELEASE_DISABLED_TOOLS:
         raise ComputerRefused(PATH_IO_RELEASE_REFUSAL)
+    if RELEASE_REPLACE_FENCED and tool == "file.write" and "expected_sha256" in arguments:
+        raise ComputerRefused(FILE_REPLACE_RELEASE_REFUSAL)
     if tool in RELEASE_OBSERVATION_ONLY_TOOLS:
         # The lease issuer calls this same admission seam independently of the
         # runtime.  Bind the complete release shape here: accepting merely the

=== SELECTED HUNKS: daedalus/runtimes/computer.py (only hunks touching dispatched / provably_no_effect / _store_failure_record / path_io_release_lock / _release_tool_spec / filesystem_scope_kind; import, Windows-only reason, self._files init, _dispatch routing and the 80-line removal of the legacy _file() helper are omitted) ===
diff --git a/daedalus/runtimes/computer.py b/daedalus/runtimes/computer.py
index e498182d..67c41e3f 100644
--- a/daedalus/runtimes/computer.py
+++ b/daedalus/runtimes/computer.py
@@ -74,6 +75,13 @@ def _release_tool_spec(tool: str) -> tuple[str, dict[str, Any]] | None:
         return None
     description, parameters = TOOL_SPECS[tool]
     parameters = json.loads(json.dumps(parameters))
+    if tool == "file.write" and _release_policy.RELEASE_REPLACE_FENCED:
+        # Replacement stays fenced (FILE_REPLACE_RELEASE_REFUSAL): do not offer
+        # the one shape the kernel would refuse. The flag is read at call time
+        # so this projection, capabilities() and the kernel fence agree.
+        parameters["properties"].pop("expected_sha256", None)
+        description = ("Create a NEW UTF-8 file inside the computer workspace. Replacing an "
+                       "existing file is disabled in this release; read back to verify.")
     if tool in RELEASE_OBSERVATION_ONLY_TOOLS:
         parameters["properties"].pop("path", None)
         parameters["required"] = ["observation_id"]
@@ -171,7 +184,10 @@ class ComputerService:
                     description += " Enabled origins: " + ", ".join(self._policy.origins)
                 available.append({"name": tool, "description": description, "parameters": parameters})
         return {"enabled": bool(available), "tools": available, "unavailable": unavailable,
-                "path_io_release_lock": PATH_IO_RELEASE_REFUSAL,
+                "path_io_release_lock": "; ".join(
+                    [f"path-based vision: {PATH_IO_RELEASE_REFUSAL}"]
+                    + ([f"file.write with expected_sha256: {FILE_REPLACE_RELEASE_REFUSAL}"]
+                       if _release_policy.RELEASE_REPLACE_FENCED else [])),
                 "workspace": str(self._policy.workspace), "policy_sha256": self.policy_digest,
                 "planner_provider": self._policy.planner_provider, "planner_model": self._policy.planner_model,
                 "allow_remote_context": self._policy.allow_remote_context,
@@ -213,6 +229,8 @@ class ComputerService:
         granted = None
         execution = None
         external_started = False
+        dispatched = False
+        operation_digest = None
         try:
             _validate_arguments(tool, arguments)
             # Detach arguments from caller-owned mutable containers before admission.
@@ -254,6 +272,9 @@ class ComputerService:
                 self.check_cancelled()
                 external_started = True
                 result = self._dispatch(tool, arguments)
+                # The adapter returned: whatever is refused from here on was
+                # observed AFTER the host effect and can never mean "no effect".
+                dispatched = True
                 self.check_cancelled()
                 # Secret-floor filtering is performed before results enter CAS
                 # or the planner, including arbitrary web/application text.
@@ -265,7 +286,8 @@ class ComputerService:
                           "mission_id": mission_id, "attempt_id": attempt_id,
                           "policy_sha256": self.policy_digest,
                           "host_mutation": tool in {"file.write", "file.mkdir", "file.move", "app.launch", "desktop.click", "desktop.type", "desktop.key", "browser.click", "browser.fill"},
-                          "filesystem_scope_kind": "computer-policy-workspace-relative"}
+                          "filesystem_scope_kind": ("handle-anchored-computer-workspace" if tool in FILE_TOOLS
+                                                    else "computer-policy-workspace-relative")}
                 artifact = store_canonical_json(self.control / "computer-artifacts", output)
                 terminal = granted.authorization.finish_effect(started.receipt, outcome="COMPLETED",
                     output_digests=(artifact.sha256,), detail_sha256=artifact.sha256)
@@ -287,19 +309,75 @@ class ComputerService:
         except (Exception, KeyboardInterrupt) as exc:
             # A failure after entering an adapter is an unknown external outcome.
             # Keep STARTED for reconciliation; never retry or invent failure.
-            if started is not None and started.execute and not external_started:
+            # The one exception is the file adapter's own contract: a plain
+            # ComputerRefused or an interruption it annotates with
+            # effect_state "none" is raised only before any host effect, while
+            # anything it cannot prove carries effect_state "uncertain".
+            # A refusal raised by the post-dispatch checkpoint (cancellation,
+            # deadline, policy drift, re-admission) is observed after the effect
+            # landed; the lease then stays STARTED for reconciliation.
+            effect_state = getattr(exc, "effect_state", None)
+            provably_no_effect = external_started and tool in FILE_TOOLS and (
+                # A plain refusal is raised by the adapter only before an effect;
+                # an interruption is trusted only when the adapter typed it.
+                (isinstance(exc, ComputerRefused) and effect_state in (None, "none"))
+                or (isinstance(exc, KeyboardInterrupt) and effect_state == "none")
+            )
+            record = None
+            if started is not None:
+                # Once an effect receipt exists, its failure leaves a digest-bound
+                # record: error class and message, the adapter's proven effect
+                # state and the paths a reconciliation must inspect. The result
+                # floor applies before anything enters CAS.
+                record = self._store_failure_record(
+                    tool=tool, operation_digest=operation_digest, mission_id=mission_id,
+                    attempt_id=attempt_id, exc=exc, effect_state=effect_state,
+                    external_started=external_started, dispatched=dispatched,
+                    provably_no_effect=provably_no_effect)
+            if started is not None and started.execute and (not external_started or provably_no_effect):
                 try:
                     granted.authorization.finish_effect(started.receipt, outcome="CANCELLED",
-                        detail_sha256=canonical_sha({"error": type(exc).__name__}))
+                        detail_sha256=record.sha256 if record is not None
+                        else canonical_sha({"error": type(exc).__name__}))
                     granted.retain_terminal_record(execution)
                 except Exception:
                     pass
-            return {"ok": False, "state": "reconciliation_required" if external_started else "blocked",
-                    "error": str(exc)[:1200], "error_type": type(exc).__name__}
+            blocked = not external_started or provably_no_effect
+            failure = {"ok": False, "state": "blocked" if blocked else "reconciliation_required",
+                       "error": str(exc)[:1200], "error_type": type(exc).__name__}
+            if record is not None:
+                failure["evidence"] = {"failure_record": record.to_dict()}
+            return failure
         finally:
             self._active_authorization = None
             self._active_operation = None
 
+    def _store_failure_record(self, *, tool: str, operation_digest: str | None, mission_id: str,
+                              attempt_id: str, exc: BaseException, effect_state: str | None,
+                              external_started: bool, dispatched: bool, provably_no_effect: bool):
+        """Persist what a later reconciliation needs; never mask the failure itself."""
+        recovery = getattr(exc, "recovery_paths", None) or ()
+        failure = {"schema": "daedalus-computer-failure/1", "tool": tool,
+                   "operation_sha256": operation_digest, "mission_id": mission_id, "attempt_id": attempt_id,
+                   "policy_sha256": self.policy_digest, "error_type": type(exc).__name__,
+                   "error": str(exc)[:1200], "effect_state": effect_state,
+                   "recovery_paths": [str(path) for path in recovery],
+                   "external_started": external_started, "dispatched": dispatched,
+                   "provably_no_effect": provably_no_effect}
+        try:
+            rendered = json.dumps(failure, ensure_ascii=False, allow_nan=False)
+            if secret_floor_rule("computer-failure.json", rendered):
+                failure = {"schema": "daedalus-computer-failure/1", "tool": tool,
+                           "operation_sha256": operation_digest, "mission_id": mission_id,
+                           "attempt_id": attempt_id, "policy_sha256": self.policy_digest,
+                           "error_type": type(exc).__name__, "effect_state": effect_state,
+                           "withheld": True, "reason": "secret floor",
+                           "external_started": external_started, "dispatched": dispatched,
+                           "provably_no_effect": provably_no_effect}
+            return store_canonical_json(self.control / "computer-artifacts", failure)
+        except Exception:
+            return None
+
     def _read_bytes(self, value: str) -> bytes:
         refuse_workspace_path_io()
         path = self._policy.path(value, must_exist=True)
