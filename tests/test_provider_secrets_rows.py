"""A provider row declares SECRETS when, and only when, it reads a credential.

WHAT IS BEING GUARDED
---------------------
Giga plan Phase 3 asks for ``Effect.SECRETS`` on the provider rows that handle
API credentials, and its own round-2 note records why a row count is the wrong
check: *"a row count measures registry labels, not whether credential-bearing
execution is contained -- adding four JSON rows satisfied the round-1 criterion
with no behaviour change"*. So this file does not count rows. It derives, from
the source each row's ``target`` names, whether a credential is actually read,
and asserts the label agrees IN BOTH DIRECTIONS:

* a row that reads a credential must declare SECRETS (no silent handling);
* a row that reads none must not declare it (no empty label).

The second direction is the one that makes the first worth having. Without it
the honest way to "pass" is to paint SECRETS on every provider row, and the
registry would then say nothing at all.

WHAT THE DERIVATION MEASURED (2026-08-22, at this head)
-------------------------------------------------------
Exactly ONE provider module reads an API credential from the environment:
``daedalus/providers/deepseek.py:178`` (``DEEPSEEK_API_KEY``), reached from
``DeepSeekProvider.run`` through ``self.api_key``. ``claude_cli`` and
``codex_cli`` read none -- both authenticate through the vendor CLI's own login
(``providers/__init__.py`` marks them ``requires_key=False``) and spawn it with
no ``env=`` argument -- and ``ollama`` is a localhost host/model/context-window
reader with no credential at all. Inheriting an ambient environment into a
spawned child is NOT a credential read; if it counted, SECRETS would become a
synonym for PROCESS_SPAWN and stop carrying information.

NO PYTEST FIXTURES: callable directly from a plain ``python -c`` probe as well
as by the suite.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daedalus.spine.effect_boundary import ENTRYPOINTS  # noqa: E402

#: Environment names that carry a secret. Deliberately narrow: OLLAMA_HOST,
#: OLLAMA_MODEL, OLLAMA_NUM_CTX, OLLAMA_KEEP_ALIVE and CODEX_MODEL are
#: configuration, and a rule that called them credentials would launder the
#: distinction this test exists to keep.
CREDENTIAL_NAME = re.compile(r"(API_KEY|_KEY$|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)


# --------------------------------------------------------------------------- #
# the derivation                                                               #
# --------------------------------------------------------------------------- #
def _credential_env_reads(node):
    """Literal credential-shaped env names read anywhere under ``node``."""

    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Constant):
            if ast.unparse(child.value).endswith("environ"):
                name = str(child.slice.value)
                if CREDENTIAL_NAME.search(name):
                    found.append((name, child.lineno))
        if isinstance(child, ast.Call) and child.args:
            func = ast.unparse(child.func)
            if func.endswith("environ.get") or func.endswith("getenv"):
                arg = child.args[0]
                if isinstance(arg, ast.Constant) and CREDENTIAL_NAME.search(str(arg.value)):
                    found.append((str(arg.value), child.lineno))
    return found


def _functions(scope):
    return {n.name: n for n in scope.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _credential_attrs(cls):
    """``self.x`` names assigned from a credential env read, e.g. ``api_key``.

    The value outlives the assignment, so a method that reads the ATTRIBUTE is
    handling the credential even though the environment read is in __init__.
    """

    attrs = set()
    for node in ast.walk(cls):
        if isinstance(node, ast.Assign) and _credential_env_reads(node.value):
            for target in node.targets:
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    attrs.add(target.attr)
    return attrs


def reaches_credential(target: str):
    """Does the function this registry row names reach a credential?

    Reachability, not module membership. ``DeepSeekProvider.rollback`` lives in
    the same module -- and on the same object -- as the API key and touches
    neither, so a module-granular rule would demand SECRETS on a door that only
    restores files. The walk follows ``self.method()`` calls inside the class
    and bare calls to module-level functions, and deliberately does NOT follow
    ``__init__``: constructing an object is not using what it holds.

    Returns ``(bool, evidence)`` -- evidence is a list of strings, so a failure
    names the line instead of the verdict.
    """

    module, _, qual = target.partition(":")
    path = ROOT / (module.replace(".", "/") + ".py")
    if not path.exists():
        path = ROOT / module.replace(".", "/") / "__init__.py"
    if not path.exists():
        return False, [f"{module}: no source on disk"]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT).as_posix()

    module_fns = _functions(tree)
    cls_name, _, fn_name = qual.rpartition(".")
    cls = None
    if cls_name:
        cls = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.ClassDef) and n.name == cls_name), None)
    methods = _functions(cls) if cls is not None else {}
    cred_attrs = _credential_attrs(cls) if cls is not None else set()

    start = methods.get(fn_name) or module_fns.get(fn_name)
    if start is None:
        return False, [f"{rel}: {qual} not found"]

    seen, frontier, evidence = set(), [start], []
    while frontier:
        fn = frontier.pop()
        if id(fn) in seen:
            continue
        seen.add(id(fn))
        for name, line in _credential_env_reads(fn):
            evidence.append(f"{rel}:{line} reads {name}")
        for node in ast.walk(fn):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self" and node.attr in cred_attrs):
                evidence.append(f"{rel}:{node.lineno} uses self.{node.attr}")
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                        and func.value.id == "self" and func.attr in methods
                        and func.attr != "__init__"):
                    frontier.append(methods[func.attr])
                elif isinstance(func, ast.Name) and func.id in module_fns:
                    frontier.append(module_fns[func.id])
    return bool(evidence), evidence


def _rows(prefix):
    return [spec for spec in ENTRYPOINTS if spec.id.startswith(prefix)]


def _declares_secrets(spec):
    return any(effect.value == "secrets" for effect in spec.effects)


# --------------------------------------------------------------------------- #
# the two directions                                                           #
# --------------------------------------------------------------------------- #
def test_every_provider_row_that_reads_a_credential_declares_secrets():
    missing = []
    for spec in _rows("provider."):
        reads, evidence = reaches_credential(spec.target)
        if reads and not _declares_secrets(spec):
            missing.append(f"{spec.id} -> {evidence}")
    assert not missing, "credential read without a SECRETS declaration:\n" + "\n".join(missing)


def test_no_provider_row_declares_secrets_without_a_credential_read():
    """The label must cost something. Four painted-on rows are the measured
    no-op this plan's own round-2 review recorded."""

    empty = []
    for spec in _rows("provider."):
        reads, _evidence = reaches_credential(spec.target)
        if _declares_secrets(spec) and not reads:
            empty.append(f"{spec.id} ({spec.target})")
    assert not empty, "SECRETS declared with no credential read:\n" + "\n".join(empty)


