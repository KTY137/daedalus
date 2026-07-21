"""memstore -- the memory ledger core: memory that cannot silently lie.

A ledger is only worth keeping if it can FAIL LOUDLY. These tests attack the ways
it could quietly lie:

  * a body that dedupes when it should, and a chain that stays deterministic
    across runs (roundtrip / determinism);
  * a flipped byte or a deleted line that the chain walk must NAME, not swallow
    (tamper);
  * a planted credential that must be REFUSED at write and appear NOWHERE in the
    file bytes (secret floor);
  * trust promotion that must require independent confirmations and a flag that
    must be terminal (fold);
  * a 1,000-line ledger that verifies fast and still catches one flipped byte
    (scale).

All offline, all model-free. Every path is injected so the real memory/ dir is
never touched.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from daedalus import memstore

# Real shape, fake bytes -- these trip sensitivity.SECRET_FLOOR_CONTENT.
PLANTED_AKIA = "AKIAIOSFODNN7EXAMPLE"
FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)

FIXED_TS = "2026-07-21T00:00:00+00:00"


def _entry(text="landed an edit", kind="landed_edit", layer="episodic",
           paths=None, proof=None):
    e = {"layer": layer, "kind": kind, "text": text,
         "provenance": {"source": "test", "agent": "daedalus", "project": "p"}}
    if paths is not None:
        e["paths"] = paths
    if proof is not None:
        e["proof"] = proof
    return e


class LedgerRoundtrip(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="memstore_"))
        self.ledger = self.dir / "ledger.local.jsonl"
        self.state = self.dir / "state.local.json"

    def test_append_load_fold_roundtrip(self):
        i1 = memstore.append_entry(_entry("first"), store_path=self.ledger)
        i2 = memstore.append_entry(_entry("second"), store_path=self.ledger)
        recs = memstore.load_ledger(self.ledger)
        self.assertEqual(len(recs), 2)
        self.assertEqual([r["id"] for r in recs], [i1, i2])
        # genesis prev is null; second links to first.
        self.assertIsNone(recs[0]["prev"])
        self.assertEqual(recs[1]["prev"], recs[0]["entry_sha"])
        st = memstore.fold_state(recs, state_path=self.state)
        self.assertEqual(st[i1]["tier"], "quarantine")
        self.assertEqual(st[i2]["confirmations"], 0)
        # derived state file is written and well-formed.
        payload = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(payload["state_version"], "dmem-state/1")
        self.assertIn(i1, payload["entries"])

    def test_duplicate_body_is_noop(self):
        i1 = memstore.append_entry(_entry("same body"), store_path=self.ledger)
        i2 = memstore.append_entry(_entry("same body"), store_path=self.ledger)
        self.assertEqual(i1, i2)
        self.assertEqual(len(memstore.load_ledger(self.ledger)), 1)

    def test_trust_is_forced_quarantine_at_write(self):
        # Caller cannot assert trust; write always mints quarantine.
        e = _entry("sneaky")
        e["trust"] = {"minted_tier": "primary"}
        i = memstore.append_entry(e, store_path=self.ledger)
        rec = memstore.load_ledger(self.ledger)[0]
        self.assertEqual(rec["trust"]["minted_tier"], "quarantine")
        self.assertEqual(rec["id"], i)


class Determinism(unittest.TestCase):
    def _build(self, path):
        for n in ("alpha", "beta", "gamma"):
            memstore.append_entry(_entry(n), store_path=path, ts=FIXED_TS)

    def test_two_runs_byte_identical(self):
        d = Path(tempfile.mkdtemp(prefix="memstore_det_"))
        a, b = d / "a.jsonl", d / "b.jsonl"
        self._build(a)
        self._build(b)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        ok, fails = memstore.verify_ledger(a)
        self.assertTrue(ok, fails)


class Tamper(unittest.TestCase):
    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_tmp_")) / "l.jsonl"
        for n in ("one", "two", "three", "four"):
            memstore.append_entry(_entry(n), store_path=self.ledger, ts=FIXED_TS)

    def test_clean_ledger_verifies(self):
        ok, fails = memstore.verify_ledger(self.ledger)
        self.assertTrue(ok, fails)
        self.assertEqual(fails, [])

    def test_flip_byte_in_middle_line_is_named(self):
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        # Flip a character inside the text field of line 2 (index 1).
        lines[1] = lines[1].replace('"two"', '"tXo"')
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, fails = memstore.verify_ledger(self.ledger)
        self.assertFalse(ok)
        self.assertTrue(any("line 2" in f and "body_sha" in f for f in fails), fails)
        # The tamper is attributed to exactly one line's content check.
        self.assertTrue(all(not f.startswith("line 1") for f in fails), fails)

    def test_delete_middle_line_breaks_chain(self):
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        del lines[1]  # remove line 2; line 3's prev now dangles
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, fails = memstore.verify_ledger(self.ledger)
        self.assertFalse(ok)
        self.assertTrue(any("prev linkage" in f for f in fails), fails)


class SecretFloor(unittest.TestCase):
    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_sec_")) / "l.jsonl"

    def test_planted_akia_refused_and_absent_from_bytes(self):
        rid = memstore.append_entry(
            _entry(text=f"deploy key is {PLANTED_AKIA} keep it"),
            store_path=self.ledger)
        recs = memstore.load_ledger(self.ledger)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["kind"], "gate_outcome")
        self.assertEqual(recs[0]["id"], rid)
        # The rule name is recorded; the secret is NOT anywhere in the file.
        raw = self.ledger.read_bytes()
        self.assertNotIn(PLANTED_AKIA.encode(), raw)
        self.assertIn(b"AWS access key id", raw)

    def test_planted_pem_in_detail_refused_and_absent(self):
        memstore.append_entry(
            _entry(text="repair recipe", proof={
                "type": "verify_result", "detail": [FAKE_PEM]}),
            store_path=self.ledger)
        raw = self.ledger.read_bytes()
        self.assertNotIn(b"BEGIN RSA PRIVATE KEY", raw)
        self.assertIn(b"PEM private key block", raw)
        self.assertEqual(memstore.load_ledger(self.ledger)[0]["kind"],
                         "gate_outcome")

    def test_secret_path_marker_refused(self):
        memstore.append_entry(
            _entry(text="clean text", paths=["config/prod.env"]),
            store_path=self.ledger)
        self.assertEqual(memstore.load_ledger(self.ledger)[0]["kind"],
                         "gate_outcome")


class Fold(unittest.TestCase):
    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_fold_")) / "l.jsonl"
        self.state = self.ledger.parent / "state.local.json"

    def test_three_confirms_promote(self):
        eid = memstore.append_entry(_entry("promote me"), store_path=self.ledger)
        for _ in range(memstore.MEM_CONFIRM_THRESHOLD):
            memstore.append_confirm(eid, store_path=self.ledger)
        st = memstore.fold_state(memstore.load_ledger(self.ledger),
                                 state_path=self.state)
        self.assertEqual(st[eid]["tier"], "primary")
        self.assertEqual(st[eid]["confirmations"], 3)

    def test_two_confirms_stay_quarantined(self):
        eid = memstore.append_entry(_entry("not yet"), store_path=self.ledger)
        memstore.append_confirm(eid, store_path=self.ledger)
        memstore.append_confirm(eid, store_path=self.ledger)
        st = memstore.fold_state(memstore.load_ledger(self.ledger),
                                 state_path=self.state)
        self.assertEqual(st[eid]["tier"], "quarantine")

    def test_flag_is_terminal_confirms_do_not_resurrect(self):
        eid = memstore.append_entry(_entry("flag me"), store_path=self.ledger)
        memstore.append_flag(eid, ["verify_failed"], store_path=self.ledger)
        # Even MEM_CONFIRM_THRESHOLD confirms after the flag cannot resurrect it.
        for _ in range(memstore.MEM_CONFIRM_THRESHOLD):
            memstore.append_confirm(eid, store_path=self.ledger)
        st = memstore.fold_state(memstore.load_ledger(self.ledger),
                                 state_path=self.state)
        self.assertEqual(st[eid]["tier"], "flagged")
        self.assertEqual(st[eid]["flags"], ["verify_failed"])

    def test_flag_demotes_a_promoted_entry(self):
        eid = memstore.append_entry(_entry("promoted then flagged"),
                                    store_path=self.ledger)
        for _ in range(memstore.MEM_CONFIRM_THRESHOLD):
            memstore.append_confirm(eid, store_path=self.ledger)
        memstore.append_flag(eid, ["late_repro_failure"], store_path=self.ledger)
        st = memstore.fold_state(memstore.load_ledger(self.ledger),
                                 state_path=self.state)
        self.assertEqual(st[eid]["tier"], "flagged")


class Scale(unittest.TestCase):
    def test_thousand_entries_verify_fast_and_catch_flip(self):
        import time
        ledger = Path(tempfile.mkdtemp(prefix="memstore_scale_")) / "l.jsonl"
        for n in range(1000):
            memstore.append_entry(_entry(f"entry number {n}"),
                                  store_path=ledger, ts=FIXED_TS)
        t0 = time.perf_counter()
        ok, fails = memstore.verify_ledger(ledger)
        elapsed = time.perf_counter() - t0
        self.assertTrue(ok, fails)
        self.assertLess(elapsed, 1.0, f"verify took {elapsed:.3f}s")
        # Flip one byte at an arbitrary interior position.
        lines = ledger.read_text(encoding="utf-8").splitlines()
        lines[500] = lines[500].replace("entry number 500", "entry number 5X0")
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok2, fails2 = memstore.verify_ledger(ledger)
        self.assertFalse(ok2)
        self.assertTrue(any("line 501" in f for f in fails2), fails2)


class SecretFloorProvenanceChannels(unittest.TestCase):
    """Regression: the floor must scan EVERY free-text channel, not only text/
    proof.detail. A value-shaped credential in provenance/refs/anchor was written
    verbatim into the hash-chained ledger (irredactable). Findings 1 & 7."""

    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_provsec_")) / "l.jsonl"

    def _refused_and_absent(self, entry):
        memstore.append_entry(entry, store_path=self.ledger)
        raw = self.ledger.read_bytes()
        self.assertNotIn(PLANTED_AKIA.encode(), raw)
        recs = memstore.load_ledger(self.ledger)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["kind"], "gate_outcome")

    def test_secret_in_provenance_source_refused(self):
        self._refused_and_absent({
            "layer": "episodic", "kind": "landed_edit", "text": "clean",
            "provenance": {"source": f"see {PLANTED_AKIA}"}})

    def test_secret_in_provenance_task_id_refused(self):
        self._refused_and_absent({
            "layer": "episodic", "kind": "landed_edit", "text": "clean",
            "provenance": {"task_id": PLANTED_AKIA}})

    def test_secret_in_refs_run_report_refused(self):
        self._refused_and_absent({
            "layer": "episodic", "kind": "landed_edit", "text": "clean",
            "refs": {"run_report": f"report {PLANTED_AKIA}"}})

    def test_secret_in_anchor_commit_sha_refused(self):
        self._refused_and_absent({
            "layer": "episodic", "kind": "landed_edit", "text": "clean",
            "anchor": {"commit_sha": PLANTED_AKIA}})

    def test_pem_in_provenance_refused(self):
        self._refused_and_absent({
            "layer": "episodic", "kind": "landed_edit", "text": "clean",
            "provenance": {"agent": FAKE_PEM}})


class RefusalReceiptDropsProvenanceSecret(unittest.TestCase):
    """Regression: an entry refused for a TEXT secret must not smuggle a DIFFERENT
    provenance-borne secret into the redacted gate_outcome receipt. Finding 8."""

    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_receipt_")) / "l.jsonl"

    def test_provenance_secret_dropped_from_redacted_receipt(self):
        prov_secret = "AKIA1111111111111111"  # distinct AWS-shaped key
        memstore.append_entry({
            "layer": "episodic", "kind": "landed_edit",
            "text": f"the key is {PLANTED_AKIA}",
            "provenance": {"source": f"leaked {prov_secret}"}},
            store_path=self.ledger)
        raw = self.ledger.read_bytes()
        # Neither the text secret nor the provenance secret reaches the file.
        self.assertNotIn(PLANTED_AKIA.encode(), raw)
        self.assertNotIn(prov_secret.encode(), raw)
        rec = memstore.load_ledger(self.ledger)[0]
        self.assertEqual(rec["kind"], "gate_outcome")
        # Provenance was dropped (not re-embedded) because it carried a secret.
        self.assertEqual(rec["provenance"]["source"], "")

    def test_clean_provenance_is_preserved_in_receipt(self):
        memstore.append_entry({
            "layer": "episodic", "kind": "landed_edit",
            "text": f"the key is {PLANTED_AKIA}",
            "provenance": {"source": "task-42", "agent": "daedalus"}},
            store_path=self.ledger)
        rec = memstore.load_ledger(self.ledger)[0]
        self.assertEqual(rec["kind"], "gate_outcome")
        # A clean provenance is retained so the operator sees whose entry refused.
        self.assertEqual(rec["provenance"]["source"], "task-42")


class TailTruncation(unittest.TestCase):
    """Regression: tail truncation is invisible to the genesis-forward walk; it is
    caught only against a ledger_head anchor. Finding 2."""

    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_tail_")) / "l.jsonl"
        for n in ("a", "b", "c", "d", "e"):
            memstore.append_entry(_entry(n), store_path=self.ledger, ts=FIXED_TS)
        self.count, self.head = memstore.ledger_head(self.ledger)

    def test_tail_truncation_undetected_without_anchor_but_named_with_it(self):
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        self.ledger.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
        # Plain walk still verifies clean (a valid prefix is a valid chain)...
        ok, _ = memstore.verify_ledger(self.ledger)
        self.assertTrue(ok)
        # ...but the anchor catches both the length shortfall and the moved head.
        ok2, fails = memstore.verify_ledger(
            self.ledger, expected_count=self.count, expected_head=self.head)
        self.assertFalse(ok2)
        self.assertTrue(any("length" in f for f in fails), fails)
        self.assertTrue(any("head" in f for f in fails), fails)

    def test_whole_file_deletion_caught_by_anchor(self):
        self.ledger.unlink()
        ok, fails = memstore.verify_ledger(
            self.ledger, expected_count=self.count, expected_head=self.head)
        self.assertFalse(ok)
        self.assertTrue(any("missing" in f for f in fails), fails)

    def test_intact_ledger_passes_its_own_anchor(self):
        ok, fails = memstore.verify_ledger(
            self.ledger, expected_count=self.count, expected_head=self.head)
        self.assertTrue(ok, fails)

    def test_state_file_persists_the_anchor(self):
        state = self.ledger.parent / "state.local.json"
        memstore.fold_state(memstore.load_ledger(self.ledger), state_path=state)
        payload = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(payload["ledger_count"], self.count)
        self.assertEqual(payload["ledger_head"], self.head)


class TornTailAppend(unittest.TestCase):
    """Regression: appending after a torn (newline-less) tail line must not fuse
    the new record onto the fragment and destroy it under a success id. Finding 3."""

    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_torn_")) / "l.jsonl"

    def test_append_after_torn_tail_lands_as_its_own_line(self):
        memstore.append_entry(_entry("good"), store_path=self.ledger, ts=FIXED_TS)
        # Simulate a crash mid-write: a partial last line with no trailing newline.
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write('{"record":"entry","half')
        rid = memstore.append_entry(_entry("after"), store_path=self.ledger,
                                    ts=FIXED_TS)
        recs = memstore.load_ledger(self.ledger)
        # The new entry is recoverable (not fused into the torn fragment).
        self.assertIn(rid, [r.get("id") for r in recs])
        landed = [r for r in recs if r.get("id") == rid]
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0]["text"], "after")
        # The torn fragment remains exactly one flagged line for the verifier.
        ok, fails = memstore.verify_ledger(self.ledger)
        self.assertFalse(ok)
        self.assertEqual(sum("unparseable" in f for f in fails), 1, fails)


class FlagBeforeEntry(unittest.TestCase):
    """Regression: a flag landing before its target entry must stay terminal, not
    be silently dropped so later confirms promote the entry. Finding 4."""

    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_fbe_")) / "l.jsonl"
        self.state = self.ledger.parent / "state.local.json"

    def test_flag_before_entry_is_terminal(self):
        e = _entry("flag me first")
        # The entry id is content-derivable before the append.
        predicted = memstore._body_sha(memstore._normalize_entry(e))[:16]
        memstore.append_flag(predicted, ["cerberus_egress_fail"],
                             store_path=self.ledger)
        eid = memstore.append_entry(e, store_path=self.ledger)
        self.assertEqual(eid, predicted)
        for _ in range(memstore.MEM_CONFIRM_THRESHOLD):
            memstore.append_confirm(eid, store_path=self.ledger)
        st = memstore.fold_state(memstore.load_ledger(self.ledger),
                                 state_path=self.state)
        self.assertEqual(st[eid]["tier"], "flagged")
        self.assertEqual(st[eid]["flags"], ["cerberus_egress_fail"])

    def test_orphan_flag_materialises_flagged_placeholder(self):
        memstore.append_flag("deadbeefdeadbeef", ["verify_failed"],
                             store_path=self.ledger)
        st = memstore.fold_state(memstore.load_ledger(self.ledger),
                                 state_path=self.state)
        # The flag is recorded (not lost) even though no entry ever appeared.
        self.assertEqual(st["deadbeefdeadbeef"]["tier"], "flagged")


class UnknownFieldRejected(unittest.TestCase):
    """Regression: an off-envelope caller field must fail LOUD, not be silently
    dropped (which lets two distinct inputs dedupe as one). Finding 5."""

    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_unk_")) / "l.jsonl"

    def test_unknown_top_level_field_raises(self):
        with self.assertRaises(ValueError):
            memstore.append_entry(
                {"layer": "episodic", "kind": "landed_edit", "text": "x",
                 "severity": "high"}, store_path=self.ledger)

    def test_unknown_provenance_field_raises(self):
        with self.assertRaises(ValueError):
            memstore.append_entry(
                {"layer": "episodic", "kind": "landed_edit", "text": "x",
                 "provenance": {"source": "s", "model": "A"}},
                store_path=self.ledger)

    def test_trust_key_still_accepted_and_forced_quarantine(self):
        # trust is a KNOWN (accepted-then-forced) key, not an unknown one.
        i = memstore.append_entry(
            {"layer": "episodic", "kind": "landed_edit", "text": "y",
             "trust": {"minted_tier": "primary"}}, store_path=self.ledger)
        rec = memstore.load_ledger(self.ledger)[0]
        self.assertEqual(rec["trust"]["minted_tier"], "quarantine")
        self.assertEqual(rec["id"], i)


class AppendIndexCache(unittest.TestCase):
    """Regression: the per-store append index must stay correct -- dedup and chain
    linkage survive, and a file changed underneath us forces a reload. Finding 6."""

    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp(prefix="memstore_cache_")) / "l.jsonl"

    def test_dedup_and_tail_tracked_through_cache(self):
        i1 = memstore.append_entry(_entry("one"), store_path=self.ledger)
        memstore.append_entry(_entry("two"), store_path=self.ledger)
        # A duplicate body still dedupes to the first id via the cached set.
        again = memstore.append_entry(_entry("one"), store_path=self.ledger)
        self.assertEqual(i1, again)
        recs = memstore.load_ledger(self.ledger)
        self.assertEqual(len(recs), 2)
        key = str(Path(self.ledger).resolve())
        idx = memstore._APPEND_CACHE[key]
        self.assertEqual(idx["tail"], recs[-1]["entry_sha"])

    def test_external_change_invalidates_cache(self):
        for n in ("a", "b", "c", "d"):
            memstore.append_entry(_entry(n), store_path=self.ledger, ts=FIXED_TS)
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        # Simulate another process truncating the file (size changes -> reload).
        self.ledger.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
        memstore.append_entry(_entry("e"), store_path=self.ledger, ts=FIXED_TS)
        recs = memstore.load_ledger(self.ledger)
        self.assertEqual([r["text"] for r in recs], ["a", "b", "e"])
        # The new tail links to the truncated head, not the stale cached one.
        self.assertEqual(recs[2]["prev"], recs[1]["entry_sha"])
        ok, fails = memstore.verify_ledger(self.ledger)
        self.assertTrue(ok, fails)


if __name__ == "__main__":
    unittest.main()
