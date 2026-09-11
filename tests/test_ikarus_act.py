"""ikarus_act -- the CAPABILITY predicate, tested separately from classify().

The whole point of the split is that these two questions have different error
budgets, so they get different suites. This file never asserts anything about
which panel the UI shows; test_ikarus_os.py's ClassifyTest never asserts
anything about what may reach an executor. The one place they meet is
DivergenceTest, which pins the cases where the two answers legitimately differ.
"""
import unittest

from daedalus.orchestration.ikarus import shell as ikarus_os
from daedalus.orchestration.ikarus import act as ikarus_act
from daedalus.orchestration.ikarus.act import may_act


def _turn_with_offer(objective, reason="r", signal="s"):
    """A prior turn shaped like one ikarus_os persists after an act offer."""
    return {"envelope": {"intent": "chat",
                         "act_offer": {"objective": objective,
                                       "reason": reason, "signal": signal}}}


class MayActAllowsTest(unittest.TestCase):
    """The allow half: a leading imperative act verb, not a question."""

    def test_leading_act_verb_is_allowed(self):
        for msg in ("build a settings dialog",
                    "fix the clone detector",
                    "add a health probe for the bench",
                    "write the readme",
                    "run the tests",
                    "refactor the router",
                    "mach den Parser robuster",
                    "baue eine Einstellungsseite",
                    "füge einen Healthcheck hinzu",
                    "prüf die Tests und repariere den Fehler",
                    "schau dir core.py an",
                    "analysiere den fehlgeschlagenen Lauf"):
            with self.subTest(msg=msg):
                d = may_act(msg)
                self.assertTrue(d.allowed, d)
                self.assertFalse(d.suspected)
                self.assertEqual(d.objective, msg)

    def test_leading_filler_is_stripped(self):
        for msg in ("please build a login page", "ok build a login page",
                    "hey just fix the parser"):
            with self.subTest(msg=msg):
                self.assertTrue(may_act(msg).allowed, msg)

    def test_signal_names_the_evidence(self):
        d = may_act("build a settings dialog")
        self.assertIn("build", d.signal)
        self.assertIn("act verb", d.signal)


class MayActRefusesTest(unittest.TestCase):
    """The refuse half -- including the false-positive budget's named case."""

    def test_does_that_make_sense_never_reaches_tools(self):
        # THE case. classify() says "enqueue" for this (substring "make "), so
        # if the intent answer were reused as the capability answer, a
        # rhetorical question would reach a tool-bearing executor.
        d = may_act("does that make sense")
        self.assertFalse(d.allowed)
        self.assertFalse(d.suspected, "not even suspected: it is a plain question")

    def test_plain_chat_is_quiet(self):
        for msg in ("hello, who are you?", "what's running?", "thanks!",
                    "how does the machine work", "Test coverage is low.",
                    "Start time is slow.", "Bauen ist kompliziert.",
                    "Testen ist wichtig.", "Analysieren braucht Zeit.",
                    "Starten dauert lange.", "Machst du das morgen"):
            with self.subTest(msg=msg):
                d = may_act(msg)
                self.assertFalse(d.allowed)
                self.assertFalse(d.suspected, f"{msg} -> {d.signal}")

    def test_empty_message(self):
        for msg in ("", "   ", None):
            with self.subTest(msg=msg):
                self.assertFalse(may_act(msg).allowed)

    def test_bare_affirmative_alone_clears_nothing(self):
        # Without a pending offer, "yes" is just a word.
        for msg in ("yes", "ja", "do it", "confirm"):
            with self.subTest(msg=msg):
                d = may_act(msg, "chat", conversation=None)
                self.assertFalse(d.allowed, f"{msg} cleared with no offer")
                self.assertEqual(d.confirmation_of, "")


class MayActSuspectsTest(unittest.TestCase):
    """Suspected is a REFUSAL that explains itself -- never a soft allow."""

    def test_german_act_request(self):
        d = may_act("kannst du das mal bauen")
        self.assertFalse(d.allowed)
        self.assertTrue(d.suspected)
        self.assertIn("German", d.signal)
        self.assertEqual(d.objective, "kannst du das mal bauen")

    def test_german_discussion_is_not_an_action_request(self):
        d = may_act("was machen wir jetzt?")
        self.assertFalse(d.allowed)
        self.assertFalse(d.suspected)

        statement = may_act("ich prüfe das später")
        self.assertFalse(statement.allowed)
        self.assertFalse(statement.suspected)

    def test_directed_and_interrogative_forms(self):
        for msg, needle in (("can you build a thing?", "directed"),
                            ("could you fix the parser", "directed"),
                            ("i want you to fix the parser", "want"),
                            ("build a settings dialog?", "question")):
            with self.subTest(msg=msg):
                d = may_act(msg)
                self.assertFalse(d.allowed, f"{msg} was ALLOWED")
                self.assertTrue(d.suspected, msg)
                self.assertIn(needle, d.signal)

    def test_suspected_is_never_allowed(self):
        for msg in ("kannst du das mal bauen", "can you build a thing?",
                    "build a settings dialog?"):
            with self.subTest(msg=msg):
                self.assertFalse(may_act(msg).allowed)

    def test_german_imperative_is_exact_and_machine_is_not_a_stem_match(self):
        # "mach" must not match inside "machine" -- a stem match here would turn
        # every question about this machine into a suspected build request.
        self.assertFalse(may_act("what does the machine do").suspected)
        decision = may_act("mach das bitte fertig")
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.suspected)
        self.assertIn("German", decision.signal)


