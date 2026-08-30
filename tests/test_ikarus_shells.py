"""The three shells: deterministic / hand / voice.

Covers the five obligations that are properties of the ROUTER rather than of
the capability predicate (that one is tested in test_ikarus_act.py):

  * classify() runs exactly once per request, and start/final cannot disagree
  * the provider fence -- chat is the client's choice, action is the system's
  * the Hand's liveness is spoken in the five-word vocabulary and refused in
    words when absent
  * the German act request round-trips through may_act + the enqueue path

No network: every test that can reach a liveness check patches it.
"""
import unittest
from collections import namedtuple
from unittest import mock

from daedalus import health, ikarus_os
from daedalus.ikarus_act import ActDecision, may_act

_Hand = namedtuple("HandState", "state detail host")
_WORKING = _Hand("working", "answered", "http://127.0.0.1:11434")
_ABSENT = _Hand("absent", "ConnectionRefusedError: refused", "http://127.0.0.1:11434")
_UNKNOWN = _Hand("unknown", "TimeoutError: timed out", "http://127.0.0.1:11434")

PROJECT = "sunny_garden"


def _offer_turn(objective):
    return {"envelope": {"intent": "chat",
                         "act_offer": {"objective": objective,
                                       "reason": "r", "signal": "s"}}}


# --------------------------------------------------------------------------- #
# _route -- the one place the two answers are folded                           #
# --------------------------------------------------------------------------- #
class RouteTest(unittest.TestCase):
    ALLOWED = ActDecision(True, "ok", objective="build x")
    REFUSED = ActDecision(False, "no")
    SUSPECT = ActDecision(False, "no", suspected=True, objective="bauen")
    CONFIRM = ActDecision(True, "ok", objective="build x", confirmation_of="build x")

    def test_capability_pulls_a_message_off_the_tool_route(self):
        self.assertEqual(ikarus_os._route("enqueue", self.REFUSED), "chat")
        self.assertEqual(ikarus_os._route("enqueue", self.SUSPECT), "chat")

    def test_capability_leaves_a_cleared_message_on_it(self):
        self.assertEqual(ikarus_os._route("enqueue", self.ALLOWED), "enqueue")

    def test_a_confirmation_lands_on_the_enqueue_route_from_chat(self):
        self.assertEqual(ikarus_os._route("chat", self.CONFIRM), "enqueue")

    def test_deterministic_intents_are_untouched_by_the_capability_answer(self):
        for intent in ("status", "distill", "design"):
            for act in (self.ALLOWED, self.REFUSED, self.SUSPECT):
                with self.subTest(intent=intent, allowed=act.allowed):
                    self.assertEqual(ikarus_os._route(intent, act), intent)

    def test_every_route_has_a_shell(self):
        for route in ("status", "distill", "design", "enqueue", "chat", "error"):
            with self.subTest(route=route):
                self.assertIn(ikarus_os._shell_for(route),
                              (ikarus_os.SHELL_DETERMINISTIC, ikarus_os.SHELL_HAND,
                               ikarus_os.SHELL_VOICE))
        self.assertEqual(ikarus_os._shell_for("enqueue"), ikarus_os.SHELL_HAND)
        self.assertEqual(ikarus_os._shell_for("chat"), ikarus_os.SHELL_VOICE)


# --------------------------------------------------------------------------- #
# obligation 2 -- classify exactly ONCE, start and final cannot disagree       #
# --------------------------------------------------------------------------- #
class ClassifyOnceTest(unittest.TestCase):
    def _count(self, message, provider="deterministic"):
        calls = []
        real = ikarus_os.classify

        def counting(msg):
            calls.append(msg)
            return real(msg)

        with mock.patch.object(ikarus_os, "classify", counting), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            list(ikarus_os.ask_stream(PROJECT, message, provider=provider))
        return calls

    def test_streaming_classifies_once_on_the_deterministic_route(self):
        # MEASURED before this change: 2 (once here, once again inside ask()).
        self.assertEqual(len(self._count("build a login page")), 1)

    def test_streaming_classifies_once_on_the_chat_route(self):
        self.assertEqual(len(self._count("hello there")), 1)

    def test_streaming_classifies_once_on_a_suspected_act_request(self):
        self.assertEqual(len(self._count("kannst du das mal bauen")), 1)

    def test_blocking_ask_classifies_once(self):
        self.assertEqual(len(self._count_blocking("build a login page")), 1)

    def _count_blocking(self, message):
        calls = []
        real = ikarus_os.classify

        def counting(msg):
            calls.append(msg)
            return real(msg)

        with mock.patch.object(ikarus_os, "classify", counting), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            ikarus_os.ask(PROJECT, message, provider=None)
        return calls


