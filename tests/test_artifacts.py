# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The data layer's contract: refuse to guess, and never confuse
"we could not look" with "there is nothing there".

The chain these tests protect is the one a physics analysis actually is:
paper.tex -> figure -> script -> .root -> config. Every link is a path spelled
inside a string literal, so every link is a place to fabricate an edge.
"""
from __future__ import annotations

import json
import unittest

from daedalus.structcore import artifacts as art


class LiteralExtraction(unittest.TestCase):
    def test_latex_input_and_figures(self):
        tex = (r"\input{sections/method}" "\n"
               r"\includegraphics[width=0.8\textwidth]{fig/eff_vs_v.pdf}" "\n"
               r"\bibliography{refs}" "\n")
        lits = art.extract_literals("paper.tex", tex)
        got = {(l.relation, l.raw) for l in lits}
        self.assertIn(("includes", "sections/method"), got)
        self.assertIn(("figures", "fig/eff_vs_v.pdf"), got)
        self.assertIn(("reads", "refs"), got)

    def test_python_reader_and_writer_calls_carry_direction(self):
        py = ('import uproot\n'
              'f = uproot.open("data/selected.root")\n'
              'df.to_csv("out/table.csv")\n')
        rel = {(l.relation, l.raw) for l in art.extract_literals("plot.py", py)}
        self.assertIn(("reads", "data/selected.root"), rel)
        self.assertIn(("writes", "out/table.csv"), rel)

    def test_cpp_root_calls(self):
        cpp = ('  TFile::Open("raw/run0421.root");\n'
               '  auto* out = new TFile("selected.root", "RECREATE");\n')
        rel = {(l.relation, l.raw) for l in art.extract_literals("analysis.cpp", cpp)}
        self.assertIn(("reads", "raw/run0421.root"), rel)
        self.assertIn(("writes", "selected.root"), rel)

    def test_a_language_with_no_rules_yields_nothing_rather_than_guessing(self):
        self.assertEqual(art.extract_literals("notes.rst", "some/path.csv"), [])

    def test_extraction_is_deterministic(self):
        tex = r"\input{a}\input{b}\includegraphics{c.pdf}"
        a = [l.to_dict() for l in art.extract_literals("p.tex", tex)]
        b = [l.to_dict() for l in art.extract_literals("p.tex", tex)]
        self.assertEqual(a, b)


class RefuseToGuess(unittest.TestCase):
    def _lits(self, rel, text):
        return {rel: art.extract_literals(rel, text)}

    def test_an_unresolved_literal_is_counted_never_bound_to_a_near_match(self):
        lits = self._lits("paper.tex", r"\includegraphics{fig/efficiency.pdf}")
        rep = art.resolve_literals(lits, {"fig/efficiency_v2.pdf"})
        self.assertEqual(rep.edges, [])
        self.assertEqual(len(rep.unresolved), 1)
        self.assertEqual(rep.unresolved[0]["raw"], "fig/efficiency.pdf")

    def test_an_ambiguous_literal_produces_no_edge_and_is_counted(self):
        """LaTeX omits the extension. Two candidates means we do not know which,
        and picking the first would be a stably reproduced fabrication."""
        lits = self._lits("paper.tex", r"\includegraphics{fig/eff}")
        rep = art.resolve_literals(lits, {"fig/eff.pdf", "fig/eff.png"})
        self.assertEqual(rep.edges, [])
        self.assertEqual(len(rep.ambiguous), 1)
        self.assertEqual(sorted(rep.ambiguous[0]["candidates"]), ["fig/eff.pdf", "fig/eff.png"])

    def test_a_single_extension_candidate_resolves(self):
        lits = self._lits("paper.tex", r"\includegraphics{fig/eff}")
        rep = art.resolve_literals(lits, {"fig/eff.pdf"})
        self.assertEqual(len(rep.edges), 1)
        self.assertEqual(rep.edges[0].target, art.artifact_node_id("fig/eff.pdf"))

    def test_an_off_tree_url_is_an_attribute_not_an_edge(self):
        lits = self._lits("paper.tex", r"\includegraphics{https://example.org/x.pdf}")
        rep = art.resolve_literals(lits, {"fig/x.pdf"})
        self.assertEqual(rep.edges, [])
        self.assertEqual(len(rep.external), 1)

    def test_edges_carry_their_provenance(self):
        lits = self._lits("plot.py", 'open("out/table.csv")')
        rep = art.resolve_literals(lits, {"out/table.csv"})
        self.assertEqual(rep.edges[0].attributes["provenance"], "declared")


class SchemaReading(unittest.TestCase):
    def test_csv_header_becomes_columns(self):
        s = art.read_schema("d.csv", b"run,voltage,current\n1,2.0,3.0\n")
        self.assertTrue(s.known)
        self.assertEqual([c.name for c in s.columns], ["run", "voltage", "current"])

    def test_json_object_keys_with_types(self):
        s = art.read_schema("c.json", json.dumps({"host": "x", "port": 1}).encode())
        self.assertTrue(s.known)
        self.assertEqual({c.name: c.dtype for c in s.columns},
                         {"host": "str", "port": "int"})

    def test_npy_header_is_parsed_with_stdlib(self):
        try:
            import io

            import numpy as np
        except ImportError:  # pragma: no cover
            self.skipTest("numpy not installed")
        buf = io.BytesIO()
        np.save(buf, np.zeros(4, dtype=[("voltage", "f4"), ("run", "i4")]))
        s = art.read_schema("a.npy", buf.getvalue())
        self.assertTrue(s.known)
        self.assertEqual([c.name for c in s.columns], ["voltage", "run"])

    def test_an_unsupported_format_is_NOT_an_empty_schema(self):
        """The whole point: 'we could not look' must not render as 'no columns'."""
        s = art.read_schema("t.root", b"root\x00binary")
        self.assertFalse(s.known)
        self.assertEqual(s.status, art.NOT_SUPPORTED)
        self.assertEqual(s.columns, ())
        self.assertIn("uproot", s.detail, "it must name the reader that would help")

    def test_an_unreadable_file_is_unreadable_not_clean(self):
        s = art.read_schema("d.csv", b"\xff\xfe\x00bad")
        self.assertFalse(s.known)
        self.assertEqual(s.status, art.UNREADABLE)

    def test_a_truncated_read_is_flagged_on_the_result(self):
        s = art.read_schema("d.csv", b"a,b,c\n1,2,3\n", truncated=True)
        self.assertTrue(s.truncated)
        self.assertIn("truncated", s.detail)


class TheJoin(unittest.TestCase):
    def test_a_declared_field_missing_from_the_artifact_is_the_finding(self):
        s = art.read_schema("d.csv", b"run,voltage,current\n")
        cmp = art.compare_schema(s, ["run", "voltage", "temperature"],
                                 declared_from="analysis.py")
        self.assertFalse(cmp.agrees)
        self.assertEqual(cmp.missing_in_artifact, ("temperature",))

    def test_it_refuses_to_compare_against_a_schema_it_never_read(self):
        s = art.read_schema("t.root", b"binary")
        cmp = art.compare_schema(s, ["voltage", "current"])
        self.assertFalse(cmp.comparable)
        self.assertEqual(cmp.missing_in_artifact, (),
                         "an unread schema must not report every field as missing")


class Chain(unittest.TestCase):
    def _chain_repo(self):
        files = {
            "paper.tex": r"\includegraphics{fig/eff.pdf}",
            "plot.py": 'f = uproot.open("selected.root")\nplt.savefig("fig/eff.pdf")\n',
            "analysis.cpp": '  TFile::Open("raw/run.root");\n'
                            '  auto* o = new TFile("selected.root", "RECREATE");\n',
        }
        known = set(files) | {"fig/eff.pdf", "selected.root", "raw/run.root"}
        lits = {rel: art.extract_literals(rel, text) for rel, text in files.items()}
        return art.resolve_literals(lits, known)

    def test_the_paper_to_data_chain_walks_backwards(self):
        rep = self._chain_repo()
        chain = art.chain_from(rep, "fig/eff.pdf")
        producers = [p for hop in chain for p in hop.get("produced_by", [])]
        self.assertIn("paper.tex", producers + [])  # the figure edge comes from the paper
        self.assertTrue(any("plot.py" in hop.get("produced_by", []) for hop in chain),
                        f"plot.py should appear as a producer: {chain}")

    def test_the_walk_is_bounded_and_says_when_it_stopped(self):
        rep = self._chain_repo()
        chain = art.chain_from(rep, "fig/eff.pdf", max_hops=1)
        self.assertTrue(chain)
        # either it finished within the bound, or it says it did not
        if len(chain) > 1:
            self.assertTrue(chain[-1].get("truncated"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
