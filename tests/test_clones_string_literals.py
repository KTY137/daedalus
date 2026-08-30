# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Comment stripping must respect string literals.

A comment marker inside a string is NOT a comment. Getting this wrong does not
merely lose precision -- it deletes real code and makes different functions hash
identically, i.e. it FABRICATES exact clones. Reporting code as duplicated when
it is not is this engine's worst failure mode, so every case here is a
correctness test, not a quality one.

Both fabrications below were confirmed against the pre-fix implementation.
"""
import unittest

from daedalus.structcore.clones import (
    _strip_comments_generic, abstract_fingerprint, fingerprint,
)
from daedalus.structcore.languages import spec_for

CPP = spec_for("x.cpp")
RUST = spec_for("x.rs")
GO = spec_for("x.go")
PY = spec_for("x.py")


class LineCommentInStringTests(unittest.TestCase):
    def test_slashes_in_string_do_not_truncate_the_line(self):
        """The HV case: two different bias voltages must not be one clone.

        'SOUR:VOLT' is a SCPI instrument command, and project_tct's egress
        policy lists `\\bsour:[a-z]` as denied content -- so this is exactly the
        code path where merging two voltages would be worst.
        """
        a = 'void arm(void){\n    send("SOUR:VOLT // 500");\n}'
        b = 'void arm(void){\n    send("SOUR:VOLT // 50");\n}'
        self.assertNotEqual(fingerprint(a, CPP), fingerprint(b, CPP))
        self.assertIn("500", _strip_comments_generic(a, CPP))

    def test_url_in_string_survives(self):
        a = 'int f(void){\n    const char *u = "https://api/arm";\n    return 1;\n}'
        b = 'int f(void){\n    const char *u = "https://api/disarm";\n    return 1;\n}'
        self.assertNotEqual(fingerprint(a, CPP), fingerprint(b, CPP))

    def test_real_line_comment_is_still_stripped(self):
        src = 'void f(void){\n    int a = 1; // set a\n    return a;\n}'
        out = _strip_comments_generic(src, CPP)
        self.assertNotIn("set a", out)
        self.assertIn("int a = 1;", out)


class BlockCommentInStringTests(unittest.TestCase):
    def test_block_open_in_string_does_not_delete_the_body(self):
        """Worst case: re.S swallowed to the next '*/', deleting whole bodies."""
        a = ('void f(void){\n    const char *s = "/*";\n'
             '    critical_write(1);\n    const char *e = "*/";\n}')
        b = ('void f(void){\n    const char *s = "/*";\n'
             '    critical_write(999);\n    const char *e = "*/";\n}')
        self.assertNotEqual(fingerprint(a, CPP), fingerprint(b, CPP))
        self.assertIn("critical_write(1)", _strip_comments_generic(a, CPP))

    def test_real_block_comment_is_still_stripped(self):
        src = 'void f(void){\n    /* block\n       comment */\n    return 1;\n}'
        out = _strip_comments_generic(src, CPP)
        self.assertNotIn("block", out)
        self.assertIn("return 1;", out)

    def test_unterminated_block_comment_does_not_crash(self):
        self.assertIsInstance(_strip_comments_generic("int f(){ /* oops", CPP), str)


class PerLanguageQuotingTests(unittest.TestCase):
    def test_rust_lifetimes_are_not_treated_as_string_openers(self):
        """`'a` is a lifetime. Consuming to the next `'` would eat the code."""
        src = "fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {\n    // pick\n    x\n}"
        out = _strip_comments_generic(src, RUST)
        self.assertIn("&'a str", out)
        self.assertNotIn("pick", out)

    def test_go_raw_string_backtick(self):
        a = 'func f() string {\n\treturn `a // b`\n}'
        b = 'func f() string {\n\treturn `a // c`\n}'
        self.assertNotEqual(fingerprint(a, GO), fingerprint(b, GO))

    def test_escaped_quote_does_not_end_the_literal(self):
        a = 'void f(void){\n    p("say \\" // 1");\n}'
        b = 'void f(void){\n    p("say \\" // 2");\n}'
        self.assertNotEqual(fingerprint(a, CPP), fingerprint(b, CPP))

    def test_unterminated_quote_degrades_one_line_not_the_file(self):
        src = 'void f(void){\n    char c = \';\n    important_call();\n}'
        self.assertIn("important_call", _strip_comments_generic(src, CPP))


class AbstractPathTests(unittest.TestCase):
    """The Type-2/Type-3 path shares this substrate, so it inherits the fix."""

    def test_abstract_fingerprint_also_distinguishes_them(self):
        a = 'void arm(void){\n    send("V // 500");\n    ramp(1);\n}'
        b = 'void arm(void){\n    send("V // 500");\n    ramp(1);\n    extra_step();\n}'
        self.assertNotEqual(abstract_fingerprint(a, CPP), abstract_fingerprint(b, CPP))

    def test_python_hash_in_string_is_not_a_comment(self):
        a = 'def f():\n    return "chan #1"\n'
        b = 'def f():\n    return "chan #2"\n'
        self.assertNotEqual(fingerprint(a, PY), fingerprint(b, PY))


if __name__ == "__main__":
    unittest.main()