def test_the_derivation_is_not_vacuous():
    """A rule that finds nothing makes both tests above pass by saying nothing.

    So pin the ground truth measured at this head: deepseek's run door reads
    the key, and its rollback door -- same module, same object -- does not.
    """

    by_id = {spec.id: spec for spec in ENTRYPOINTS}
    reads, evidence = reaches_credential(by_id["provider.deepseek"].target)
    assert reads and any("DEEPSEEK_API_KEY" in e or "self.api_key" in e for e in evidence), evidence
    assert _declares_secrets(by_id["provider.deepseek"])

    rollback = by_id["provider.deepseek.rollback"]
    assert reaches_credential(rollback.target) == (False, [])
    assert not _declares_secrets(rollback)


def test_the_cli_providers_are_measured_not_assumed():
    """claude_cli and codex_cli authenticate through the vendor CLI's own login
    and read no credential here. This test exists so that if either one ever
    starts reading a key, the forward direction above fires instead of the
    registry quietly going stale."""

    by_id = {spec.id: spec for spec in ENTRYPOINTS}
    for row in ("provider.claude", "provider.codex", "provider.ollama"):
        reads, evidence = reaches_credential(by_id[row].target)
        assert not reads, f"{row} now reads a credential: {evidence}"
        assert not _declares_secrets(by_id[row])


def test_the_doctor_door_declares_secrets_because_it_reads_the_key_itself():
    """Not a provider row, and that is the point: the effect follows the read,
    not the surface. ``daedalus doctor`` pulls DEEPSEEK_API_KEY out of the
    environment inside its own guarded door to report whether it is set."""

    doctor = next(spec for spec in ENTRYPOINTS if spec.id == "cli.doctor")
    reads, evidence = reaches_credential(doctor.target)
    assert reads, "the doctor door no longer reads a credential; drop the label"
    assert any("DEEPSEEK_API_KEY" in item for item in evidence), evidence
    assert _declares_secrets(doctor)


def test_the_rule_itself_sees_a_planted_credential_read():
    """Falsify the analyzer without the tree: if this passed on a source that
    plainly reads a key, every verdict above would be an artifact of the walk
    rather than of the code."""

    tree = ast.parse(
        "import os\n"
        "class P:\n"
        "    def __init__(self):\n"
        "        self.api_key = os.environ.get('VENDOR_API_KEY', '')\n"
        "        self.host = os.environ.get('VENDOR_HOST', '')\n"
        "    def run(self):\n"
        "        return self._send(self.api_key)\n"
        "    def rollback(self):\n"
        "        return self.host\n"
        "    def _send(self, key):\n"
        "        return key\n"
    )
    cls = tree.body[1]
    attrs = _credential_attrs(cls)
    assert attrs == {"api_key"}, attrs           # host is configuration, not a secret
    methods = _functions(cls)
    assert _credential_env_reads(methods["__init__"])
    assert not _credential_env_reads(methods["rollback"])


if __name__ == "__main__":  # probe entry
    for _name, _fn in sorted(dict(globals()).items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
