# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""S1 — C/C++ function naming, and the Type-3 hold-out that must accompany it.

C and C++ are the only supported grammars with no ``name`` field on a function:
the name sits at the bottom of a ``declarator`` chain, while the RETURN TYPE is
a plain ``type_identifier`` sitting as a direct child. The old generic scan
therefore returned the return type ("MyType foo(void)" -> "MyType"), which is
strictly worse than no name -- a fabricated identifier shared by every function
returning that type, and one the clone passes do NOT filter out.

Two things are asserted here, and the second is the load-bearing one:
  1. every C/C++ shape resolves to its real name, or honestly to "<anonymous>"
     where the grammar is genuinely ambiguous (never to a guess);
  2. naming those units does NOT switch on Type-3 for C/C++ -- five genuinely
     unrelated C functions must still produce ZERO near-clone clusters.

Skips cleanly when tree-sitter is absent (the C/C++ path needs it).
"""
import unittest

from daedalus.structcore import clones
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import extract_units, tree_sitter_available

C = spec_for("x.c")
CPP = spec_for("x.cpp")

# (label, source, expected_name). Expectations are the MEASURED output of the
# installed c/cpp grammars, not guesses.
CASES = [
    ("plain C",             C,   "int add(int a, int b) { return a + b; }", "add"),
    # The two that used to yield a fabricated return-type name:
    ("C user-type return",  C,   "MyType foo(void) { return t; }", "foo"),
    ("C++ user-type return", CPP, "MyClass makeThing(int n) { return MyClass(n); }", "makeThing"),
    # Wrapper declarators interposed between fn_def and the name:
    ("C pointer return",    C,   "static void *bar(void) { return 0; }", "bar"),
    ("C struct-ptr return", C,   "struct Point *make_point(int x) { return 0; }", "make_point"),
    ("C++ reference return", CPP, "std::string& Cfg::name() { return n_; }", "Cfg::name"),
    # Qualified / template / trailing-return / noexcept forms:
    ("C++ out-of-line",     CPP, "int Widget::compute(int x) const { return x; }", "Widget::compute"),
    ("C++ noexcept",        CPP, "void Foo::bar() noexcept { go(); }", "Foo::bar"),
    ("C++ trailing return", CPP, "auto compute(int x) -> int { return x; }", "compute"),
    ("C++ template fn",     CPP, "template<typename T> std::vector<T> Sorted(std::vector<T> v) { return v; }", "Sorted"),
    ("C++ template method", CPP, "template<typename T> T Box<T>::get() const { return v_; }", "Box<T>::get"),
    # Constructors/destructors: the name legitimately IS the type name.
    ("C++ ctor out-of-line", CPP, "Widget::Widget(int x) : x_(x) { }", "Widget::Widget"),
    ("C++ ctor in-class",   CPP, "struct S { S() { init(); } };", "S"),
    ("C++ dtor",            CPP, "Widget::~Widget() { cleanup(); }", "Widget::~Widget"),
    # Operators, including the operator_cast shape whose name node spans the
    # parameter list and cv-qualifiers ("operator bool() const").
    ("C++ operator==",      CPP, "bool operator==(const A& a, const A& b) { return true; }", "operator=="),
    ("C++ operator() qual", CPP, "int Fn::operator()(int a) const { return a; }", "Fn::operator()"),
    ("C++ operator() in-class", CPP, "struct F { int operator()(int a) { return a; } };", "operator()"),
    ("C++ operator bool qual", CPP, "Foo::operator bool() const { return ok_; }", "Foo::operator bool"),
    ("C++ operator bool in-class", CPP, "struct S { operator bool() const { return b_; } };", "operator bool"),
    # Genuinely ambiguous: a function RETURNING a function pointer nests a second
    # function_declarator, and which one is "the name" is undecidable. Under-report.
    ("C++ fn-pointer return", CPP, "int (*get_handler(int k))(void) { return 0; }", "<anonymous>"),
]

# Five hand-written C functions with nothing in common but C's syntax. In a
# C-minority pool these previously chained into ONE near-clone cluster at
# similarity 0.853 (pairwise overlaps 0.72-0.90) purely because the generic
# abstraction collapses C's type system to ID.
UNRELATED_C = '''
size_t json_escape(const char *in, char *out, size_t cap) {
    size_t n = 0;
    for (size_t i = 0; in[i] && n + 2 < cap; i++) {
        if (in[i] == '"' || in[i] == '\\\\') { out[n++] = '\\\\'; }
        out[n++] = in[i];
    }
    out[n] = 0;
    return n;
}
int cfg_parse_line(const char *line, char *key, char *val) {
    const char *eq = strchr(line, '=');
    if (!eq) { return -1; }
    size_t klen = (size_t)(eq - line);
    memcpy(key, line, klen);
    key[klen] = 0;
    strcpy(val, eq + 1);
    return 0;
}
unsigned short crc16_update(unsigned short crc, unsigned char byte) {
    crc ^= (unsigned short)byte << 8;
    for (int i = 0; i < 8; i++) {
        if (crc & 0x8000) { crc = (crc << 1) ^ 0x1021; }
        else { crc = crc << 1; }
    }
    return crc;
}
void motor_set_duty(int channel, int duty) {
    if (duty < 0) { duty = 0; }
    if (duty > 1000) { duty = 1000; }
    TIM1->CCR[channel] = (unsigned)duty;
    TIM1->EGR |= 1u;
    motor_state[channel] = duty;
}
float sensor_read_temp(int idx) {
    int raw = adc_sample(idx);
    if (raw < 0) { return -100.0f; }
    float mv = (float)raw * 3300.0f / 4095.0f;
    float c = (mv - 500.0f) / 10.0f;
    sensor_last[idx] = c;
    return c;
}
'''

PY_FILLER = "".join(
    "def py_fn_%d(a, b):\n"
    "    t = 0\n"
    "    for i in range(a):\n"
    "        t += i * b\n"
    "        if t > %d: t -= 1\n"
    "    return t\n\n" % (k, k)
    for k in range(60)
)


@unittest.skipUnless(tree_sitter_available(), "tree-sitter not installed")
class CNameTests(unittest.TestCase):

    def test_c_cpp_function_names_resolve(self):
        for label, spec, src, expected in CASES:
            with self.subTest(label):
                units = extract_units("m", src, spec)
                self.assertTrue(units, "no unit extracted for %s" % label)
                self.assertEqual(units[0].name, expected)

    def test_return_type_is_never_used_as_a_name(self):
        """The specific regression: a fabricated name is worse than none, because
        it is NOT filtered downstream the way "<anonymous>" is. Constructors are
        excluded -- their name legitimately equals the type name."""
        for src, forbidden in (("MyType foo(void) { return t; }", "MyType"),
                               ("MyClass makeThing(int n) { return MyClass(n); }", "MyClass"),
                               ("template<typename T> T ident(T v) { return v; }", "T")):
            with self.subTest(src):
                spec = C if forbidden == "MyType" else CPP
                self.assertNotEqual(extract_units("m", src, spec)[0].name, forbidden)


@unittest.skipUnless(tree_sitter_available(), "tree-sitter not installed")
class CType3HoldOutTests(unittest.TestCase):
    """Naming C units must not silently enable Type-3 for them."""

    def _units(self):
        return extract_units("app/misc.c", UNRELATED_C, C)

    def test_units_are_named_now(self):
        self.assertEqual(
            sorted(u.name for u in self._units()),
            ["cfg_parse_line", "crc16_update", "json_escape",
             "motor_set_duty", "sensor_read_temp"])

    def test_unrelated_c_functions_form_no_near_clusters(self):
        units = self._units()
        self.assertEqual(clones.near_clusters(units, {"c": C}, None), [])

    def test_unrelated_c_functions_form_no_near_clusters_in_python_majority(self):
        """The regime that actually fabricated: C as a MINORITY of the pool, where
        ubiq_cut is computed over mostly-Python units so C's tokens look rare."""
        py = extract_units("app/p.py", PY_FILLER, spec_for("x.py"))
        pool = self._units() + py
        got = clones.near_clusters(pool, {"c": C, "python": spec_for("x.py")}, None)
        self.assertEqual(
            [c for c in got if any(n in c["names"] for n in
                                   ("json_escape", "crc16_update", "motor_set_duty"))],
            [])

    def test_exclusion_is_declared(self):
        self.assertIn("c", clones.TYPE3_EXCLUDED_LANGUAGES)
        self.assertIn("cpp", clones.TYPE3_EXCLUDED_LANGUAGES)


if __name__ == "__main__":
    unittest.main()
