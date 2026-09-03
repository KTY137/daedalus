"""Mechanical inventory of every switch that can turn a built feature off.

A hand-written feature inventory goes stale the hour it is written; this half
of the architecture artifact is regenerated on every run, so it cannot. What it
answers is deliberately narrow and fully mechanical:

* which environment variables the package reads, where, and with what DEFAULT;
* which public entry points take a boolean parameter that defaults to off;
* which config keys in ``projects/*.json`` carry an off-shaped value;
* which names the docs promise and the code never reads (and the reverse).

The classification -- not the listing -- is the product. A feature is DARK when
its switch defaults to off *and* nothing in the surrounding code supplies a
fallback: in normal operation that code path never runs and no report mentions
it. That is how 51 dark features hid behind an inventory that knew about 2.

WHAT THIS CANNOT SEE (stated so the artifact is not mistaken for complete):
env names assembled at runtime are listed in ``dynamic_reads`` rather than
guessed at; only module-level ``NAME = "LITERAL"`` constants are resolved; and
"documented" means the token appears in a doc under an env-shaped form, not
that the prose around it is true.
"""
from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA = "daedalus-switch-report/1"

# Directories that are never package source: build output, caches, vendored
# trees, run artifacts, and the eval corpora (fixtures are data that happens to
# parse as Python -- scanning them would invent switches that do not exist).
_SKIP_DIRS = frozenset({
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "venv",
    "__pycache__", "node_modules", "build", "dist", "site-packages",
    "runs", "inbox", "outbox", "tests", "fixtures", "apps", "structcore-rs",
    "vscode-agent-env", ".claude", "egg-info", "daedalus.egg-info",
    # Corpora are evidence, not source: experiments/forest_v2/*/corpus carries
    # a DELIBERATELY unparseable fixture, and sweeping it turned the whole
    # analysis red in every clean clone (MEASURED 2026-08-24, B6 baseline).
    # Same category the self-registration names for daedalus/eval/fixtures.
    "corpus",
})

# Platform variables the OS owns. They are read, but they are not Daedalus
# switches and marking them dark would bury the ones that are.
_PLATFORM_ENV = frozenset({
    "APPDATA", "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA",
    "PATH", "PATHEXT", "PROCESSOR_IDENTIFIER", "PROGRAMFILES", "PYTHONPATH",
    "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "USER", "USERDOMAIN", "USERNAME",
    "USERPROFILE", "VIRTUAL_ENV",
    "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
})
# ``USER``, ``USERDOMAIN`` and ``PROCESSOR_IDENTIFIER`` joined the set on
# 2026-09-03. It already held ``USERNAME`` and ``USERPROFILE``; these are the
# same category of account-and-host identity and were simply not encountered
# when the set was written, so the gate reported three OS variables as
# undocumented Daedalus switches -- the exact burying the comment above says
# this set exists to prevent. Documenting them instead would have traded a
# ``code-only`` row for a ``doc-only`` one: a name in the strict operator form
# that no Daedalus module owns reads as "docs tell an operator to set it; no
# module reads it". The scope boundary is the right lever, stated once here.