class StartFinalAgreementTest(unittest.TestCase):
    def _events(self, message, provider="deterministic"):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            return list(ikarus_os.ask_stream(PROJECT, message, provider=provider))

    def test_start_and_final_agree_on_intent_and_shell(self):
        for msg in ("build a login page", "what's running?", "hello there",
                    "kannst du das mal bauen", "does that make sense", "   "):
            with self.subTest(msg=msg):
                events = self._events(msg)
                start = next(p for e, p in events if e == "start")
                final = next(p for e, p in events if e == "final")
                self.assertEqual(start["intent"], final["intent"], msg)
                self.assertEqual(start["shell"], final["shell"], msg)

    def test_reconcile_passes_an_agreeing_final_through_untouched(self):
        env = {"intent": "enqueue", "action": {"kind": "queue_task"}}
        out = ikarus_os._reconcile_final("enqueue", env)
        self.assertIs(out, env)
        self.assertIn("action", out)
        self.assertNotIn("intent_mismatch", out)

    def test_reconcile_lets_an_error_supersede_the_announcement(self):
        env = {"intent": "error", "assistant": "boom"}
        out = ikarus_os._reconcile_final("chat", env)
        self.assertEqual(out["intent"], "error")
        self.assertNotIn("intent_mismatch", out)

    def test_reconcile_drops_the_capability_when_they_disagree(self):
        # THE historic bug: a Confirm button rendered from a `final` whose
        # `start` said chat. The announcement stands and the action is dropped.
        env = {"intent": "enqueue", "action": {"kind": "queue_task"},
               "assistant": "..."}
        out = ikarus_os._reconcile_final("chat", env)
        self.assertEqual(out["intent"], "chat")
        self.assertEqual(out["shell"], ikarus_os.SHELL_VOICE)
        self.assertNotIn("action", out)
        self.assertEqual(out["intent_mismatch"],
                         {"start": "chat", "final": "enqueue", "dropped_action": True})

    def test_a_divergent_final_cannot_smuggle_an_action_through_the_stream(self):
        # Force the divergence the threading is supposed to make unreachable,
        # and prove the stream still cannot emit an unannounced action.
        divergent = {"ok": True, "intent": "enqueue", "shell": "hand",
                     "assistant": "queued!", "action": {"kind": "queue_task"}}
        with mock.patch.object(ikarus_os, "_chat", return_value=divergent), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            events = list(ikarus_os.ask_stream(
                PROJECT, "hello there", provider="deterministic"
            ))
        start = next(p for e, p in events if e == "start")
        final = next(p for e, p in events if e == "final")
        self.assertEqual(start["intent"], "chat")
        self.assertEqual(final["intent"], "chat")
        self.assertNotIn("action", final)
        self.assertTrue(final["intent_mismatch"]["dropped_action"])


# --------------------------------------------------------------------------- #
# obligation 3 -- the provider fence                                           #
# --------------------------------------------------------------------------- #
class ProviderFenceTest(unittest.TestCase):
    def test_the_hand_path_has_no_provider_argument_at_all(self):
        import inspect

        params = inspect.signature(ikarus_os._enqueue).parameters
        self.assertNotIn("provider", params)

    def test_naming_a_provider_cannot_put_it_on_the_tool_bearing_path(self):
        for provider in ("claude", "deepseek", "codex", "ollama", "gemini"):
            with self.subTest(provider=provider):
                with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
                    res = ikarus_os.ask(PROJECT, "build a login page", provider=provider)
                self.assertEqual(res["intent"], "enqueue")
                self.assertEqual(res["shell"], ikarus_os.SHELL_HAND)
                self.assertEqual(res["provider_used"], "deterministic")
                self.assertEqual(res["action"]["args"]["lane"], "local_only")
                self.assertTrue(res["action"]["requires_confirmation"])
                # the request's provider is nowhere in what was proposed
                self.assertNotIn(provider, str(res["action"]))

    def test_chat_still_honors_the_clients_choice_of_voice(self):
        with mock.patch.object(ikarus_os, "_llm",
                               return_value=("hi", "m1", ikarus_os._EMPTY_CTX)):
            res = ikarus_os.ask(PROJECT, "hello there", provider="claude")
        self.assertEqual(res["intent"], "chat")
        self.assertEqual(res["shell"], ikarus_os.SHELL_VOICE)
        self.assertEqual(res["provider_used"], "claude_code_cli")
        self.assertEqual(res["model_used"], "m1")

    def test_an_unwired_voice_fails_closed(self):
        res = ikarus_os.ask(PROJECT, "hello there", provider="gemini")
        self.assertEqual(res["provider_used"], "unavailable")
        self.assertEqual(res["intent"], "error")
        self.assertEqual(res["shell"], ikarus_os.SHELL_VOICE)


