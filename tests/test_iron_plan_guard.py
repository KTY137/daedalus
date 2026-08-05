from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import iron_plan_guard as guard
from tools import iron_plan_hook_runner as runner


ROOT = Path(__file__).resolve().parents[1]


def run_git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return proc.stdout.strip()


class IronPlanContractTests(unittest.TestCase):
    def test_repository_policy_bundle_verifies(self) -> None:
        self.assertEqual(guard.verify(ROOT), [])

    def test_ledger_seals_current_plan(self) -> None:
        records = guard.read_ledger(ROOT)
        latest = records[-1]
        self.assertEqual(latest["result_plan_sha256"], guard.file_sha256(ROOT / guard.PLAN_REL))
        self.assertEqual(latest["record_sha256"], guard.canonical_record_sha256(latest))
        # The sealed revision is a STATUS, not a constant: it advances with every
        # accepted amendment. Bind it to the plan header so this keeps asserting
        # "the ledger seals the current plan" instead of "the plan is revision 1".
        revision, version, _ = guard.parse_plan_header(
            (ROOT / guard.PLAN_REL).read_text(encoding="utf-8")
        )
        self.assertEqual(latest["result_revision"], revision)
        self.assertEqual(latest["version"], version)

    def test_canonical_hash_normalizes_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left"
            right = root / "right"
            left.write_bytes(b"alpha\r\nbeta\r\n")
            right.write_bytes(b"alpha\nbeta\n")
            self.assertEqual(guard.file_sha256(left), guard.file_sha256(right))

    def test_apply_patch_finds_protected_master_plan(self) -> None:
        tool_input = {
            "patch": (
                "*** Begin Patch\n"
                "*** Update File: docs/IKARUS_ARIADNE_MASTER_PLAN.md\n"
                "@@\n-old\n+new\n"
                "*** End Patch\n"
            )
        }
        self.assertEqual(
            guard.protected_targets("apply_patch", tool_input, ROOT),
            [guard.PLAN_REL],
        )

    def test_read_only_shell_mention_is_not_blocked(self) -> None:
        tool_input = {"command": f"git diff -- {guard.PLAN_REL}"}
        self.assertFalse(guard.is_mutating_tool("Bash", tool_input))
        self.assertEqual(guard.protected_targets("Bash", tool_input, ROOT), [])

    def test_mutating_shell_command_is_blocked(self) -> None:
        tool_input = {
            "command": (
                "Set-Content -LiteralPath "
                f"'{guard.PLAN_REL}' -Value 'replacement'"
            )
        }
        self.assertTrue(guard.is_mutating_tool("Bash", tool_input))
        self.assertEqual(
            guard.protected_targets("Bash", tool_input, ROOT),
            [guard.PLAN_REL],
        )

    def test_directory_wide_delete_cannot_erase_protected_plan(self) -> None:
        tool_input = {"command": "Remove-Item -Recurse -Force docs"}
        targets = guard.protected_targets("Bash", tool_input, ROOT)
        self.assertIn("<directory: docs>", targets)

    def test_traversal_path_normalizes_to_protected_target(self) -> None:
        self.assertEqual(
            guard.normalize_repo_path("docs/../AGENTS.md", ROOT),
            "AGENTS.md",
        )
        self.assertTrue(guard.is_protected_path("docs/../AGENTS.md", ROOT))

    def test_python_open_write_through_traversal_is_blocked(self) -> None:
        tool_input = {
            "command": (
                "python -c \"open('docs/../AGENTS.md', 'w').write('bypass')\""
            )
        }
        self.assertTrue(guard.is_mutating_tool("Bash", tool_input))
        self.assertIn(
            "AGENTS.md",
            guard.protected_targets("Bash", tool_input, ROOT),
        )

    def test_common_interpreter_and_platform_writes_are_blocked(self) -> None:
        commands = (
            "python -c \"open('AGENTS.md', mode='w').write('x')\"",
            "python -c \"Path('AGENTS.md').open('w').write('x')\"",
            "node -e \"fs.writeFileSync('AGENTS.md', 'x')\"",
            "powershell -Command \"[IO.File]::WriteAllText('AGENTS.md','x')\"",
        )
        for command in commands:
            with self.subTest(command=command):
                targets = guard.protected_targets(
                    "mcp__terminal__exec_command",
                    {"command": command},
                    ROOT,
                )
                self.assertIn("AGENTS.md", targets)

    def test_git_global_options_and_short_bypass_flags_are_blocked(self) -> None:
        commands = (
            "git commit -n -m bypass",
            "git -C . commit --no-verify -m bypass",
            "git -C . config core.hooksPath NUL",
            "git update-index --chmod=-x .githooks/pre-commit",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(
                    "<repository policy bundle>",
                    guard.protected_targets("Bash", {"command": command}, ROOT),
                )

    def test_mutating_globs_that_expand_over_policy_are_blocked(self) -> None:
        commands = (
            "rm docs/*.md",
            "rm docs/IKARUS*",
            "Remove-Item docs/*.md",
            "git restore docs/*.md",
            "git checkout HEAD -- docs/*.md",
            "git restore :/",
            "git checkout HEAD -- :(top)**",
            "rm *.md",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(
                    guard.protected_targets("Bash", {"command": command}, ROOT)
                )

    def test_opaque_interactive_process_boundaries_are_blocked(self) -> None:
        cases = (
            ("exec_command", {"cmd": "powershell", "tty": True}),
            ("Bash", {"command": "python -i"}),
            ("write_stdin", {"session_id": 42, "chars": "anything"}),
            ("mcp__terminal__feed_chars", {"chars": "anything"}),
        )
        for tool_name, tool_input in cases:
            with self.subTest(tool=tool_name):
                self.assertEqual(
                    guard.protected_targets(tool_name, tool_input, ROOT),
                    ["<opaque interactive process>"],
                )

    def test_generic_and_nested_tool_schemas_find_protected_paths(self) -> None:
        cases = (
            ("Delete", {"path": "AGENTS.md"}),
            ("mcp__filesystem__remove", {"path": "AGENTS.md"}),
            (
                "mcp__filesystem__write_text_file",
                {"uri": (ROOT / "AGENTS.md").as_uri(), "data": "x"},
            ),
            ("delete_files", {"paths": ["AGENTS.md"]}),
            (
                "apply_patch",
                {
                    "request": {
                        "patch": "*** Begin Patch\n*** Delete File: AGENTS.md\n"
                    }
                },
            ),
        )
        for tool_name, tool_input in cases:
            with self.subTest(tool=tool_name):
                self.assertIn(
                    "AGENTS.md",
                    guard.protected_targets(tool_name, tool_input, ROOT),
                )

    @unittest.skipUnless(os.name == "nt", "Windows alias semantics")
    def test_windows_aliases_resolve_to_the_same_protected_file(self) -> None:
        absolute = str(ROOT / "AGENTS.md")
        extended = "\\\\?\\" + absolute
        drive, tail = os.path.splitdrive(absolute)
        admin = (
            "\\\\localhost\\"
            + drive[0]
            + "$\\"
            + tail.lstrip("\\/")
        )
        for alias in (extended, admin):
            with self.subTest(alias=alias):
                self.assertTrue(guard.is_protected_path(alias, ROOT))
                self.assertIn(
                    "AGENTS.md",
                    guard.protected_targets(
                        "Write", {"file_path": alias, "content": "x"}, ROOT
                    ),
                )

    def test_evidence_state_directory_is_itself_protected(self) -> None:
        path = ".git/iron-plan-hook-state/debt.json"
        self.assertTrue(guard.is_protected_path(path, ROOT))
        self.assertTrue(
            guard.protected_targets(
                "Bash", {"command": f"Remove-Item {path}"}, ROOT
            )
        )

    def test_new_top_level_paths_are_governed_by_default(self) -> None:
        tool_input = {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: new_kernel/control.py\n"
                "+effect = True\n"
                "*** End Patch\n"
            )
        }
        self.assertEqual(
            guard.governed_targets("apply_patch", tool_input, ROOT),
            ["new_kernel/control.py"],
        )

    def test_architectural_semantics_are_not_falsely_claimed_as_blocked(self) -> None:
        tool_input = {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: daedalus/parallel_event_store.py\n"
                "+class ParallelEventStore: ...\n"
                "*** End Patch\n"
            )
        }
        self.assertEqual(guard.protected_targets("apply_patch", tool_input, ROOT), [])
        self.assertEqual(
            guard.governed_targets("apply_patch", tool_input, ROOT),
            ["daedalus/parallel_event_store.py"],
        )

    def test_legacy_always_value_cannot_call_runtime_promotion(self) -> None:
        from daedalus.kairos import gated_writes

        assignment = SimpleNamespace(
            accepted=True,
            mode="write",
            worker="worker",
            lane="ollama",
            owner="owner",
            objective="change",
            paths=["src/example.py"],
        )
        artifact = SimpleNamespace(
            diff_sha256="a" * 64,
            byte_length=1,
            changed_paths=("src/example.py",),
        )
        result = SimpleNamespace(
            ok=True,
            artifact=artifact,
            artifact_path="archive.patch",
            persist_error=None,
            runner_detail=None,
            state="clean",
            task_id="task-1",
            branch="candidate/task-1",
            error=None,
        )
        candidate = gated_writes.GatedCandidate(
            assignment=assignment,
            spec=SimpleNamespace(),
            result=result,
        )
        scheduler = SimpleNamespace(
            project=None,
            availability={},
            max_parallel_writes=1,
            max_workers=1,
            policy=None,
            dispatch=mock.Mock(return_value=[]),
        )
        with (
            mock.patch.object(
                gated_writes, "gate_candidates", return_value=[candidate]
            ),
            mock.patch.object(
                gated_writes,
                "_governance_verdict",
                return_value=(True, "ready", "fresh receipt"),
            ),
            mock.patch.object(gated_writes, "promote_candidates") as promote,
        ):
            report = gated_writes.run_write_wave(
                scheduler,
                str(ROOT),
                [{"objective": "change"}],
                [assignment],
                auto_promote="always",
            )
        promote.assert_not_called()
        self.assertEqual(report[0]["status"], "gated_held")
        self.assertEqual(report[0]["auto_promote"], "never")
        self.assertEqual(report[0]["requested_auto_promote"], "always")

    def test_repository_wide_reset_is_treated_as_protected(self) -> None:
        tool_input = {"command": "git reset --hard HEAD"}
        targets = guard.protected_targets("Bash", tool_input, ROOT)
        self.assertIn("<repository policy bundle>", targets)

    def test_checkout_ref_over_whole_tree_is_treated_as_protected(self) -> None:
        tool_input = {"command": "git checkout otherbranch -- ."}
        self.assertIn(
            "<repository policy bundle>",
            guard.protected_targets("Bash", tool_input, ROOT),
        )

    def test_reading_hook_config_is_not_misclassified_as_mutation(self) -> None:
        tool_input = {"command": "git config --local --get core.hooksPath"}
        self.assertFalse(guard.is_mutating_tool("Bash", tool_input))

    def test_disabling_hook_config_is_treated_as_protected(self) -> None:
        tool_input = {"command": "git config --local core.hooksPath ''"}
        self.assertTrue(guard.is_mutating_tool("Bash", tool_input))
        self.assertIn(
            "<repository policy bundle>",
            guard.protected_targets("Bash", tool_input, ROOT),
        )

    def test_exact_local_hook_activation_is_bootstrap_safe(self) -> None:
        tool_input = {
            "command": "git config --local core.hooksPath .githooks"
        }
        self.assertTrue(guard.is_mutating_tool("Bash", tool_input))
        self.assertEqual(guard.protected_targets("Bash", tool_input, ROOT), [])

    def test_hook_activation_can_repair_its_own_single_verify_error(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "bootstrap-test",
            "tool_name": "Bash",
            "tool_input": {
                "command": "git config --local core.hooksPath .githooks"
            },
        }
        stdout = io.StringIO()
        with (
            mock.patch.object(
                guard,
                "verify",
                return_value=["local core.hooksPath is not .githooks (run: fix)"],
            ),
            mock.patch.object(guard, "mark_session_write", return_value=True),
            mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(guard.sys, "stdout", stdout),
        ):
            self.assertEqual(guard.hook(ROOT), 0)
        decision = json.loads(stdout.getvalue())["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", decision)

    def test_no_verify_commit_is_treated_as_protected(self) -> None:
        tool_input = {"command": "git commit --no-verify -m bypass"}
        self.assertIn(
            "<repository policy bundle>",
            guard.protected_targets("Bash", tool_input, ROOT),
        )

    def test_pre_tool_hook_denies_protected_write_without_token(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(ROOT / guard.PLAN_REL), "content": "x"},
        }
        stdout = io.StringIO()
        with (
            mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(guard.sys, "stdout", stdout),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("DAEDALUS_IRON_PLAN_AMENDMENT", None)
            self.assertEqual(guard.hook(ROOT), 0)
        result = json.loads(stdout.getvalue())
        decision = result["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn(guard.PLAN_REL, decision["permissionDecisionReason"])

    def test_pre_tool_hook_accepts_current_digest_as_amendment_token(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(ROOT / guard.PLAN_REL), "content": "x"},
        }
        stdout = io.StringIO()
        with (
            mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(guard.sys, "stdout", stdout),
            mock.patch.object(guard, "mark_session_write", return_value=True),
            mock.patch.dict(
                os.environ,
                {
                    "DAEDALUS_IRON_PLAN_AMENDMENT": guard.file_sha256(
                        ROOT / guard.PLAN_REL
                    )
                },
                clear=False,
            ),
        ):
            self.assertEqual(guard.hook(ROOT), 0)
        result = json.loads(stdout.getvalue())
        self.assertNotIn("permissionDecision", result["hookSpecificOutput"])

    def test_stop_requires_alignment_handoff_after_governed_write(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "contract-test",
            "last_assistant_message": "Done.",
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            with (
                mock.patch.object(guard, "_state_path", return_value=state),
                mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
                mock.patch.object(guard.sys, "stdout", stdout),
            ):
                self.assertEqual(guard.hook(ROOT), 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["decision"], "block")
            self.assertIn("Iron Plan:", result["reason"])

    def test_stop_clears_state_after_complete_handoff(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "contract-test",
            "last_assistant_message": (
                "Iron Plan: ALIGNED\nIron Gate: 0\nEvidence: focused tests"
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            with (
                mock.patch.object(guard, "_state_path", return_value=state),
                mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
                mock.patch.object(guard.sys, "stdout", stdout),
            ):
                self.assertEqual(guard.hook(ROOT), 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertFalse(state.exists())

    def test_stop_rejects_labels_that_only_contain_required_substrings(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "contract-test",
            "last_assistant_message": (
                "Iron Plan: WHATEVER\nIron Gate: 5\nEvidence: tests pass"
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            with (
                mock.patch.object(guard, "_state_path", return_value=state),
                mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
                mock.patch.object(guard.sys, "stdout", stdout),
            ):
                self.assertEqual(guard.hook(ROOT), 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["decision"], "block")
            self.assertIn("ALIGNED|EXPERIMENT|AMENDMENT", result["reason"])
            self.assertIn("Iron Gate: 0", result["reason"])
            self.assertIn("specific inspected behavior", result["reason"])
            self.assertTrue(state.exists())

    def test_stop_rejects_vacuous_evidence(self) -> None:
        self.assertIn(
            "Evidence: <specific inspected behavior/artifact>",
            guard.handoff_errors(
                "Iron Plan: ALIGNED\nIron Gate: 0\nEvidence: banana",
                "Gate 0 — Canonical Kernel",
            ),
        )

    def test_second_stop_does_not_create_a_cross_turn_loop(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "contract-test",
            "stop_hook_active": True,
            "last_assistant_message": "Still incomplete.",
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            with (
                mock.patch.object(guard, "_state_path", return_value=state),
                mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
                mock.patch.object(guard.sys, "stdout", stdout),
            ):
                self.assertEqual(guard.hook(ROOT), 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertTrue(
                state.exists(),
                "the recursion escape must not erase unresolved evidence debt",
            )

    def test_corrective_second_stop_clears_resolved_evidence_debt(self) -> None:
        payload = {
            "hook_event_name": "Stop",
            "session_id": "contract-test",
            "stop_hook_active": True,
            "last_assistant_message": (
                "Iron Plan: ALIGNED\n"
                "Iron Gate: 0\n"
                "Evidence: inspected traversal denial and hook crash behavior"
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            with (
                mock.patch.object(guard, "_state_path", return_value=state),
                mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
                mock.patch.object(guard.sys, "stdout", stdout),
            ):
                self.assertEqual(guard.hook(ROOT), 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertFalse(state.exists())

    def test_owner_token_can_repair_a_broken_protected_projection(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(ROOT / "CLAUDE.md"), "content": "repair"},
        }
        stdout = io.StringIO()
        with (
            mock.patch.object(guard, "verify", return_value=["projection broken"]),
            mock.patch.object(guard, "amendment_unlocked", return_value=True),
            mock.patch.object(guard, "mark_session_write", return_value=True),
            mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(guard.sys, "stdout", stdout),
        ):
            self.assertEqual(guard.hook(ROOT), 0)
        result = json.loads(stdout.getvalue())
        self.assertNotIn("permissionDecision", result["hookSpecificOutput"])

    def test_governed_effect_fails_closed_when_debt_cannot_persist(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "sessionId": "camel-case-session",
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(ROOT / "new_kernel/control.py"),
                "content": "x",
            },
        }
        stdout = io.StringIO()
        with (
            mock.patch.object(guard, "verify", return_value=[]),
            mock.patch.object(guard, "mark_session_write", return_value=False),
            mock.patch.object(guard.sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(guard.sys, "stdout", stdout),
        ):
            self.assertEqual(guard.hook(ROOT), 0)
        decision = json.loads(stdout.getvalue())["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("durably record", decision["permissionDecisionReason"])

    def test_camel_case_session_id_has_a_stable_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                guard, "_git_path", return_value=Path(directory)
            ):
                path = guard._state_path(ROOT, {"sessionId": "abc"})
        self.assertIsNotNone(path)

    def test_governed_commit_requires_plan_trailers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            message = Path(directory) / "COMMIT_EDITMSG"
            message.write_text("Implement a kernel change\n", encoding="utf-8")
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    guard, "staged_paths", return_value=["daedalus/kernel.py"]
                ),
                mock.patch.object(guard.sys, "stderr", stderr),
            ):
                self.assertEqual(guard.commit_msg(str(message), ROOT), 1)
            self.assertIn("Iron-Plan:", stderr.getvalue())

    def test_governed_commit_accepts_complete_plan_trailers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            message = Path(directory) / "COMMIT_EDITMSG"
            message.write_text(
                "Implement a kernel change\n\n"
                "Iron-Plan: aligned\n"
                "Iron-Gate: 0\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                guard, "staged_paths", return_value=["daedalus/kernel.py"]
            ):
                self.assertEqual(guard.commit_msg(str(message), ROOT), 0)

    def test_governed_commit_rejects_wrong_active_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            message = Path(directory) / "COMMIT_EDITMSG"
            message.write_text(
                "Implement a kernel change\n\n"
                "Iron-Plan: aligned\n"
                "Iron-Gate: 5\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    guard, "staged_paths", return_value=["daedalus/kernel.py"]
                ),
                mock.patch.object(guard.sys, "stderr", io.StringIO()),
            ):
                self.assertEqual(guard.commit_msg(str(message), ROOT), 1)

    def test_protected_commit_must_be_amendment_or_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            message = Path(directory) / "COMMIT_EDITMSG"
            message.write_text(
                "Change policy\n\nIron-Plan: aligned\nIron-Gate: 0\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    guard, "staged_paths", return_value=[guard.PLAN_REL]
                ),
                mock.patch.object(guard.sys, "stderr", io.StringIO()),
            ):
                self.assertEqual(guard.commit_msg(str(message), ROOT), 1)

    def test_governed_commit_cannot_precede_initial_policy_adoption(self) -> None:
        clean = subprocess.CompletedProcess([], 0, "", "")
        stderr = io.StringIO()
        with (
            mock.patch.object(guard, "verify", return_value=[]),
            mock.patch.object(
                guard, "staged_paths", return_value=["daedalus/kernel.py"]
            ),
            mock.patch.object(guard, "git_run", return_value=clean),
            mock.patch.object(guard, "_head_ledger", return_value=[]),
            mock.patch.object(
                guard,
                "_head_plan_digest",
                return_value=guard.read_ledger(ROOT)[0]["base_plan_sha256"],
            ),
            mock.patch.object(guard.sys, "stderr", stderr),
        ):
            self.assertEqual(guard.pre_commit(ROOT), 1)
        self.assertIn("initial adoption", stderr.getvalue())

    def test_ci_history_check_accepts_adoption_and_rejects_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_git(repo, "init")
            run_git(repo, "config", "user.name", "Iron Plan Test")
            run_git(repo, "config", "user.email", "iron-plan@example.invalid")

            old_plan = run_git(ROOT, "show", f"HEAD:{guard.PLAN_REL}") + "\n"
            base_plan = repo / guard.PLAN_REL
            base_plan.parent.mkdir(parents=True, exist_ok=True)
            base_plan.write_text(old_plan, encoding="utf-8")
            run_git(repo, "add", guard.PLAN_REL)
            run_git(repo, "commit", "-m", "base")
            base_sha = run_git(repo, "rev-parse", "HEAD")

            for rel in guard.PROTECTED_PATHS:
                source = ROOT / rel
                destination = repo / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            run_git(repo, "add", "-A")
            run_git(
                repo,
                "add",
                "--chmod=+x",
                ".githooks/pre-commit",
                ".githooks/commit-msg",
            )
            run_git(repo, "commit", "-m", "adopt policy")
            with mock.patch.dict(os.environ, {"CI": "1"}, clear=False):
                self.assertEqual(guard.verify_base(base_sha, repo), [])

            adoption_sha = run_git(repo, "rev-parse", "HEAD")
            ledger_path = repo / guard.LEDGER_REL
            record = json.loads(ledger_path.read_text(encoding="utf-8"))
            record["summary"] = "rewritten history"
            record["record_sha256"] = guard.canonical_record_sha256(record)
            ledger_path.write_text(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            run_git(repo, "add", guard.LEDGER_REL)
            run_git(repo, "commit", "-m", "rewrite accepted history")
            with mock.patch.dict(os.environ, {"CI": "1"}, clear=False):
                errors = guard.verify_base(adoption_sha, repo)
            self.assertTrue(
                any("rewritten or reordered" in error for error in errors),
                errors,
            )

    def test_staged_rename_exposes_both_source_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_git(repo, "init")
            run_git(repo, "config", "user.name", "Iron Plan Test")
            run_git(repo, "config", "user.email", "iron-plan@example.invalid")
            (repo / "AGENTS.md").write_text("policy\n", encoding="utf-8")
            run_git(repo, "add", "AGENTS.md")
            run_git(repo, "commit", "-m", "base")
            run_git(repo, "mv", "AGENTS.md", "renamed.md")
            staged = guard.staged_paths(repo)
            self.assertIn("AGENTS.md", staged)
            self.assertIn("renamed.md", staged)

    def test_codex_local_hook_disable_is_detected(self) -> None:
        self.assertTrue(
            guard._codex_hooks_disabled(
                "[features]\nhooks = false\nunrelated = true\n"
            )
        )
        self.assertFalse(
            guard._codex_hooks_disabled(
                "[other]\nhooks = false\n[features]\nhooks = true\n"
            )
        )

    def test_fail_closed_runner_maps_guard_crash_to_exit_two(self) -> None:
        fake_stdin = SimpleNamespace(
            buffer=io.BytesIO(b'{"hook_event_name":"PreToolUse"}')
        )
        failed = subprocess.CompletedProcess([], 1, b"", b"guard crashed")
        with (
            mock.patch.object(runner.sys, "stdin", fake_stdin),
            mock.patch.object(runner.sys, "stderr", io.StringIO()),
            mock.patch.object(runner.subprocess, "run", return_value=failed),
        ):
            self.assertEqual(runner.main(), 2)

    def test_fail_closed_runner_rejects_invalid_guard_output(self) -> None:
        fake_stdin = SimpleNamespace(
            buffer=io.BytesIO(b'{"hook_event_name":"PreToolUse"}')
        )
        invalid = subprocess.CompletedProcess([], 0, b"not-json", b"")
        with (
            mock.patch.object(runner.sys, "stdin", fake_stdin),
            mock.patch.object(runner.sys, "stderr", io.StringIO()),
            mock.patch.object(runner.subprocess, "run", return_value=invalid),
        ):
            self.assertEqual(runner.main(), 2)

    def test_fail_closed_runner_rejects_schema_free_valid_json(self) -> None:
        fake_stdin = SimpleNamespace(
            buffer=io.BytesIO(b'{"hook_event_name":"PreToolUse"}')
        )
        invalid = subprocess.CompletedProcess([], 0, b'{"anything":"goes"}', b"")
        with (
            mock.patch.object(runner.sys, "stdin", fake_stdin),
            mock.patch.object(runner.sys, "stderr", io.StringIO()),
            mock.patch.object(runner.subprocess, "run", return_value=invalid),
        ):
            self.assertEqual(runner.main(), 2)


if __name__ == "__main__":
    unittest.main()