class ConfirmationTest(unittest.TestCase):
    OBJ = "kannst du das mal bauen"

    def test_affirmative_after_an_offer_clears_the_original_objective(self):
        conv = [_turn_with_offer(self.OBJ)]
        for word in ("yes", "ja", "mach das", "do it", "Confirm."):
            with self.subTest(word=word):
                d = may_act(word, "chat", conv)
                self.assertTrue(d.allowed, word)
                self.assertEqual(d.objective, self.OBJ)
                self.assertEqual(d.confirmation_of, self.OBJ)

    def test_decline_after_an_offer_refuses_quietly(self):
        d = may_act("no", "chat", [_turn_with_offer(self.OBJ)])
        self.assertFalse(d.allowed)
        self.assertFalse(d.suspected)
        self.assertEqual(d.signal, "declined")

    def test_a_sentence_containing_yes_is_not_a_confirmation(self):
        d = may_act("yes, but does that make sense?", "chat",
                    [_turn_with_offer(self.OBJ)])
        self.assertFalse(d.allowed)
        self.assertEqual(d.confirmation_of, "")

    def test_no_offer_on_the_previous_turn(self):
        conv = [{"envelope": {"intent": "chat"}}]
        self.assertFalse(may_act("yes", "chat", conv).allowed)

    def test_malformed_offer_is_no_offer(self):
        for env in ({"act_offer": {}},
                    {"act_offer": {"objective": ""}},
                    {"act_offer": "build it"},
                    {"act_offer": None}):
            with self.subTest(env=env):
                self.assertIsNone(ikarus_act.pending_offer({"envelope": env}))
                self.assertFalse(may_act("yes", "chat", [{"envelope": env}]).allowed)

    def test_pending_offer_accepts_a_turn_object_a_dict_and_a_list(self):
        class _Turn:
            envelope = {"act_offer": {"objective": self.OBJ}}

        for conv in (_Turn(), _Turn, {"envelope": {"act_offer": {"objective": self.OBJ}}},
                     [_turn_with_offer("earlier"), _turn_with_offer(self.OBJ)]):
            with self.subTest(conv=type(conv).__name__):
                offer = ikarus_act.pending_offer(conv)
                self.assertIsNotNone(offer)
                self.assertEqual(offer["objective"], self.OBJ)

    def test_no_conversation_at_all(self):
        self.assertIsNone(ikarus_act.pending_offer(None))
        self.assertIsNone(ikarus_act.pending_offer([]))


class DivergenceTest(unittest.TestCase):
    """The two predicates answer different questions and may disagree.

    Pinned here so a future edit that quietly merges them fails loudly.
    """

    def test_fix_the_clone_detector_is_the_documented_divergence(self):
        msg = "fix the clone detector"
        # classify's precedence puts it on the local, no-spend distill report...
        self.assertEqual(ikarus_os.classify(msg), "distill")
        # ...while the capability predicate says the SENTENCE is clearable.
        self.assertTrue(may_act(msg).allowed)
        # The route is chosen by intent, so no tool-bearing executor is reached.
        self.assertEqual(ikarus_os._route("distill", may_act(msg)), "distill")

    def test_does_that_make_sense_diverges_the_other_way(self):
        msg = "does that make sense"
        self.assertEqual(ikarus_os.classify(msg), "enqueue")   # the substring table
        self.assertFalse(may_act(msg).allowed)                 # the capability answer
        self.assertEqual(ikarus_os._route("enqueue", may_act(msg)), "chat")

    def test_the_verdict_does_not_depend_on_the_intent_label(self):
        # `intent` is carried for reporting, never read by a branch.
        for msg in ("build a login page", "does that make sense",
                    "kannst du das mal bauen", "hello"):
            with self.subTest(msg=msg):
                a = may_act(msg, "chat")
                b = may_act(msg, "enqueue")
                self.assertEqual(a.allowed, b.allowed)
                self.assertEqual(a.suspected, b.suspected)
                self.assertEqual(a.signal, b.signal)

    def test_decision_is_serialisable_and_carries_the_intent(self):
        d = may_act("build a login page", "enqueue")
        self.assertEqual(d.to_dict()["intent"], "enqueue")
        self.assertIs(d.to_dict()["allowed"], True)


if __name__ == "__main__":
    unittest.main()