# --------------------------------------------------------------------------- #
# obligation 4 -- the Hand's liveness, in the five-word vocabulary             #
# --------------------------------------------------------------------------- #
class HandLivenessVocabularyTest(unittest.TestCase):
    """health.hand_state composes the ONE liveness predicate; no second one."""

    def test_working_absent_unknown(self):
        cases = [((True, "answered", ""), health.WORKING),
                 ((False, "URLError: refused", "ConnectionRefusedError"), health.ABSENT),
                 ((False, "URLError: timed out", "TimeoutError"), health.UNKNOWN)]
        for ret, expected in cases:
            with self.subTest(expected=expected):
                with mock.patch.object(health, "hand_admission",
                                       return_value=(True, "trusted", "test")), \
                     mock.patch.object(health, "_ollama_alive", return_value=ret):
                    self.assertEqual(health.hand_state("http://h:1").state, expected)

    def test_the_probe_speaks_the_same_five_words(self):
        spec = next(p for p in health.PROBES if p.name == "hand.executor")
        for ret, expected in [((True, "answered", ""), health.WORKING),
                              ((False, "d", "ConnectionRefusedError"), health.ABSENT),
                              ((False, "d", "TimeoutError"), health.UNKNOWN)]:
            with self.subTest(expected=expected):
                with mock.patch.object(health, "_ollama_alive", return_value=ret):
                    rep = spec.fn(health.Ctx())
                self.assertEqual(rep.state, expected)
                self.assertTrue(rep.facts, "a state must carry its evidence")

    def test_bench_alive_still_returns_a_two_tuple(self):
        with mock.patch.object(health, "_ollama_alive",
                               return_value=(True, "answered", "")):
            alive, detail = health._bench_ollama_alive(health.Ctx())
        self.assertTrue(alive)
        self.assertEqual(detail, "answered")

    def test_ikarus_never_reads_working_out_of_a_broken_check(self):
        ikarus_os._HAND_CACHE.clear()
        with mock.patch.object(health, "hand_state", side_effect=RuntimeError("nope")):
            st = ikarus_os._hand_state()
        ikarus_os._HAND_CACHE.clear()
        self.assertEqual(st.state, "unknown")

    def test_the_liveness_answer_is_cached_briefly(self):
        ikarus_os._HAND_CACHE.clear()
        with mock.patch.object(health, "hand_state", return_value=_WORKING) as hs:
            ikarus_os._hand_state()
            ikarus_os._hand_state()
        ikarus_os._HAND_CACHE.clear()
        self.assertEqual(hs.call_count, 1)


