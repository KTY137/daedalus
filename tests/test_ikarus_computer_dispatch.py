"""G1-IKARUS-46: an act-shaped chat turn reaches the computer loop.

The chain under test, with the vendor voice and the control root pinned out:

    "verbessere Daedalus"  -> classify: enqueue, may_act: allowed
                           -> _enqueue: computer_task offer (loop available)
    "ja"                   -> may_act: confirmation of that objective
                           -> _ask_inner / _ask_stream_inner: /computer run <objective>
                           -> conversation_events (the same door /computer takes)

No network, no spawn, no control root: `_computer_hand` is patched to a
fixture capability and `conversation_events` to a recorder. The queue path
is asserted unchanged when the loop is unavailable.

Which production change turns these red:

* `_enqueue` proposing the loop while `_computer_hand` says None;
* the offer's `args.message` drifting from `run_command(objective)`;
* the offer losing its `act_offer` (a typed "ja" would stop confirming);
* `_confirmed_computer_run` running on an UNCONFIRMED imperative;
* `_ask_stream_inner` classifying twice or queueing behind a click;
* `/computer run <x>` being parsed as a subcommand;
* `/computer enable daedalus` widening without the current policy digest.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from daedalus.kernel.policy.computer import DAEDALUS_TOOLS
from daedalus.orchestration.ikarus import computer_loop as loop
from daedalus.orchestration.ikarus import shell as ikarus_os
from daedalus.orchestration.ikarus.act import may_act

# The same two voice pins as tests/test_ikarus_shells.py: a message that falls
# through to the Voice must never spawn a vendor from a routing test
# (MEASURED 2026-09-10: the first draft of this module did, once).
_PINS = (
    mock.patch.dict(os.environ, {"DAEDALUS_IKARUS_PROVIDER": "claude"}),
    mock.patch.object(ikarus_os, "_llm", return_value=("pinned voice", "pinned-model", ikarus_os._EMPTY_CTX)),
)


def setUpModule():
    for pin in _PINS:
        pin.start()


def tearDownModule():
    for pin in reversed(_PINS):
        pin.stop()


PROJECT = "sunny_garden"
OBJ = "verbessere den Parser"
HAND = {"planner": {"provider": "claude_code_cli", "model": "sonnet", "remote_context": True},
        "tools": ["daedalus.status", "daedalus.slice", "file.read"],
        "workspace": "W", "policy_sha256": "e" * 64, "max_steps": 16, "timeout_s": 300}


def _offer_turn(objective, *, signal="computer_task", policy_sha256=HAND["policy_sha256"]):
    """The previous turn as `_computer_offer` (default) or `_act_offer` (a question) left it."""
    offer = {"objective": objective, "reason": "computer task offered", "signal": signal}
    if policy_sha256 is not None:
        offer["policy_sha256"] = policy_sha256
    return {"envelope": {"act_offer": offer}}


class RunCommandTest(unittest.TestCase):
    def test_run_command_is_the_verbatim_objective_behind_the_run_verb(self):
        self.assertEqual(loop.run_command("  status   prüfen "), "/computer run status prüfen")

    def test_an_empty_objective_is_refused(self):
        with self.assertRaises(loop.ComputerLoopRefused):
            loop.run_command("   ")

    def test_run_executes_the_objective_even_when_it_names_a_subcommand(self):
        seen = []

        def run_objective(project, root, objective, cancelled):
            seen.append((project, objective))
            yield "final", {"intent": "computer", "assistant": "ran"}
        with mock.patch.object(loop, "_run_objective", run_objective):
            events = list(loop.conversation_events(PROJECT, "/computer run status"))
        self.assertEqual(seen, [(PROJECT, "status")])
        self.assertEqual(events[-1][1]["assistant"], "ran")

    def test_run_without_an_objective_is_blocked_before_any_service(self):
        with mock.patch.object(loop, "_run_objective", side_effect=AssertionError("no service")):
            events = list(loop.conversation_events(PROJECT, "/computer run"))
        self.assertEqual(events[-1][1]["intent"], "error")
        self.assertIn("/computer run <objective>", events[-1][1]["assistant"])

    def test_the_objective_run_binds_the_project_to_the_service(self):
        built = []

        class Service:
            def __init__(self, root, workspace=None, *, project=None, project_readers=None):
                built.append(project)

            def close(self):
                pass

        def events(root, objective, *, service, cancelled):
            yield "final", {"ok": True, "state": "completed", "summary": "s", "steps": []}
        from daedalus.runtimes import computer
        with mock.patch.object(computer, "ComputerService", Service), \
                mock.patch.object(loop, "computer_events", events):
            final = list(loop.conversation_events(PROJECT, "/computer run lies den Status"))[-1][1]
        self.assertEqual(built, [PROJECT])
        self.assertEqual(final["intent"], "computer")


class EnableDaedalusTest(unittest.TestCase):
    def _status(self, tools, *, provider="ollama_http", remote=False):
        import tempfile
        return {"enabled": True, "policy_sha256": "a" * 64, "tools": [{"name": t} for t in tools],
                "configuration": {"schema": "daedalus-computer-policy/1",
                                  "workspace": tempfile.gettempdir(),  # absolute: the loop derives the lane from it
                                  "tools": list(tools), "origins": [], "applications": {},
                                  "planner_provider": provider, "planner_model": None,
                                  "allow_remote_context": remote, "max_steps": 16, "timeout_s": 300,
                                  "max_file_bytes": 1048576}}

    def _enable(self, *, provider, remote, message="/computer enable daedalus confirm-remote"):
        from daedalus.interfaces import computer_configuration
        from daedalus.runtimes import computer
        status = lambda root, project=None, project_readers=None: self._status(  # noqa: E731
            ["file.read"], provider=provider, remote=remote)
        with mock.patch.object(computer, "computer_status", status), \
                mock.patch.object(computer_configuration, "configure_computer",
                                  lambda root, policy, *, owner_confirmed, expected_policy_sha256: {"ok": True, "policy_sha256": "b" * 64}):
            return list(loop.conversation_events(PROJECT, message))[-1][1]

    def test_the_grant_sentence_is_true_per_lane(self):
        """Cerberus round 2 (N1/N6): the deny list applies only on the untrusted
        lane; observations leave only with a remote, non-local planner."""
        with mock.patch.dict(os.environ, {"OLLAMA_HOST": "http://127.0.0.1:11434"}):
            claude = self._enable(provider="claude_code_cli", remote=True)["assistant"]
            codex = self._enable(provider="codex_cli", remote=True)["assistant"]
            local_flagged = self._enable(provider="ollama_http", remote=True)["assistant"]
            local = self._enable(provider="ollama_http", remote=False, message="/computer enable daedalus")["assistant"]
        self.assertIn("verlassen damit den Rechner", claude)
        self.assertIn("gelten hier NICHT", claude)
        self.assertNotIn("Deny-Liste, deny_content) und", claude)
        self.assertIn("verlassen damit den Rechner", codex)
        self.assertIn("Egress-Policy des Projekts (Deny-Liste, deny_content)", codex)
        self.assertIn("nichts verlässt ihn", local_flagged)
        self.assertIn("nichts verlässt ihn", local)
        self.assertIn("gelten hier NICHT", local)
        warning = self._enable(provider="claude_code_cli", remote=True, message="/computer enable daedalus")["assistant"]
        self.assertIn("gelten hier NICHT", warning)
        self.assertIn("confirm-remote", warning)

    def test_a_networked_ollama_is_egress_and_needs_the_confirmation(self):
        """Cerberus round 3 (C1): decided by HOST, not by provider name. An
        Ollama on a tailnet address with the remote flag set is untrusted, its
        observations leave, the grant must say so and must ask first."""
        from daedalus.interfaces import computer_configuration
        from daedalus.runtimes import computer
        status = lambda root, project=None, project_readers=None: self._status(  # noqa: E731
            ["file.read"], provider="ollama_http", remote=True)
        with mock.patch.dict(os.environ, {"OLLAMA_HOST": "http://100.119.126.9:11434"}), \
                mock.patch.object(computer, "computer_status", status), \
                mock.patch.object(computer_configuration, "configure_computer",
                                  side_effect=AssertionError("must not configure without the confirmation")):
            final = list(loop.conversation_events(PROJECT, "/computer enable daedalus"))[-1][1]
        self.assertEqual(final["computer"]["daedalus_tools_change"], "confirmation_required")
        self.assertIn("Egress-Policy des Projekts (Deny-Liste, deny_content)", final["assistant"])
        with mock.patch.dict(os.environ, {"OLLAMA_HOST": "http://100.119.126.9:11434"}):
            granted = self._enable(provider="ollama_http", remote=True)["assistant"]
        self.assertIn("verlassen damit den Rechner", granted)
        self.assertNotIn("nichts verlässt ihn", granted)
        self.assertNotIn("gelten hier NICHT", granted)

    def test_enable_adds_the_family_through_compare_and_replace(self):
        from daedalus.interfaces import computer_configuration
        from daedalus.runtimes import computer
        calls = []

        def configure(root, policy, *, owner_confirmed, expected_policy_sha256):
            calls.append((policy["tools"], owner_confirmed, expected_policy_sha256))
            return {"ok": True, "policy_sha256": "b" * 64}
        with mock.patch.object(computer, "computer_status", lambda root, project=None, project_readers=None: self._status(["file.read"])), \
                mock.patch.object(computer_configuration, "configure_computer", configure):
            final = list(loop.conversation_events(PROJECT, "/computer enable daedalus"))[-1][1]
        self.assertEqual(calls, [(["file.read", *DAEDALUS_TOOLS], True, "a" * 64)])
        self.assertTrue(final["computer"]["daedalus_tools"])
        # Cerberus 2026-09-10 (CRITICAL 2): the grant sentence says what the
        # observations are and where they go; with a local planner nothing leaves.
        self.assertIn("Planner `ollama_http`", final["assistant"])
        self.assertIn("nichts verlässt ihn", final["assistant"])
        self.assertNotIn("cannot write, launch or send", final["assistant"])

    def test_enable_with_a_remote_planner_needs_a_transient_confirmation(self):
        from daedalus.interfaces import computer_configuration
        from daedalus.runtimes import computer
        status = lambda root, project=None, project_readers=None: self._status(  # noqa: E731
            ["file.read"], provider="codex_cli", remote=True)
        with mock.patch.object(computer, "computer_status", status), \
                mock.patch.object(computer_configuration, "configure_computer",
                                  side_effect=AssertionError("must not configure without the confirmation")):
            final = list(loop.conversation_events(PROJECT, "/computer enable daedalus"))[-1][1]
        self.assertEqual(final["computer"]["daedalus_tools_change"], "confirmation_required")
        self.assertIn("`codex_cli`", final["assistant"])
        self.assertIn("Git-Status-Pfade", final["assistant"])
        self.assertIn("/computer enable daedalus confirm-remote", final["assistant"])
        self.assertIn("Nichts wurde geändert", final["assistant"])
        calls = []

        def configure(root, policy, *, owner_confirmed, expected_policy_sha256):
            calls.append(policy["tools"])
            return {"ok": True, "policy_sha256": "b" * 64}
        with mock.patch.object(computer, "computer_status", status), \
                mock.patch.object(computer_configuration, "configure_computer", configure):
            final = list(loop.conversation_events(PROJECT, "/computer enable daedalus confirm-remote"))[-1][1]
        self.assertEqual(calls, [["file.read", *DAEDALUS_TOOLS]])
        self.assertEqual(final["computer"]["daedalus_tools_change"], "applied")
        self.assertIn("verlassen damit den Rechner", final["assistant"])

    def test_the_remote_planner_warning_names_the_daedalus_observations(self):
        text = loop._remote_planner_warning("codex_cli", None)
        self.assertIn("Git-Status-Pfade", text)
        self.assertIn("Codescheiben", text)

    def test_disable_removes_only_the_family(self):
        from daedalus.interfaces import computer_configuration
        from daedalus.runtimes import computer
        calls = []

        def configure(root, policy, *, owner_confirmed, expected_policy_sha256):
            calls.append(policy["tools"])
            return {"ok": True, "policy_sha256": "b" * 64}
        with mock.patch.object(computer, "computer_status",
                               lambda root, project=None, project_readers=None: self._status(["file.read", *DAEDALUS_TOOLS])), \
                mock.patch.object(computer_configuration, "configure_computer", configure):
            final = list(loop.conversation_events(PROJECT, "/computer disable daedalus"))[-1][1]
        self.assertEqual(calls, [["file.read"]])
        self.assertFalse(final["computer"]["daedalus_tools"])

    def test_any_other_argument_or_a_missing_policy_is_refused(self):
        from daedalus.interfaces import computer_configuration
        from daedalus.runtimes import computer
        with mock.patch.object(computer_configuration, "configure_computer",
                               side_effect=AssertionError("must not configure")):
            for message in ("/computer enable everything", "/computer enable daedalus extra",
                            "/computer enable", "/computer disable daedalus confirm-remote extra"):
                with self.subTest(message=message):
                    final = list(loop.conversation_events(PROJECT, message))[-1][1]
                    self.assertEqual(final["intent"], "error", final["assistant"])
            with mock.patch.object(computer, "computer_status", lambda root, project=None, project_readers=None: {"enabled": False, "tools": []}):
                final = list(loop.conversation_events(PROJECT, "/computer enable daedalus"))[-1][1]
        self.assertEqual(final["intent"], "error")
        self.assertIn("/computer setup", final["assistant"])


class ComputerHandTest(unittest.TestCase):
    def test_unavailable_or_failing_status_is_none(self):
        from daedalus.runtimes import computer
        with mock.patch.object(computer, "computer_status", lambda root, project=None, project_readers=None: {"enabled": False, "tools": []}):
            self.assertIsNone(ikarus_os._computer_hand(PROJECT))
        with mock.patch.object(computer, "computer_status", side_effect=RuntimeError("boom")):
            self.assertIsNone(ikarus_os._computer_hand(PROJECT))

    def test_an_enabled_policy_projects_planner_and_tools(self):
        from daedalus.runtimes import computer
        caps = {"enabled": True, "tools": [{"name": "daedalus.status"}, {"name": "file.read"}],
                "planner_provider": "codex_cli", "planner_model": None, "allow_remote_context": True,
                "workspace": "W", "policy_sha256": "e" * 64, "max_steps": 16, "timeout_s": 300}
        seen = []
        with mock.patch.object(computer, "computer_status",
                               lambda root, project=None, project_readers=None: seen.append(project) or caps):
            hand = ikarus_os._computer_hand(PROJECT)
        self.assertEqual(seen, [PROJECT])
        self.assertEqual(hand["tools"], ["daedalus.status", "file.read"])
        self.assertEqual(hand["planner"], {"provider": "codex_cli", "model": None, "remote_context": True})


class OfferTest(unittest.TestCase):
    def _offer(self, message=OBJ, hand=HAND):
        with mock.patch.object(ikarus_os, "_computer_hand", return_value=hand), \
                mock.patch.object(ikarus_os, "_hand_state", side_effect=AssertionError("no liveness probe")):
            return ikarus_os.ask(PROJECT, message, provider=None)

    def test_an_act_request_is_offered_as_a_computer_task(self):
        res = self._offer()
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["shell"], ikarus_os.SHELL_HAND)
        action = res["action"]
        self.assertEqual(action["kind"], "computer_task")
        self.assertTrue(action["requires_confirmation"])
        self.assertEqual(action["args"]["message"], loop.run_command(OBJ))
        self.assertEqual(action["args"]["objective"], OBJ)
        self.assertEqual(action["args"]["lane"], "computer")
        self.assertEqual(action["args"]["tools"], HAND["tools"])
        self.assertEqual(res["act_offer"]["objective"], OBJ)
        self.assertEqual(res["provider_used"], "deterministic")

    def test_the_german_offer_names_planner_tools_and_egress(self):
        res = self._offer()
        self.assertIn("Computer-Auftrag", res["assistant"])
        self.assertIn("claude_code_cli (sonnet)", res["assistant"])
        self.assertIn("verlassen den Rechner", res["assistant"])
        self.assertIn("`daedalus.status`", res["assistant"])
        self.assertIn("kein Beweis", res["assistant"])

    def test_the_english_offer_reads_in_english(self):
        res = self._offer("improve the parser")
        self.assertIn("computer task", res["assistant"])
        self.assertIn("not proof", res["assistant"])

    def test_without_a_loop_the_queue_offer_is_unchanged(self):
        with mock.patch.object(ikarus_os, "_computer_hand", return_value=None):
            res = ikarus_os.ask(PROJECT, "build a login page", provider=None)
        self.assertEqual(res["action"]["kind"], "queue_task")
        self.assertNotIn("act_offer", res)

    def test_new_german_verbs_reach_the_offer(self):
        for message in ("verbessere Daedalus", "erweitere den Parser", "korrigiere die Doku",
                        "entwickle ein CLI-Tool", "programmiere einen Parser"):
            with self.subTest(message=message):
                res = self._offer(message)
                self.assertEqual(res["action"]["kind"], "computer_task", res["assistant"])

    def test_a_question_still_gets_no_offer_of_a_run(self):
        res = self._offer("kannst du Daedalus verbessern?")
        self.assertNotIn("action", res)
        self.assertIn("act_offer", res)  # the suspected path's confirm offer, as before


class ConfirmationTest(unittest.TestCase):
    def _confirm(self, hand=HAND, message="ja", recorder=None, prior=None):
        recorder = recorder if recorder is not None else []
        prior = prior if prior is not None else _offer_turn(OBJ)

        def events(project, message, cancelled=None):
            recorder.append((project, message))
            yield "start", {"intent": "computer"}
            yield "final", {"intent": "computer", "shell": "hand", "assistant": "loop ran",
                            "provider_used": "computer-policy", "computer": {"ok": True}}
        with mock.patch.object(ikarus_os, "_computer_hand", return_value=hand), \
                mock.patch.object(ikarus_os, "_prior_turn", return_value=prior), \
                mock.patch.object(loop, "conversation_events", events):
            res = ikarus_os.ask(PROJECT, message, provider=None, conversation_id=None,
                                act=may_act(message, "chat", prior), intent="chat")
        return res, recorder

    def test_a_question_s_offer_confirms_into_a_proposal_never_a_run(self):
        """Odysseus 2026-09-10 (defect 4): `_act_offer` promises a confirm-gated
        task; its "ja" must yield the computer_task PROPOSAL with its own gate."""
        # Same policy digest as the loop on purpose: only the offer's SIGNAL
        # may keep this "ja" from running (a real question offer carries no
        # digest at all, which the digest check would also refuse).
        prior = _offer_turn("kannst du das mal bauen?", signal="German directed request")
        res, recorder = self._confirm(prior=prior)
        self.assertEqual(recorder, [])
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["action"]["kind"], "computer_task")
        self.assertEqual(res["act_offer"]["signal"], "computer_task")
        self.assertEqual(res["act_offer"]["policy_sha256"], HAND["policy_sha256"])

    def test_a_confirmation_against_a_changed_policy_re_offers_instead_of_running(self):
        """Odysseus 2026-09-10 (defect 5): the offer's policy digest is bound to the run."""
        prior = _offer_turn(OBJ, policy_sha256="f" * 64)
        res, recorder = self._confirm(prior=prior)
        self.assertEqual(recorder, [])
        self.assertEqual(res["action"]["kind"], "computer_task")
        self.assertIn("seit dem Angebot geändert", res["assistant"])
        self.assertEqual(res["act_offer"]["policy_sha256"], HAND["policy_sha256"])

    def test_the_question_offer_names_the_computer_loop_when_it_is_available(self):
        with mock.patch.object(ikarus_os, "_computer_hand", return_value=HAND):
            res = ikarus_os.ask(PROJECT, "kannst du das mal bauen?", provider=None)
        self.assertNotIn("action", res)
        self.assertIn("Computer-Auftrag im Daedalus-Loop", res["assistant"])
        with mock.patch.object(ikarus_os, "_computer_hand", return_value=None):
            res = ikarus_os.ask(PROJECT, "kannst du das mal bauen?", provider=None)
        self.assertIn("Projekt-Lane", res["assistant"])

    def test_a_typed_confirmation_runs_the_offered_objective(self):
        res, recorder = self._confirm()
        self.assertEqual(recorder, [(PROJECT, loop.run_command(OBJ))])
        self.assertEqual(res["intent"], "computer")
        self.assertEqual(res["assistant"], "loop ran")

    def test_a_decline_runs_nothing(self):
        res, recorder = self._confirm(message="nein")
        self.assertEqual(recorder, [])
        self.assertNotEqual(res.get("intent"), "computer")

    def test_a_confirmation_without_a_loop_falls_back_to_the_queue_offer(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=None):
            res, recorder = self._confirm(hand=None)
        self.assertEqual(recorder, [])
        self.assertEqual(res["intent"], "enqueue")

    def test_an_unconfirmed_imperative_never_runs_the_loop(self):
        recorder = []

        def events(project, message, cancelled=None):
            recorder.append(message)
            yield "final", {}
        with mock.patch.object(ikarus_os, "_computer_hand", return_value=HAND), \
                mock.patch.object(loop, "conversation_events", events):
            res = ikarus_os.ask(PROJECT, OBJ, provider=None)
        self.assertEqual(recorder, [])
        self.assertEqual(res["action"]["kind"], "computer_task")

    def test_the_streaming_confirmation_streams_the_loop_and_classifies_once(self):
        recorder = []

        def events(project, message, cancelled=None):
            recorder.append((project, message))
            yield "start", {"intent": "computer", "shell": "hand", "provider_used": "computer-policy"}
            yield "progress", {"phase": "planning"}
            yield "final", {"intent": "computer", "shell": "hand", "assistant": "streamed",
                            "provider_used": "computer-policy", "computer": {"ok": True}}
        classify = mock.Mock(return_value="chat")
        with mock.patch.object(ikarus_os, "_computer_hand", return_value=HAND), \
                mock.patch.object(ikarus_os, "_prior_turn", return_value=_offer_turn(OBJ)), \
                mock.patch.object(ikarus_os, "classify", classify), \
                mock.patch.object(loop, "conversation_events", events):
            frames = list(ikarus_os.ask_stream(PROJECT, "ja", provider=None))
        self.assertEqual(recorder, [(PROJECT, loop.run_command(OBJ))])
        self.assertEqual(classify.call_count, 1)
        self.assertEqual([event for event, _ in frames][:3], ["start", "progress", "final"])
        self.assertEqual(frames[-1][1]["assistant"], "streamed")


if __name__ == "__main__":
    unittest.main()
