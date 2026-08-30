# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""council.bus -- the transcript that cannot silently lie.

A council record is only worth keeping if it can FAIL LOUDLY. These tests attack
the ways it could quietly lie:

  * append/read round-trip, and a chain that stays deterministic across runs and
    across DISPATCH ORDER (four vendors answer in wall-clock order; the chain
    must not);
  * a flipped byte and a deleted line, each of which must be NAMED by line
    number, not swallowed;
  * planted credentials -- an AKIA-shaped key, a PEM block, an evidence path
    named ``.env`` -- which must be REFUSED before writing and appear NOWHERE in
    the file bytes, with the refusal itself reaching the chain;
  * tail truncation, which the chain walk alone cannot see and the anchor must;
  * the doctrine boundaries: no approve/reject/score field, no write anywhere
    near the memory ledger, no bare actor name, no silently skipped participant;
  * 500 turns that verify fast.

All offline, all model-free, no network and no vendor CLI. Every path is
injected into a temp dir so runs/council/ and memory/ are never touched.
"""
from __future__ import annotations

import json
import re
import tempfile
import time
import unittest
from pathlib import Path

from daedalus.council import bus
from daedalus.spine import ledger as spine_ledger

# ``daedalus/memstore.py`` owned the "certified memory" ledger at this path and
# was retired 2026-08-22: a 615-line island with zero production importers whose
# file had never once been written. The path is named here rather than imported
# because the invariant it anchored did NOT retire with it -- council chatter
# must reach no durable store outside its own transcript, neither the memory
# ledger it was once tested against nor the canonical event spine that now
# carries every other record in the tree.
RETIRED_MEMORY_LEDGER = bus.ROOT / "memory" / "ledger.local.jsonl"

# Real shape, fake bytes -- these trip sensitivity.SECRET_FLOOR_CONTENT.
PLANTED_AKIA = "AKIAIOSFODNN7EXAMPLE"
FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)

FIXED_TS = "2026-07-28T00:00:00+00:00"
CID = "council-0001"

ANTHROPIC = bus.actor_id("anthropic", "claude-opus-5")
OPENAI = bus.actor_id("openai", "gpt-5-codex")
GOOGLE = bus.actor_id("google", "gemini-3-pro")
LOCAL = bus.actor_id("local", "qwen2.5-coder:7b")


def _split(actor):
    """(vendor, model) for well-formed actors; placeholders for the malformed
    ones the validation tests deliberately feed in."""
    parts = actor.split(".", 2)
    return (parts[1] if len(parts) > 1 else "unknown",
            parts[2] if len(parts) > 2 else "unknown")


def _turn(actor=ANTHROPIC, content="the diff drops the timeout on line 42",
          **kw):
    vendor, model = _split(actor)
    t = {
        "actor": actor,
        "vendor": vendor,
        "model": model,
        "independence_class": {"vendor": vendor, "family": model},
        "role": "reviewer",
        "content": content,
        "blind": True,
        "lane": "untrusted",
        "meta": {"cli_version": "1.2.3", "endpoint": "127.0.0.1",
                 "latency_ms": 1200, "prompt_tokens": 900},
    }
    t.update(kw)
    return t


def _participant(actor=ANTHROPIC, outcome="responded", **kw):
    vendor, model = _split(actor)
    p = {
        "actor": actor,
        "vendor": vendor,
        "model": model,
        "independence_class": {"vendor": vendor, "family": model},
        "outcome": outcome,
    }
    p.update(kw)
    return p


class BusCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="council_bus_"))
        self.store = self.dir / f"{CID}.jsonl"

    def _bytes(self) -> str:
        return self.store.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# round-trip                                                                   #
# --------------------------------------------------------------------------- #
class Roundtrip(BusCase):
    def test_append_read_roundtrip(self):
        ids = bus.append_round(CID, 1, [_turn(ANTHROPIC), _turn(OPENAI, "no")],
                               store_path=self.store, ts=FIXED_TS)
        self.assertEqual(len(ids), 2)
        recs = bus.load_transcript(self.store)
        self.assertEqual([r["record"] for r in recs], ["turn", "turn"])
        self.assertEqual([r["actor"] for r in recs], sorted([ANTHROPIC, OPENAI]))
        self.assertEqual([r["seq"] for r in recs], [0, 1])
        self.assertEqual([r["round"] for r in recs], [1, 1])
        self.assertIsNone(recs[0]["prev"])
        self.assertEqual(recs[1]["prev"], recs[0]["entry_sha"])
        self.assertEqual([r["id"] for r in recs], ids)
        ok, failures = bus.verify_chain(self.store)
        self.assertTrue(ok, failures)

    def test_seq_is_monotonic_across_rounds(self):
        bus.append_round(CID, 1, [_turn(ANTHROPIC), _turn(OPENAI, "no")],
                         store_path=self.store, ts=FIXED_TS)
        bus.append_round(CID, 2, [_turn(ANTHROPIC, "still no")],
                         store_path=self.store, ts=FIXED_TS)
        recs = bus.load_transcript(self.store)
        self.assertEqual([r["seq"] for r in recs], [0, 1, 2])
        self.assertTrue(bus.verify_chain(self.store)[0])

    def test_metadata_is_carried_per_turn(self):
        bus.append_turn(CID, 1, _turn(LOCAL), store_path=self.store, ts=FIXED_TS)
        rec = bus.load_transcript(self.store)[0]
        self.assertEqual(rec["model"], "qwen2.5-coder:7b")
        self.assertEqual(rec["independence_class"],
                         {"vendor": "local", "family": "qwen2.5-coder:7b"})
        self.assertEqual(rec["meta"]["cli_version"], "1.2.3")
        self.assertEqual(rec["meta"]["latency_ms"], 1200)
        self.assertEqual(rec["lane"], "untrusted")

    def test_evidence_digests_are_recorded(self):
        ev = bus.evidence_ref("daedalus/core.py", b"def f():\n    return 1\n")
        bus.append_turn(CID, 1, _turn(evidence=[ev], refs=["patch-7"]),
                        store_path=self.store, ts=FIXED_TS)
        rec = bus.load_transcript(self.store)[0]
        self.assertEqual(rec["evidence"], [ev])
        self.assertEqual(rec["refs"], ["patch-7"])
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", ev["sha256"]))

    def test_unknown_field_is_refused_not_dropped(self):
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, _turn(verdict="approve"),
                            store_path=self.store, ts=FIXED_TS)


# --------------------------------------------------------------------------- #
# determinism                                                                  #
# --------------------------------------------------------------------------- #
class Determinism(BusCase):
    def test_canonical_body_is_byte_identical(self):
        a = bus._normalize_turn(CID, 1, _turn())
        b = bus._normalize_turn(CID, 1, _turn())
        self.assertEqual(bus.canonical_body_json(a), bus.canonical_body_json(b))
        # ts/prev/entry_sha/id are position, not content: they must not appear.
        for field in ("ts", "prev", "entry_sha", "id", "body_sha"):
            self.assertNotIn(f'"{field}"', bus.canonical_body_json(a))

    def test_reversed_completion_order_yields_identical_chain_head(self):
        turns = [_turn(ANTHROPIC), _turn(OPENAI, "no"), _turn(GOOGLE, "maybe"),
                 _turn(LOCAL, "looks fine")]
        other = self.dir / "reversed.jsonl"
        bus.append_round(CID, 1, list(turns), store_path=self.store, ts=FIXED_TS)
        bus.append_round(CID, 1, list(reversed(turns)), store_path=other,
                         ts=FIXED_TS)
        self.assertEqual(self.store.read_bytes(), other.read_bytes())
        self.assertEqual(bus.transcript_head(self.store),
                         bus.transcript_head(other))

    def test_same_council_twice_yields_identical_bytes(self):
        other = self.dir / "again.jsonl"
        for path in (self.store, other):
            bus.append_round(CID, 1, [_turn(ANTHROPIC), _turn(OPENAI, "no")],
                             store_path=path, ts=FIXED_TS)
            bus.append_roster(CID, [_participant(ANTHROPIC),
                                    _participant(OPENAI)],
                              phase="close", store_path=path, ts=FIXED_TS)
        self.assertEqual(self.store.read_bytes(), other.read_bytes())


# --------------------------------------------------------------------------- #
# tamper detection                                                             #
# --------------------------------------------------------------------------- #
class Tamper(BusCase):
    def _seed(self, n=4):
        bus.append_round(CID, 1, [_turn(a, f"turn from {a}") for a in
                                  (ANTHROPIC, OPENAI, GOOGLE, LOCAL)][:n],
                         store_path=self.store, ts=FIXED_TS)

    def test_flipped_byte_names_the_line(self):
        self._seed()
        lines = self.store.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["content"] = rec["content"] + "!"
        lines[1] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        self.store.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, failures = bus.verify_chain(self.store)
        self.assertFalse(ok)
        self.assertTrue(any(f.startswith("line 2: body_sha mismatch")
                            for f in failures), failures)
        # and only line 2 is accused of a content edit
        self.assertEqual(sum(1 for f in failures if "body_sha mismatch" in f), 1)

    def test_deleted_interior_line_names_the_line(self):
        self._seed()
        lines = self.store.read_text(encoding="utf-8").splitlines()
        del lines[1]
        self.store.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, failures = bus.verify_chain(self.store, use_anchor=False)
        self.assertFalse(ok)
        self.assertTrue(any(f.startswith("line 2: prev linkage broken")
                            for f in failures), failures)

    def test_backdated_ts_names_the_line(self):
        self._seed()
        lines = self.store.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[2])
        rec["ts"] = "1999-01-01T00:00:00+00:00"
        lines[2] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        self.store.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, failures = bus.verify_chain(self.store)
        self.assertFalse(ok)
        self.assertTrue(any(f.startswith("line 3: entry_sha mismatch")
                            for f in failures), failures)

    def test_clean_transcript_verifies(self):
        self._seed()
        ok, failures = bus.verify_chain(self.store)
        self.assertTrue(ok, failures)
        self.assertEqual(failures, [])


# --------------------------------------------------------------------------- #
# tail truncation                                                              #
# --------------------------------------------------------------------------- #
class TailTruncation(BusCase):
    def test_truncation_is_invisible_without_the_anchor(self):
        bus.append_round(CID, 1, [_turn(ANTHROPIC), _turn(OPENAI, "no")],
                         store_path=self.store, ts=FIXED_TS)
        lines = self.store.read_text(encoding="utf-8").splitlines()
        self.store.write_text(lines[0] + "\n", encoding="utf-8")
        # a prefix of a valid chain IS a valid chain -- this is why the anchor
        # exists, and the test states the weakness explicitly.
        self.assertTrue(bus.verify_chain(self.store, use_anchor=False)[0])

    def test_truncation_detected_via_anchor(self):
        bus.append_round(CID, 1, [_turn(ANTHROPIC), _turn(OPENAI, "no")],
                         store_path=self.store, ts=FIXED_TS)
        anchor = bus.read_anchor(self.store)
        self.assertEqual(anchor["count"], 2)
        lines = self.store.read_text(encoding="utf-8").splitlines()
        self.store.write_text(lines[0] + "\n", encoding="utf-8")
        ok, failures = bus.verify_chain(self.store)
        self.assertFalse(ok)
        self.assertTrue(any("transcript length 1 != expected 2" in f
                            for f in failures), failures)
        self.assertTrue(any("head" in f for f in failures), failures)

    def test_whole_file_deleted_is_detected(self):
        bus.append_round(CID, 1, [_turn(ANTHROPIC)], store_path=self.store,
                         ts=FIXED_TS)
        count, head = bus.transcript_head(self.store)
        self.store.unlink()
        ok, failures = bus.verify_chain(self.store, expected_count=count,
                                        expected_head=head)
        self.assertFalse(ok)
        self.assertEqual(len(failures), 2, failures)


# --------------------------------------------------------------------------- #
# secret floor                                                                 #
# --------------------------------------------------------------------------- #
class SecretFloor(BusCase):
    def _assert_refused(self, turn, marker):
        bus.append_turn(CID, 1, turn, store_path=self.store, ts=FIXED_TS)
        raw = self._bytes()
        self.assertNotIn(marker, raw)
        recs = bus.load_transcript(self.store)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["status"], "refused")
        self.assertEqual(recs[0]["content"], "")
        self.assertTrue(recs[0]["reason"])
        # the refusal itself is chained -- a refused voice is still a voice
        self.assertTrue(bus.verify_chain(self.store)[0])
        return recs[0]

    def test_akia_in_content_is_refused(self):
        rec = self._assert_refused(
            _turn(content=f"the diff hardcodes {PLANTED_AKIA} in settings"),
            PLANTED_AKIA)
        self.assertIn("secret content", rec["reason"])
        # the refusal still names WHO was refused
        self.assertEqual(rec["actor"], ANTHROPIC)

    def test_pem_block_in_content_is_refused(self):
        rec = self._assert_refused(_turn(content=FAKE_PEM), "PRIVATE KEY")
        self.assertIn("secret content", rec["reason"])

    def test_dotenv_evidence_path_is_refused(self):
        # The rule LABEL names the marker (".env") -- a fixed string, the same
        # discipline the retired memstore used, and bus.py has carried since.
        # What must not survive is the cited PATH and
        # its digest: the refusal must not become a map to the secret file.
        ev = bus.evidence_ref("apps/web/.env.production", b"TOKEN=x\n")
        rec = self._assert_refused(_turn(evidence=[ev]),
                                   "apps/web/.env.production")
        self.assertNotIn(ev["sha256"], self._bytes())
        self.assertIn("secret path marker", rec["reason"])
        self.assertEqual(rec["evidence"], [])

    def test_id_rsa_evidence_path_is_refused(self):
        ev = bus.evidence_ref("home/.ssh/id_rsa", b"key\n")
        self._assert_refused(_turn(evidence=[ev]), "home/.ssh/id_rsa")

    def test_secret_in_refs_is_refused(self):
        self._assert_refused(_turn(refs=[f"run-{PLANTED_AKIA}"]), PLANTED_AKIA)

    def test_secret_in_meta_endpoint_is_refused(self):
        self._assert_refused(
            _turn(meta={"endpoint": f"https://x/{PLANTED_AKIA}"}), PLANTED_AKIA)

    def test_inbound_vendor_response_is_floored_before_chaining(self):
        # This is the INBOUND direction: a vendor quoting the evidence back. Once
        # a secret is inside a chained line it can never be redacted without
        # breaking verify_chain, so it must never get in.
        vendor_said = f"I found the key {PLANTED_AKIA} in your diff"
        self._assert_refused(_turn(OPENAI, content=vendor_said), PLANTED_AKIA)

    def test_refusal_degrades_to_anonymous_when_identity_carries_the_secret(self):
        bus.append_turn(CID, 1, _turn(model=PLANTED_AKIA), store_path=self.store,
                        ts=FIXED_TS)
        self.assertNotIn(PLANTED_AKIA, self._bytes())
        rec = bus.load_transcript(self.store)[0]
        self.assertEqual(rec["status"], "refused")
        self.assertEqual(rec["actor"], "council.redacted.redacted")

    def test_withheld_paths_are_named_not_refused(self):
        # Deliberate carve-out: withheld paths are the ones that did NOT leave
        # the machine. Refusing the turn that proves the floor worked would be
        # the floor eating its own receipt.
        bus.append_turn(CID, 1, _turn(withheld=[".env", "secrets/id_rsa"]),
                        store_path=self.store, ts=FIXED_TS)
        rec = bus.load_transcript(self.store)[0]
        self.assertEqual(rec["status"], "spoke")
        self.assertEqual(rec["withheld"], [".env", "secrets/id_rsa"])

    def test_secret_in_roster_refuses_the_participant_list(self):
        bus.append_roster(CID, [_participant(ANTHROPIC, model=PLANTED_AKIA)],
                          store_path=self.store, ts=FIXED_TS)
        self.assertNotIn(PLANTED_AKIA, self._bytes())
        rec = bus.load_transcript(self.store)[0]
        self.assertEqual(rec["participants"], [])
        self.assertTrue(rec["refused"])


# --------------------------------------------------------------------------- #
# doctrine boundaries                                                          #
# --------------------------------------------------------------------------- #
_FORBIDDEN_SEGMENTS = {
    "approve", "approved", "reject", "rejected", "verdict", "score", "ok",
    "pass", "passed", "majority", "consensus", "confidence", "vote", "rating",
}


class Doctrine(BusCase):
    def test_no_verdict_shaped_field_on_any_record(self):
        bus.append_round(CID, 1, [_turn(ANTHROPIC)], store_path=self.store,
                         ts=FIXED_TS)
        bus.append_roster(CID, [_participant(ANTHROPIC)], store_path=self.store,
                          ts=FIXED_TS)

        def walk(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    for seg in str(k).split("_"):
                        self.assertNotIn(
                            seg.lower(), _FORBIDDEN_SEGMENTS,
                            f"field {path}{k!r} mints a promotion token: the "
                            f"gate decides, not a model")
                    walk(v, f"{path}{k}.")
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, path)

        for rec in bus.load_transcript(self.store):
            walk(rec)

    def test_no_council_write_touches_another_durable_store(self):
        """Council opinion reaches its own transcript and nothing else.

        Both paths are checked because both have been the answer to "where does
        durable truth live" in this tree: the retired memory ledger, and the
        canonical event spine that now holds intents, attempts, promotions and
        conversation turns. A council write landing in either would promote
        deliberation to record, which is the one thing bus.py exists to refuse.
        """
        watched = [RETIRED_MEMORY_LEDGER, spine_ledger.default_db_path()]
        before = [(p.exists(), p.read_bytes() if p.exists() else None)
                  for p in watched]
        bus.append_round(CID, 1, [_turn(ANTHROPIC)], store_path=self.store,
                         ts=FIXED_TS)
        for path, (existed, body) in zip(watched, before):
            self.assertEqual(path.exists(), existed,
                             f"a council write created {path}")
            if existed:
                self.assertEqual(path.read_bytes(), body,
                                 f"a council write changed {path}")

    def test_store_under_memory_dir_is_refused(self):
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, _turn(),
                            store_path=RETIRED_MEMORY_LEDGER,
                            ts=FIXED_TS)
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, _turn(),
                            store_path=bus.ROOT / "memory" / "council.jsonl",
                            ts=FIXED_TS)

    def test_bare_actor_name_is_refused(self):
        for bad in ("claude", "vendor.anthropic.claude", "council.anthropic",
                    "council..claude"):
            with self.assertRaises(ValueError, msg=bad):
                bus.append_turn(CID, 1, _turn(actor=bad), store_path=self.store,
                                ts=FIXED_TS)

    def test_missing_independence_class_is_refused(self):
        t = _turn()
        del t["independence_class"]
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, t, store_path=self.store, ts=FIXED_TS)
        t = _turn(independence_class={"host": "100.119.126.9"})
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, t, store_path=self.store, ts=FIXED_TS)

    def test_caller_cannot_assert_a_refusal(self):
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, _turn(status="refused", content="x"),
                            store_path=self.store, ts=FIXED_TS)

    def test_empty_spoke_turn_is_refused(self):
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, _turn(content="   "), store_path=self.store,
                            ts=FIXED_TS)

    def test_unavailable_needs_a_machine_reason(self):
        with self.assertRaises(ValueError):
            bus.append_turn(CID, 1, _turn(GOOGLE, "", status="unavailable"),
                            store_path=self.store, ts=FIXED_TS)
        with self.assertRaises(ValueError):
            bus.append_turn(
                CID, 1, _turn(GOOGLE, "", status="unavailable",
                              reason="it seemed unhappy"),
                store_path=self.store, ts=FIXED_TS)

    def test_unavailable_participant_is_a_turn_not_an_absence(self):
        # agy is not signed in: a two-vendor council must never render
        # identically to a four-vendor one.
        bus.append_round(CID, 1, [
            _turn(ANTHROPIC),
            _turn(OPENAI, "no"),
            _turn(GOOGLE, "", status="unavailable", reason="not_authenticated"),
            _turn(LOCAL, "", status="budget_exhausted"),
        ], store_path=self.store, ts=FIXED_TS)
        recs = bus.load_transcript(self.store)
        self.assertEqual(len(recs), 4)
        by_actor = {r["actor"]: r for r in recs}
        self.assertEqual(by_actor[GOOGLE]["status"], "unavailable")
        self.assertEqual(by_actor[GOOGLE]["reason"], "not_authenticated")
        self.assertEqual(by_actor[LOCAL]["reason"], "budget_exhausted")
        self.assertTrue(bus.verify_chain(self.store)[0])

    def test_duplicate_actor_in_one_round_is_refused(self):
        with self.assertRaises(ValueError):
            bus.append_round(CID, 1, [_turn(ANTHROPIC), _turn(ANTHROPIC, "again")],
                             store_path=self.store, ts=FIXED_TS)

    def test_roster_counts_degraded_and_distinct_classes(self):
        bus.append_roster(CID, [
            _participant(ANTHROPIC),
            _participant(OPENAI),
            _participant(GOOGLE, outcome="unavailable",
                         reason="not_authenticated"),
            _participant(LOCAL),
        ], phase="close", store_path=self.store, ts=FIXED_TS)
        rec = bus.load_transcript(self.store)[0]
        self.assertEqual(rec["requested"], 4)
        self.assertEqual(rec["responded"], 3)
        self.assertEqual(rec["unavailable"], 1)
        self.assertTrue(rec["degraded"])
        self.assertEqual(rec["distinct_classes"], 3)
        self.assertEqual(rec["duplicate_classes"], [])

    def test_roster_flags_two_participants_of_one_weight_class(self):
        # local 7b and bench 7b are the SAME weights on two sockets: one voice
        # counted twice. Different endpoint, same independence class.
        bench = bus.actor_id("bench", "qwen2.5-coder:7b")
        dupe = _participant(bench)
        dupe["independence_class"] = {"vendor": "local", "family": "qwen2.5-coder:7b"}
        bus.append_roster(CID, [_participant(LOCAL), dupe, _participant(ANTHROPIC)],
                          phase="close", store_path=self.store, ts=FIXED_TS)
        rec = bus.load_transcript(self.store)[0]
        self.assertEqual(rec["distinct_classes"], 2)
        self.assertEqual(rec["duplicate_classes"], ["local/qwen2.5-coder:7b"])
        self.assertFalse(rec["degraded"])

    def test_council_id_must_be_filename_safe(self):
        for bad in ("../escape", "a/b", ".hidden", ""):
            with self.assertRaises(ValueError, msg=bad):
                bus.council_store_path(bad)


# --------------------------------------------------------------------------- #
# scale                                                                        #
# --------------------------------------------------------------------------- #
class Scale(BusCase):
    def test_500_turns_append_and_verify_fast(self):
        actors = [bus.actor_id("local", f"qwen-{i:03d}") for i in range(50)]
        t0 = time.time()
        for rnd in range(10):
            bus.append_round(CID, rnd, [
                _turn(a, f"round {rnd} from {a}") for a in actors
            ], store_path=self.store, ts=FIXED_TS)
        append_s = time.time() - t0
        recs = bus.load_transcript(self.store)
        self.assertEqual(len(recs), 500)
        self.assertEqual([r["seq"] for r in recs], list(range(500)))
        t1 = time.time()
        ok, failures = bus.verify_chain(self.store)
        verify_s = time.time() - t1
        self.assertTrue(ok, failures[:5])
        self.assertLess(append_s, 10.0, f"append took {append_s:.2f}s")
        self.assertLess(verify_s, 5.0, f"verify took {verify_s:.2f}s")

    def test_one_flipped_byte_in_500_is_still_named(self):
        actors = [bus.actor_id("local", f"qwen-{i:03d}") for i in range(50)]
        for rnd in range(10):
            bus.append_round(CID, rnd, [_turn(a, f"r{rnd} {a}") for a in actors],
                             store_path=self.store, ts=FIXED_TS)
        lines = self.store.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[301])
        rec["content"] = "quietly rewritten"
        lines[301] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        self.store.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, failures = bus.verify_chain(self.store)
        self.assertFalse(ok)
        self.assertTrue(any(f.startswith("line 302: body_sha mismatch")
                            for f in failures), failures[:5])


if __name__ == "__main__":
    unittest.main()