class HandRefusesInWordsTest(unittest.TestCase):
    OBJ = "kannst du das mal bauen"

    def _confirm(self, hand):
        with mock.patch.object(ikarus_os, "_prior_turn",
                               return_value=_offer_turn(self.OBJ)), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=hand):
            return ikarus_os.ask(PROJECT, "ja", provider=None, conversation_id=None,
                                 act=may_act("ja", "chat", _offer_turn(self.OBJ)),
                                 intent="chat")

    def test_a_confirmed_route_to_an_absent_hand_is_refused_in_words(self):
        res = self._confirm(_ABSENT)
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["shell"], ikarus_os.SHELL_HAND)
        self.assertNotIn("action", res, "nothing may be proposed at an absent Hand")
        self.assertIn("unreachable", res["assistant"])
        self.assertIn("ConnectionRefusedError", res["assistant"])
        self.assertEqual(res["hand"]["state"], "absent")

    def test_unknown_is_not_clearance_either(self):
        # MEASURED on Windows: a closed local port TIMES OUT rather than
        # refusing, so `absent` is nearly unreachable and a guard keyed only to
        # it would be a guard in name only. `unknown` still is not `absent` --
        # the wording differs -- but neither is clearance.
        res = self._confirm(_UNKNOWN)
        self.assertNotIn("action", res)
        self.assertIn("could not confirm", res["assistant"])
        self.assertEqual(res["hand"]["state"], "unknown")

    def test_a_confirmation_with_no_liveness_answer_at_all_is_refused(self):
        res = self._confirm(None)
        self.assertNotIn("action", res)
        self.assertEqual(res["hand"]["state"], "unknown")
        self.assertIn("could not confirm", res["assistant"])

    def test_a_confirmed_route_to_a_working_hand_is_queued(self):
        res = self._confirm(_WORKING)
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["action"]["args"]["objective"], self.OBJ)
        self.assertEqual(res["action"]["args"]["lane"], "local_only")
        self.assertEqual(res["hand"]["state"], "working")

    def test_an_unconfirmed_proposal_still_proposes_but_says_the_state(self):
        # Nothing is committed yet, so refusing to PROPOSE would be wrong --
        # but proposing into the void silently is what this forbids.
        for hand in (_ABSENT, _UNKNOWN):
            with self.subTest(state=hand.state):
                with mock.patch.object(ikarus_os, "_hand_state", return_value=hand):
                    res = ikarus_os.ask(PROJECT, "build a login page", provider=None)
                self.assertIn("action", res)
                self.assertEqual(res["hand"]["state"], hand.state)
                self.assertIn(hand.state, res["assistant"])

    def test_a_proposal_never_pays_for_a_liveness_probe(self):
        # MEASURED: a non-answering host costs the full 2s timeout on this
        # platform. A proposal commits nothing, so it looks at the cache and
        # does not knock -- and claims no state it did not measure.
        ikarus_os._HAND_CACHE.clear()
        with mock.patch.object(health, "hand_state") as probed:
            res = ikarus_os.ask(PROJECT, "build a login page", provider=None)
        probed.assert_not_called()
        self.assertIn("action", res)
        self.assertNotIn("hand", res, "no state may be reported without measuring")

    def test_but_a_confirmation_does_pay_for_one(self):
        ikarus_os._HAND_CACHE.clear()
        with mock.patch.object(ikarus_os, "_prior_turn",
                               return_value=_offer_turn(self.OBJ)),                 mock.patch.object(health, "hand_state",
                                  return_value=_WORKING) as probed:
            res = ikarus_os.ask(PROJECT, "ja", provider=None, conversation_id="c1")
        ikarus_os._HAND_CACHE.clear()
        probed.assert_called_once()
        self.assertIn("action", res)

    def test_a_fresh_cached_answer_is_reported_on_a_proposal(self):
        ikarus_os._HAND_CACHE.clear()
        with mock.patch.object(health, "hand_state", return_value=_UNKNOWN):
            ikarus_os._hand_state()            # warm it, as a confirmation would
        with mock.patch.object(health, "hand_state") as probed:
            res = ikarus_os.ask(PROJECT, "build a login page", provider=None)
        ikarus_os._HAND_CACHE.clear()
        probed.assert_not_called()
        self.assertEqual(res["hand"]["state"], "unknown")

    def test_a_working_hand_adds_no_noise_to_the_proposal(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, "build a login page", provider=None)
        self.assertIn("action", res)
        self.assertNotIn("local executor is", res["assistant"])

    def test_turn_status_never_records_a_phantom_proposal(self):
        from daedalus import conversation

        self.assertEqual(
            ikarus_os._turn_status({"intent": "enqueue", "action": {"k": 1}}),
            conversation.STATUS_PROPOSED)
        self.assertEqual(ikarus_os._turn_status({"intent": "enqueue"}),
                         conversation.STATUS_ANSWERED)
        self.assertEqual(ikarus_os._turn_status({"intent": "error"}),
                         conversation.STATUS_ERROR)