_SECRET_TOKENS = frozenset({"KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "APIKEY"})
_URL_TOKENS = frozenset({"HOST", "URL", "ENDPOINT", "BASE"})
_PATH_TOKENS = frozenset({"DIR", "PATH", "ROOT", "DB", "FILE", "HOME", "SDK", "STORE"})
_NUMBER_TOKENS = frozenset({
    "TOKENS", "CTX", "WORKERS", "PARALLEL", "COUNT", "LIMIT", "MAX", "MIN",
    "THRESHOLD", "PORT", "RETRIES", "TIMEOUT", "SECONDS", "GIB", "GB", "MB",
    "SIZE", "BUDGET", "DEPTH",
})
_FLAG_TOKENS = frozenset({
    "ENABLE", "ENABLED", "DEBUG", "VERBOSE", "DISABLE", "DISABLED", "OFF",
    "ON", "DRY", "FORCE", "STRICT", "AUTO",
})
# Tokens that invert a switch: the variable turns something OFF, so its unset
# default leaves the feature ON. Never dark.
_INVERTING_TOKENS = frozenset({"NO", "DISABLE", "DISABLED", "SKIP", "WITHOUT", "OFF"})

# A default that reads as "not configured" once coerced.
_OFF_LITERALS = frozenset({"", "0", "0.0", "false", "no", "off", "none"})

_GATE_PARAMS = frozenset({
    "enable", "enabled", "allow", "allowed", "auto", "include", "includes",
    "use", "using", "with", "writable", "write", "writes", "probe", "persist",
    "live", "stream", "streaming", "apply", "verify", "deep", "expand", "emit",
    "publish", "record", "annotate", "explain", "trace", "follow", "resolve",
})
# Parameters whose False default is a safety posture, not a hidden feature.
_SAFETY_PARAMS = frozenset({
    "dry", "force", "overwrite", "quiet", "clobber", "interactive", "reset",
    "delete", "destructive", "unsafe", "insecure", "danger", "purge", "prune",
})

_ENV_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
# A token only counts as documentation of an environment variable when it is
# written the way an operator would set it. Without this filter every
# SCREAMING_CASE doc *filename* becomes a phantom switch. Names the code
# provably reads are exempt (see `_augment_documented`) -- those cannot be
# phantoms, so a bare mention is documentation enough.
_DOC_ENV_FORMS = (
    re.compile(r"(?:^|[^A-Za-z0-9_])(?P<name>[A-Z][A-Z0-9_]+)\s*="),
    re.compile(r"(?i:set|setx|export|\$env:)\s*:?\s*[`'\"]?(?P<name>[A-Z][A-Z0-9_]+)"),
    re.compile(r"(?i:environment variable|env var)[^\n]{0,40}?(?P<name>[A-Z][A-Z0-9_]{3,})"),
)

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class EnvSite:
    """One physical read of one environment variable."""

    name: str
    module: str
    line: int
    via: str            # environ.get | environ[] | getenv | registry
    default: str        # source text of the default expression ("None" when absent)
    default_literal: str | None   # resolved constant, None when non-literal
    required: bool      # subscript form: unset raises
    kind: str           # flag|number|path|url|secret|string|platform
    polarity: str       # enable|disable
    state: str          # ON|OFF|REQUIRED
    dark: bool
    fallback: str       # evidence that unset still yields a usable value
    gates: str


@dataclass(frozen=True)
class EnvSwitch:
    """All reads of one variable, reconciled."""

    name: str
    kind: str
    polarity: str
    default: str
    state: str
    dark: bool
    documented: bool
    gates: str
    conflicting_defaults: tuple[str, ...]
    sites: tuple[EnvSite, ...]


@dataclass(frozen=True)
class ParamSwitch:
    """A public entry point whose boolean parameter defaults to off."""

    module: str
    line: int
    qualname: str
    param: str
    annotation: str
    default: str
    state: str
    dark: bool
    gates: str


@dataclass(frozen=True)
class ConfigSwitch:
    """A config key whose value is off-shaped."""

    source: str
    key: str
    value: str
    state: str
    read_in_code: bool
    dark: bool


@dataclass(frozen=True)
class DocDrift:
    """A name the docs and the code disagree about."""

    kind: str           # documented_never_read | read_never_documented | name_mismatch
    documented: str
    read: str
    detail: str
    doc_sites: tuple[str, ...]
    code_sites: tuple[str, ...]


@dataclass(frozen=True)
class SwitchCounts:
    env_switches: int
    env_sites: int
    dark_env: int
    inverted_env: int
    conflicting_env: int
    param_switches: int
    dark_params: int
    config_switches: int
    dark_config: int
    drift: int
    name_mismatches: int
    dynamic_reads: int
    modules_scanned: int


@dataclass(frozen=True)
class SwitchReport:
    schema: str
    root: str
    counts: SwitchCounts
    env_switches: tuple[EnvSwitch, ...]
    param_switches: tuple[ParamSwitch, ...]
    config_switches: tuple[ConfigSwitch, ...]
    drift: tuple[DocDrift, ...]
    dynamic_reads: tuple[str, ...]
    unparsable: tuple[str, ...]

    def dark_env_switches(self) -> tuple[EnvSwitch, ...]:
        return tuple(s for s in self.env_switches if s.dark)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# source discovery
# --------------------------------------------------------------------------- #

def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_sources(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _iter_docs(root: Path) -> Iterator[Path]:
    for candidate in sorted(root.glob("*.md")):
        yield candidate
    for candidate in (root / ".env.example", root / ".env.template"):
        if candidate.is_file():
            yield candidate
    docs = root / "docs"
    if docs.is_dir():
        for dirpath, dirnames, filenames in os.walk(docs):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith((".md", ".txt")):
                    yield Path(dirpath) / name


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


# --------------------------------------------------------------------------- #
# ast helpers
# --------------------------------------------------------------------------- #

def _tokens(name: str) -> list[str]:
    return [t for t in name.split("_") if t]


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    flat = _WS.sub(" ", text).strip()
    if not flat:
        return ""
    for stop in (". ", "; "):
        idx = flat.find(stop)
        if 0 < idx < 240:
            return flat[: idx + 1].strip()
    return flat[:240].strip()


@dataclass
class _Binding:
    """One ``from X import NAME`` visible at a point in a module."""

    alias: str
    origin: str            # repo-relative path of the defining module, "" if external
    original: str
    lineno: int
    owner: tuple[int, int] | None      # enclosing function span, None at module level


@dataclass
class _ModuleInfo:
    rel: str
    tree: ast.Module
    consts: dict[str, Any]
    bindings: list[_Binding]


def _module_constants(tree: ast.Module) -> dict[str, Any]:
    consts: dict[str, Any] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None or not isinstance(value, ast.Constant):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                consts[target.id] = value.value
    return consts


def _walk(node: ast.AST, parents: tuple[ast.AST, ...] = ()) -> Iterator[tuple[ast.AST, tuple[ast.AST, ...]]]:
    yield node, parents
    chain = parents + (node,)
    for child in ast.iter_child_nodes(node):
        yield from _walk(child, chain)


def _enclosing(parents: Sequence[ast.AST], types: tuple[type, ...]) -> Any:
    for anc in reversed(parents):
        if isinstance(anc, types):
            return anc
    return None


def _qualname(parents: Sequence[ast.AST], node: ast.AST) -> str:
    parts: list[str] = []
    for anc in parents:
        if isinstance(anc, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(anc.name)
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        parts.append(node.name)
    return ".".join(parts)


def _src(node: ast.AST | None) -> str:
    if node is None:
        return "None"
    try:
        return ast.unparse(node)
    except Exception:      # pragma: no cover -- unparse is total on parsed trees
        return "?"


# --------------------------------------------------------------------------- #
# env read extraction
# --------------------------------------------------------------------------- #

def _is_environ(node: ast.expr) -> bool:
    """`os.environ` or a bare `environ` imported from os."""
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return isinstance(node.value, ast.Name) and node.value.id == "os"
    return isinstance(node, ast.Name) and node.id == "environ"


def _env_read(node: ast.AST) -> tuple[str, ast.expr | None, str] | None:
    """Return (name_expr_source_marker, default_expr, via) for an env read."""
    if isinstance(node, ast.Subscript) and _is_environ(node.value):
        # Load context only: `os.environ[k] = v` sets a variable, it is not a
        # switch read, and counting it invents a required switch per write.
        if not isinstance(node.ctx, ast.Load):
            return None
        return ("[]", None, "environ[]")
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "get" and _is_environ(func.value):
        via = "environ.get"
    elif isinstance(func, ast.Attribute) and func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        via = "getenv"
    elif isinstance(func, ast.Name) and func.id == "getenv":
        via = "getenv"
    else:
        return None
    if not node.args:
        return None
    default: ast.expr | None = node.args[1] if len(node.args) > 1 else None
    if default is None:
        for kw in node.keywords:
            if kw.arg == "default":
                default = kw.value
    return ("call", default, via)


def _name_expr(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.Subscript):
        return node.slice if isinstance(node.slice, ast.expr) else None
    if isinstance(node, ast.Call) and node.args:
        return node.args[0]
    return None


def _resolve_name(expr: ast.expr | None, consts: dict[str, Any]) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        value = consts.get(expr.id)
        if isinstance(value, str):
            return value
    return None


def _import_bindings(info_rel: str, tree: ast.Module) -> list[_Binding]:
    """Every `from X import NAME` in a module, with its lexical scope.

    Defaults are routinely written as an imported constant, and this codebase
    imports two DIFFERENT constants under the SAME name `DEFAULT_MODEL` inside
    one function. Without the scope and the line number, reconciling defaults
    across modules would confidently compare the wrong values.
    """
    out: list[_Binding] = []
    for node, parents in _walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        func = _enclosing(parents, (ast.FunctionDef, ast.AsyncFunctionDef))
        owner = None
        if func is not None:
            owner = (func.lineno, getattr(func, "end_lineno", None) or func.lineno)
        origin = _resolve_import_origin(info_rel, node)
        for alias in node.names:
            if alias.name == "*":
                continue
            out.append(_Binding(
                alias=alias.asname or alias.name,
                origin=origin,
                original=alias.name,
                lineno=node.lineno,
                owner=owner,
            ))
    return out


def _resolve_import_origin(info_rel: str, node: ast.ImportFrom) -> str:
    parts = info_rel.split("/")[:-1]
    if node.level:
        parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
    else:
        parts = []
    if node.module:
        parts = parts + node.module.split(".")
    if not parts:
        return ""
    return "/".join(parts) + ".py"


class _Resolver:
    """Resolves a constant Name to its value, following module imports."""

    def __init__(self, modules: dict[str, _ModuleInfo]) -> None:
        self._modules = modules

    def value(self, name: str, info: _ModuleInfo, lineno: int,
              func: ast.AST | None, _depth: int = 0) -> tuple[bool, Any]:
        if _depth > 4:
            return False, None
        if name in info.consts:
            return True, info.consts[name]
        binding = self._binding(name, info, lineno, func)
        if binding is None or not binding.origin:
            return False, None
        target = self._modules.get(binding.origin) or self._modules.get(
            binding.origin[: -len(".py")] + "/__init__.py")
        if target is None:
            return False, None
        return self.value(binding.original, target, 10 ** 9, None, _depth + 1)

    def _binding(self, name: str, info: _ModuleInfo, lineno: int,
                 func: ast.AST | None) -> _Binding | None:
        span = None
        if func is not None:
            span = (func.lineno, getattr(func, "end_lineno", None) or func.lineno)
        local = [b for b in info.bindings
                 if b.alias == name and b.owner is not None and b.owner == span
                 and b.lineno <= lineno]
        if local:
            return max(local, key=lambda b: b.lineno)
        globals_ = [b for b in info.bindings if b.alias == name and b.owner is None]
        return globals_[-1] if globals_ else None


def _resolve_default(expr: ast.expr | None, info: _ModuleInfo, resolver: _Resolver,
                     lineno: int, func: ast.AST | None) -> str | None:
    """The default's constant value as text, or None when it is not a literal."""
    if expr is None:
        return None
    if isinstance(expr, ast.Constant):
        return "" if expr.value is None else str(expr.value)
    if isinstance(expr, ast.Name):
        found, value = resolver.value(expr.id, info, lineno, func)
        if found:
            return "" if value is None else str(value)
    return None


def _classify_kind(name: str, node: ast.AST, parents: Sequence[ast.AST],
                   func: ast.AST | None) -> str:
    """Syntactic evidence first, then the enclosing signature, then the name."""
    if name in _PLATFORM_ENV:
        return "platform"
    tokens = set(_tokens(name))
    if tokens & _SECRET_TOKENS:
        return "secret"

    current: ast.AST = node
    for anc in reversed(parents[-6:]):
        if isinstance(anc, ast.Attribute) and anc.value is current:
            current = anc
            continue
        if isinstance(anc, ast.Call) and anc.func is current:
            current = anc
            continue
        if isinstance(anc, ast.Call) and isinstance(anc.func, ast.Name):
            if anc.func.id in ("int",):
                return "number"
            if anc.func.id in ("float",):
                return "number"
            if anc.func.id in ("bool",):
                return "flag"
            if anc.func.id in ("Path",):
                return "path"
        if isinstance(anc, ast.Compare) and isinstance(anc.ops[0], (ast.In, ast.NotIn, ast.Eq, ast.NotEq)):
            return "flag"
        if isinstance(anc, (ast.If, ast.IfExp, ast.While)) and getattr(anc, "test", None) is current:
            return "flag"
        if isinstance(anc, (ast.BoolOp, ast.UnaryOp)):
            current = anc
            continue
        break

    returns = getattr(func, "returns", None)
    ret = _src(returns) if returns is not None else ""
    if ret == "bool":
        return "flag"
    if ret in ("int", "float"):
        return "number"
    if ret in ("Path", "pathlib.Path"):
        return "path"

    if tokens & _NUMBER_TOKENS:
        return "number"
    if tokens & _URL_TOKENS:
        return "url"
    if tokens & _PATH_TOKENS:
        return "path"
    if tokens & _FLAG_TOKENS:
        return "flag"
    return "string"


def _has_default_name(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and "DEFAULT" in sub.id.upper():
            return True
    return False


def _fallback_evidence(node: ast.AST, parents: Sequence[ast.AST],
                       block: Sequence[ast.stmt] | None,
                       stmt: ast.stmt | None) -> str:
    """Does an unset variable still yield a usable value at this site?

    Evidence, in order: a DEFAULT-named constant in the same statement; the read
    sitting in a non-final ``or`` operand (something else answers when it is
    empty); a conditional expression; or -- when the read is stashed in a local
    -- a later statement in the same block that consumes that local through a
    DEFAULT constant, an ``if/else``, or a conditional expression.
    """
    if stmt is not None:
        if _has_default_name(stmt):
            return "DEFAULT constant in the same statement"
        for anc in reversed(parents):
            if isinstance(anc, ast.BoolOp) and isinstance(anc.op, ast.Or):
                if any(_contains(operand, node) for operand in anc.values[:-1]):
                    return "left operand of an `or` fallback chain"
            if isinstance(anc, ast.IfExp) and _contains(anc.test, node):
                return "conditional expression supplies the other branch"

    if stmt is None or block is None:
        return ""
    if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)):
        return ""
    local = stmt.targets[0].id
    seen = False
    for sibling in block:
        if sibling is stmt:
            seen = True
            continue
        if not seen:
            continue
        # The guard must be ABOUT this local. Any `or`/`if` anywhere in a long
        # statement that merely happens to mention it is not evidence -- that
        # loose form silently un-darkened three provider API keys.
        for sub in ast.walk(sibling):
            if isinstance(sub, ast.IfExp) and _mentions(sub.test, local):
                return f"conditional expression guards `{local}` downstream"
            if isinstance(sub, ast.If) and _mentions(sub.test, local):
                if sub.orelse:
                    return f"if/else guards `{local}` downstream"
                if _has_default_name(ast.Module(body=sub.body, type_ignores=[])):
                    return f"DEFAULT constant guards `{local}` downstream"
            if isinstance(sub, ast.BoolOp) and isinstance(sub.op, ast.Or):
                if any(_mentions(operand, local) for operand in sub.values[:-1]):
                    return f"`or` fallback guards `{local}` downstream"
    return ""


def _mentions(node: ast.AST, name: str) -> bool:
    return any(isinstance(sub, ast.Name) and sub.id == name for sub in ast.walk(node))


def _contains(haystack: ast.AST, needle: ast.AST) -> bool:
    return any(sub is needle for sub in ast.walk(haystack))


def _statement_for(parents: Sequence[ast.AST]) -> ast.stmt | None:
    for anc in reversed(parents):
        if isinstance(anc, ast.stmt):
            return anc
    return None


def _block_for(parents: Sequence[ast.AST], stmt: ast.stmt | None) -> list[ast.stmt] | None:
    if stmt is None:
        return None
    for anc in reversed(parents):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(anc, attr, None)
            if isinstance(block, list) and any(s is stmt for s in block):
                return block
    return None


def _state_for(required: bool, default_literal: str | None,
               has_default_expr: bool) -> str:
    if required:
        return "REQUIRED"
    if default_literal is None:
        # Non-literal default (a module constant or an expression): a value is
        # supplied, so the feature is configured even when the env is unset.
        return "ON" if has_default_expr else "OFF"
    return "OFF" if default_literal.strip().lower() in _OFF_LITERALS else "ON"


def _polarity(name: str) -> str:
    return "disable" if set(_tokens(name)) & _INVERTING_TOKENS else "enable"


def _gates_sentence(func: ast.AST | None, tree: ast.Module, module: str,
                    qualname: str) -> str:
    doc = ast.get_docstring(func) if isinstance(
        func, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
    sentence = _first_sentence(doc)
    if sentence:
        return sentence
    sentence = _first_sentence(ast.get_docstring(tree))
    if sentence:
        return sentence
    return f"read by {qualname or module} (no docstring at the read site)"


def _collect_module(path: Path, root: Path) -> tuple[_ModuleInfo | None, str]:
    rel = _rel(path, root)
    try:
        tree = ast.parse(_read_text(path), filename=str(path))
    except SyntaxError as exc:
        return None, f"{rel}: {exc.__class__.__name__}: {exc}"
    return _ModuleInfo(
        rel=rel,
        tree=tree,
        consts=_module_constants(tree),
        bindings=_import_bindings(rel, tree),
    ), ""


def _scan_module(info: _ModuleInfo, resolver: _Resolver) -> tuple[
        list[EnvSite], list[ParamSwitch], list[str], set[str], set[str]]:
    module = info.rel
    tree = info.tree
    consts = info.consts
    const_names = {name for name in consts if name.isupper() and "_" in name}
    sites: list[EnvSite] = []
    params: list[ParamSwitch] = []
    dynamic: list[str] = []
    literals: set[str] = set()

    for node, parents in _walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)

        read = _env_read(node)
        if read is not None:
            _, default_expr, via = read
            name = _resolve_name(_name_expr(node), consts)
            line = getattr(node, "lineno", 0)
            if name is None:
                dynamic.append(f"{module}:{line} {_src(_name_expr(node))}")
            else:
                func = _enclosing(parents, (ast.FunctionDef, ast.AsyncFunctionDef))
                stmt = _statement_for(parents)
                block = _block_for(parents, stmt)
                required = via == "environ[]"
                kind = _classify_kind(name, node, parents, func)
                default_literal = _resolve_default(default_expr, info, resolver, line, func)
                state = _state_for(required, default_literal, default_expr is not None)
                fallback = "" if required else _fallback_evidence(node, parents, block, stmt)
                polarity = _polarity(name)
                dark = (
                    state == "OFF"
                    and polarity == "enable"
                    and kind != "platform"
                    and not fallback
                )
                sites.append(EnvSite(
                    name=name,
                    module=module,
                    line=line,
                    via=via,
                    default=_src(default_expr) if default_expr is not None else (
                        "<required>" if required else "None"),
                    default_literal=default_literal,
                    required=required,
                    kind=kind,
                    polarity=polarity,
                    state=state,
                    dark=dark,
                    fallback=fallback,
                    gates=_gates_sentence(func, tree, module, _qualname(parents, node)),
                ))

        # Registry-declared env keys: `env_key="X"` / `env_keys=("X", ...)`,
        # read later through a variable. Without these the provider lanes look
        # unconfigurable because no literal name appears at the read site.
        for key_name, value in _registry_env_keys(node):
            for env_name in value:
                sites.append(EnvSite(
                    name=env_name,
                    module=module,
                    line=getattr(node, "lineno", 0),
                    via="registry",
                    default="None",
                    default_literal="",
                    required=False,
                    kind="secret" if set(_tokens(env_name)) & _SECRET_TOKENS else "string",
                    polarity=_polarity(env_name),
                    state="OFF",
                    dark=True,
                    fallback="",
                    gates=f"declared as `{key_name}` in a provider/runtime registry entry; "
                          f"the lane reports unconfigured until it is set",
                ))

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params.extend(_param_switches(node, parents, module, tree))

    return sites, params, dynamic, literals, const_names


def _registry_env_keys(node: ast.AST) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    if isinstance(node, ast.keyword) and node.arg in ("env_key", "env_keys"):
        out.append((node.arg, _string_values(node.value)))
    elif isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value in ("env_key", "env_keys"):
                out.append((str(key.value), _string_values(value)))
    return [(name, values) for name, values in out if values]


def _string_values(node: ast.expr) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out: list[str] = []
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str) and element.value:
                out.append(element.value)
        return out
    return []


def _param_switches(node: ast.FunctionDef | ast.AsyncFunctionDef,
                    parents: Sequence[ast.AST], module: str,
                    tree: ast.Module) -> list[ParamSwitch]:
    if node.name.startswith("_"):
        return []
    for anc in parents:
        if isinstance(anc, ast.ClassDef) and anc.name.startswith("_"):
            return []
        if isinstance(anc, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return []      # nested helper, not a public entry point
    args = node.args
    pairs: list[tuple[ast.arg, ast.expr]] = []
    positional = list(args.posonlyargs) + list(args.args)
    for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
        pairs.append((arg, default))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is not None:
            pairs.append((arg, default))

    out: list[ParamSwitch] = []
    qualname = _qualname(parents, node)
    for arg, default in pairs:
        if not (isinstance(default, ast.Constant) and default.value is False):
            continue
        annotation = _src(arg.annotation) if arg.annotation is not None else ""
        if annotation and "bool" not in annotation:
            continue
        head = _tokens(arg.arg)[0].lower() if _tokens(arg.arg) else arg.arg.lower()
        gate = head in _GATE_PARAMS or arg.arg.lower() in _GATE_PARAMS
        dark = gate and head not in _SAFETY_PARAMS
        out.append(ParamSwitch(
            module=module,
            line=node.lineno,
            qualname=qualname,
            param=arg.arg,
            annotation=annotation or "(unannotated)",
            default="False",
            state="OFF",
            dark=dark,
            gates=_gates_sentence(node, tree, module, qualname),
        ))
    return out


# --------------------------------------------------------------------------- #
# config keys
# --------------------------------------------------------------------------- #

def _flatten(prefix: str, value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            if str(key).startswith("_"):
                continue        # `_comment` keys are prose, not switches
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten(child, value[key])
    else:
        yield prefix, value


def _config_switches(root: Path, literals: set[str]) -> list[ConfigSwitch]:
    sources: list[Path] = []
    projects = root / "projects"
    if projects.is_dir():
        sources.extend(sorted(projects.glob("*.json")))
    for candidate in sorted(root.glob("*settings*.json")) + sorted(root.glob("config.json")):
        if candidate.is_file():
            sources.append(candidate)

    out: list[ConfigSwitch] = []
    for path in sources:
        try:
            payload = json.loads(_read_text(path))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for key, value in _flatten("", payload):
            if not key:
                continue
            off = (
                value is False
                or value is None
                or value == 0
                or value == ""
                or (isinstance(value, (list, dict)) and len(value) == 0)
            )
            gate = isinstance(value, bool) or off
            if not gate:
                continue
            leaf = key.rsplit(".", 1)[-1]
            read = leaf in literals
            out.append(ConfigSwitch(
                source=_rel(path, root),
                key=key,
                value=json.dumps(value),
                state="OFF" if off else "ON",
                read_in_code=read,
                dark=bool(off and read),
            ))
    out.sort(key=lambda c: (c.source, c.key))
    return out


# --------------------------------------------------------------------------- #
# documentation cross-check
# --------------------------------------------------------------------------- #

def _documented_names(root: Path) -> dict[str, list[str]]:
    """Env-shaped names in docs, mapped to `path:line` sites."""
    found: dict[str, list[str]] = {}
    for path in _iter_docs(root):
        rel = _rel(path, root)
        for lineno, line in enumerate(_read_text(path).splitlines(), 1):
            for pattern in _DOC_ENV_FORMS:
                for match in pattern.finditer(line):
                    name = match.group("name")
                    if "_" not in name or not _ENV_TOKEN.fullmatch(name):
                        continue
                    found.setdefault(name, []).append(f"{rel}:{lineno}")
    return found


def _mentioned_names(root: Path) -> dict[str, list[str]]:
    """Every env-shaped token in docs, however it is written."""
    found: dict[str, list[str]] = {}
    for path in _iter_docs(root):
        rel = _rel(path, root)
        for lineno, line in enumerate(_read_text(path).splitlines(), 1):
            for match in _ENV_TOKEN.finditer(line):
                found.setdefault(match.group(0), []).append(f"{rel}:{lineno}")
    return found


def _augment_documented(documented: dict[str, list[str]],
                        mentioned: dict[str, list[str]], read: set[str]) -> None:
    """Count a bare doc mention as documentation for names the code truly reads.

    ``docs/HANDOFF.md`` lists some variables as bare lines inside a fenced
    block, which matches no operator-shaped form. Requiring the strict form
    there would manufacture a "read but never documented" finding for a name
    the docs plainly show, and the whole point of the drift list is that every
    entry is worth acting on.
    """
    for name in sorted(read):
        if name in documented:
            continue
        sites = mentioned.get(name)
        if sites:
            documented[name] = list(sites)


def _is_subsequence(short: Sequence[str], long: Sequence[str]) -> bool:
    it = iter(long)
    return all(token in it for token in short)


def _drift(documented: dict[str, list[str]], mentioned: dict[str, list[str]],
           sites_by_name: dict[str, list[EnvSite]]) -> list[DocDrift]:
    read = {name for name in sites_by_name if name not in _PLATFORM_ENV}
    doc_names = set(documented)
    out: list[DocDrift] = []

    for name in sorted(doc_names - read):
        out.append(DocDrift(
            kind="documented_never_read",
            documented=name,
            read="",
            detail="docs tell an operator to set it; no module in the package reads it",
            doc_sites=tuple(sorted(set(documented[name]))),
            code_sites=(),
        ))
    for name in sorted(read - doc_names):
        sites = sites_by_name[name]
        out.append(DocDrift(
            kind="read_never_documented",
            documented="",
            read=name,
            detail="the code reads it; no doc shows an operator how to set it",
            doc_sites=tuple(sorted(set(mentioned.get(name, ())))),
            code_sites=tuple(sorted(f"{s.module}:{s.line}" for s in sites)),
        ))

    # A near-miss pair is the silent bug: the operator sets the documented name
    # and nothing happens. Only strict token-subsequence pairs qualify, so
    # OLLAMA_NUM_CTX and OLLAMA_NUM_PARALLEL are not accused of being the same
    # variable spelled two ways.
    for doc_name in sorted(doc_names):
        for read_name in sorted(read):
            if doc_name == read_name:
                continue
            a, b = _tokens(doc_name), _tokens(read_name)
            if len(a) == len(b):
                continue
            short, long = (a, b) if len(a) < len(b) else (b, a)
            if short[0] != long[0] or not _is_subsequence(short, long):
                continue
            if doc_name in read and read_name in doc_names:
                continue     # both sides are documented and read: an alias pair
            out.append(DocDrift(
                kind="name_mismatch",
                documented=doc_name,
                read=read_name,
                detail=(f"`{doc_name}` and `{read_name}` differ by "
                        f"{abs(len(a) - len(b))} name segment(s); only one of the two "
                        f"is both documented and read"),
                doc_sites=tuple(sorted(set(documented.get(doc_name, ())))),
                code_sites=tuple(sorted(
                    f"{s.module}:{s.line}" for s in sites_by_name.get(read_name, ()))),
            ))

    out.sort(key=lambda d: (d.kind, d.documented, d.read))
    return out


# --------------------------------------------------------------------------- #
# reconciliation
# --------------------------------------------------------------------------- #

def _default_key(site: EnvSite) -> str:
    """What this site actually falls back to -- the value, not how it is spelt."""
    if site.default_literal is None:
        return site.default
    return repr(site.default_literal)


def _majority(values: Sequence[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _reconcile(name: str, sites: list[EnvSite], documented: bool) -> EnvSwitch:
    """Fold every read of one variable into a single verdict.

    DARK requires unanimity on the default (every site reads it as off) plus at
    least one site with no fallback -- i.e. there is a code path that simply
    does not run unless an operator knows the name. A variable that is off at
    one site and defaulted at another is MIXED, never dark: the feature is
    reachable, the defaults just disagree, which the conflict list reports.
    """
    ordered = tuple(sorted(sites, key=lambda s: (s.module, s.line)))
    real = [s for s in ordered if s.via != "registry"] or list(ordered)
    defaults = sorted({_default_key(s) for s in real})
    states = {s.state for s in real}
    return EnvSwitch(
        name=name,
        kind=_majority([s.kind for s in real]),
        polarity=_majority([s.polarity for s in real]),
        default=_majority([s.default for s in real]),
        state=next(iter(states)) if len(states) == 1 else "MIXED",
        dark=states == {"OFF"} and any(s.dark for s in real),
        documented=documented,
        gates=_majority([s.gates for s in real]),
        conflicting_defaults=tuple(defaults) if len(defaults) > 1 else (),
        sites=ordered,
    )


def analyse(repo_root: str | Path) -> SwitchReport:
    """Inventory every switch under ``repo_root`` and classify its default."""
    root = Path(repo_root).resolve()
    sites: list[EnvSite] = []
    params: list[ParamSwitch] = []
    dynamic: list[str] = []
    unparsable: list[str] = []
    literals: set[str] = set()
    const_names: set[str] = set()
    modules = 0

    # Two passes: every module is parsed before any default is resolved, so a
    # default written as an imported constant is compared by VALUE. Comparing
    # the source text instead reports `DEFAULT_HOST` and its own literal as a
    # disagreement while missing DEEPSEEK_MODEL, where the values really differ.
    collected: dict[str, _ModuleInfo] = {}
    for path in _iter_sources(root):
        modules += 1
        info, problem = _collect_module(path, root)
        if info is None:
            unparsable.append(problem)
            continue
        collected[info.rel] = info

    resolver = _Resolver(collected)
    for rel in sorted(collected):
        m_sites, m_params, m_dynamic, m_literals, m_consts = _scan_module(
            collected[rel], resolver)
        sites.extend(m_sites)
        params.extend(m_params)
        dynamic.extend(m_dynamic)
        literals |= m_literals
        const_names |= m_consts

    documented = _documented_names(root)
    mentioned = _mentioned_names(root)

    by_name: dict[str, list[EnvSite]] = {}
    for site in sites:
        by_name.setdefault(site.name, []).append(site)

    # `DEFAULT_NUM_CTX=8192` in prose documents a Python constant, not an
    # environment variable. Names the code defines as module constants and
    # never reads from the environment are dropped before drift is computed.
    for name in sorted(const_names - set(by_name)):
        documented.pop(name, None)
    # SAME notion of "read" that ``_drift`` uses, platform names excluded. When
    # these two disagreed, a bare doc mention of an OS variable put it into
    # ``documented`` while ``_drift`` kept it out of ``read``, and the
    # difference surfaced as a phantom "documented, but no code reads it any
    # more" row for a name the code demonstrably reads.
    _augment_documented(documented, mentioned,
                        {n for n in by_name if n not in _PLATFORM_ENV})

    switches = tuple(
        _reconcile(name, by_name[name], name in documented)
        for name in sorted(by_name)
    )
    params.sort(key=lambda p: (p.module, p.line, p.param))
    config = _config_switches(root, literals)
    drift = _drift(documented, mentioned, by_name)

    counts = SwitchCounts(
        env_switches=len(switches),
        env_sites=len(sites),
        dark_env=sum(1 for s in switches if s.dark),
        inverted_env=sum(1 for s in switches if s.polarity == "disable"),
        conflicting_env=sum(1 for s in switches if s.conflicting_defaults),
        param_switches=len(params),
        dark_params=sum(1 for p in params if p.dark),
        config_switches=len(config),
        dark_config=sum(1 for c in config if c.dark),
        drift=len(drift),
        name_mismatches=sum(1 for d in drift if d.kind == "name_mismatch"),
        dynamic_reads=len(dynamic),
        modules_scanned=modules,
    )
    return SwitchReport(
        schema=SCHEMA,
        root=root.as_posix(),
        counts=counts,
        env_switches=switches,
        param_switches=tuple(params),
        config_switches=tuple(config),
        drift=tuple(drift),
        dynamic_reads=tuple(sorted(set(dynamic))),
        unparsable=tuple(sorted(set(unparsable))),
    )