# --------------------------------------------------------------------------- #
# obligation 5 -- the German act request, explicitly                           #
# --------------------------------------------------------------------------- #
class GermanActRequestTest(unittest.TestCase):
    MSG = "kannst du das mal bauen"

    def test_classify_says_chat_because_there_is_no_english_keyword(self):
        self.assertEqual(ikarus_os.classify(self.MSG), "chat")

    def test_the_voice_reports_the_refusal_and_offers_the_route(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, self.MSG, provider=None)
        self.assertEqual(res["intent"], "chat")
        self.assertEqual(res["shell"], ikarus_os.SHELL_VOICE)
        self.assertEqual(res["provider_used"], "deterministic")
        self.assertNotIn("action", res, "the offer is not itself an action")
        self.assertIn("can't queue it from here", res["assistant"])
        self.assertEqual(res["act_offer"]["objective"], self.MSG)
        self.assertFalse(res["act"]["allowed"])
        self.assertTrue(res["act"]["suspected"])

    def test_the_offer_costs_no_brain_even_when_one_is_configured(self):
        # It is a report of may_act's verdict, not a model's opinion.
        with mock.patch.object(ikarus_os, "_llm") as llm, \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, self.MSG, provider="claude")
        llm.assert_not_called()
        self.assertEqual(res["provider_used"], "deterministic")

    def test_the_confirmation_goes_through_the_enqueue_path(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            offered = ikarus_os.ask(PROJECT, self.MSG, provider=None)
        prior = {"envelope": offered}
        with mock.patch.object(ikarus_os, "_prior_turn", return_value=prior), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, "ja", provider=None, conversation_id="c1")
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["shell"], ikarus_os.SHELL_HAND)
        # what is queued is the ORIGINAL request, never the word "ja"
        self.assertEqual(res["action"]["args"]["objective"], self.MSG)
        self.assertEqual(res["action"]["args"]["lane"], "local_only")
        self.assertTrue(res["action"]["requires_confirmation"])
        self.assertEqual(res["act"]["confirmation_of"], self.MSG)

    def test_declining_queues_nothing(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            offered = ikarus_os.ask(PROJECT, self.MSG, provider=None)
        with mock.patch.object(ikarus_os, "_prior_turn",
                               return_value={"envelope": offered}), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, "nein", provider=None, conversation_id="c1")
        self.assertEqual(res["intent"], "chat")
        self.assertNotIn("action", res)

    def test_without_conversation_state_a_confirmation_clears_nothing(self):
        # The degrade direction: no store -> MORE restrictive, never less.
        with mock.patch.object(ikarus_os, "_prior_turn", return_value=None), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, "ja", provider=None, conversation_id="c1")
        self.assertEqual(res["intent"], "chat")
        self.assertNotIn("action", res)

    def test_the_same_round_trip_over_the_stream(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            events = list(ikarus_os.ask_stream(PROJECT, self.MSG, provider=None))
        offered = next(p for e, p in events if e == "final")
        self.assertEqual(offered["act_offer"]["objective"], self.MSG)
        with mock.patch.object(ikarus_os, "_prior_turn",
                               return_value={"envelope": offered}), \
                mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            events = list(ikarus_os.ask_stream(PROJECT, "ja", provider=None,
                                               conversation_id="c1"))
        start = next(p for e, p in events if e == "start")
        final = next(p for e, p in events if e == "final")
        self.assertEqual(start["intent"], "enqueue")
        self.assertEqual(final["intent"], "enqueue")
        self.assertEqual(final["action"]["args"]["objective"], self.MSG)


# --------------------------------------------------------------------------- #
# the false positive, landing in the real router                               #
# --------------------------------------------------------------------------- #
class FalsePositiveDoesNotReachTheHandTest(unittest.TestCase):
    def test_does_that_make_sense_is_answered_not_queued(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, "does that make sense", provider=None)
        self.assertEqual(res["intent"], "chat")
        self.assertEqual(res["shell"], ikarus_os.SHELL_VOICE)
        self.assertNotIn("action", res)

    def test_and_the_real_build_request_still_is(self):
        with mock.patch.object(ikarus_os, "_hand_state", return_value=_WORKING):
            res = ikarus_os.ask(PROJECT, "build a settings dialog", provider=None)
        self.assertEqual(res["intent"], "enqueue")
        self.assertEqual(res["action"]["kind"], "queue_task")


if __name__ == "__main__":
    unittest.main()
