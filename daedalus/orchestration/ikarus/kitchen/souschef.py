"""The Sous-Chef: a local, low-context model working through task division.

Claude Code and Codex are agentic -- they read, write and run tools on their
own. A local Ollama model has no tools and a small window, so the kitchen
supplies the agency: it PLANS the candidate as a short list of files, WRITES
one file per call with only the context that file needs (the plan, the
signatures of files already written, and the Grey Matter motifs retrieved for
that file's purpose), CHECKS through the toolchain, and REPAIRS only the files
the failure names. Every call is bounded by characters, never by hope.

This is the demonstration the owner asked for on 2026-09-12: a low-context
agent can work inside the Ariadne forest when Grey Matter divides the labour.
The lane records its decomposition (steps, context sizes, motifs) so the claim
is inspectable rather than asserted.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .report import BuilderReport, BuilderUnavailable
from .toolchain import MANIFEST, _EVALUATOR_DIRS, _VERIFICATION_CONFIGS, detect, freeze_verification

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"


def host_url() -> str:
    """``OLLAMA_HOST`` as Ollama itself spells it (``host:port`` or a URL)."""
    raw = os.environ.get("DAEDALUS_KITCHEN_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
    raw = raw.strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    if raw.startswith("http://0.0.0.0"):
        raw = raw.replace("0.0.0.0", "127.0.0.1", 1)
    return raw


def model_name() -> str:
    return os.environ.get("DAEDALUS_KITCHEN_OLLAMA_MODEL", DEFAULT_MODEL)
MAX_FILES = 10
MAX_REPAIR_FILES = 3
PLAN_CHARS = 9000
FILE_CONTEXT_CHARS = 7000
MOTIF_CHARS = 1400
WRITTEN_PREVIEW_CHARS = 900
NUM_PREDICT = 6000
_FENCE = re.compile(r"```[a-zA-Z0-9_+.-]*\n(.*?)```", re.S)
_SAFE_PATH = re.compile(r"^(?!/)(?!.*\.\.)(?!.*//)[A-Za-z0-9_][A-Za-z0-9_./-]{0,200}$")

_STATIC_MANIFEST = {"stack": "static-web",
                    "build": ["python", "-c", "import pathlib,sys,html.parser\nclass P(html.parser.HTMLParser):\n    ok=False\n    def handle_starttag(self,t,a):\n        self.ok = self.ok or t=='html'\np=P(); p.feed(pathlib.Path('index.html').read_text(encoding='utf-8')); sys.exit(0 if p.ok else 1)"],
                    "test": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                    "run": ["python", "-m", "http.server", "8765", "--bind", "127.0.0.1"], "preview": "http://127.0.0.1:8765"}
_PYTHON_MANIFEST = {"stack": "python", "build": ["python", "-m", "compileall", "-q", "."],
                    "test": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], "run": ["python", "main.py"], "preview": None}


def ollama_available(host: str | None = None, model: str | None = None) -> bool:
    host = host or host_url()
    model = model or model_name()
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False
    names = {m.get("name") for m in payload.get("models", []) if isinstance(m, dict)}
    return model in names or model.split(":")[0] + ":latest" in names or any(n and n.startswith(model) for n in names)


def _chat(messages: list[dict[str, str]], *, json_mode: bool, timeout_s: float, host: str, model: str,
          num_predict: int = NUM_PREDICT) -> str:
    from ....providers._ollama_native import native_chat
    reply = native_chat(host=host, model=model, messages=messages, force_json=json_mode, num_predict=num_predict,
                        keep_alive="10m", timeout_s=timeout_s, temperature=0.1)
    return str(reply.get("content") or "")


def _json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        payload = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except ValueError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _content(text: str) -> str:
    blocks = _FENCE.findall(text)
    if blocks:
        return max(blocks, key=len).rstrip() + "\n"
    return text.strip() + "\n"


def _safe_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().replace("\\", "/").lstrip("./")
    return value if _SAFE_PATH.match(value) else None


def _frozen_verification_paths(workspace: Path) -> set[str]:
    frozen = freeze_verification(detect(workspace), workspace)
    if frozen.error:
        raise ValueError(frozen.error)
    return {name.casefold() for name, _ in frozen.files}


def _is_verification_path(relative: str, frozen_paths: set[str]) -> bool:
    """Apply the kitchen's evaluator selection to existing and proposed files.

    Existing custom command inputs come from the frozen snapshot. Conventional
    tests/configs also stay protected when a model proposes creating them.
    The Chef's full integrity check remains authoritative after these writes.
    """
    path = Path(relative)
    name = path.name.casefold()
    return (relative.casefold() in frozen_paths
            or name in {config.casefold() for config in _VERIFICATION_CONFIGS}
            or name.startswith(("vitest.config.", "vite.config.", "jest.config.", "webpack.config.", "tsconfig"))
            or bool({part.casefold() for part in path.parts[:-1]} & _EVALUATOR_DIRS)
            or name.startswith("test_") or name.endswith("_test.py") or ".test." in name or ".spec." in name)


def _order_text(prompt: str) -> str:
    match = re.search(r"ORDER \(.*?\):\n(.*?)\n\n", prompt, re.S)
    return match.group(1).strip() if match else prompt[:1500]


def _preview(path: Path, limit: int = WRITTEN_PREVIEW_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [l for l in text.splitlines() if l.strip()]
    signature = [l for l in lines if re.match(r"\s*(def |class |function |export |const |let |import |from |<(?:html|body|main|section|script|link)|\.[a-zA-Z-]+\s*\{)", l)]
    chosen = "\n".join(signature[:40]) if len(signature) >= 3 else "\n".join(lines[:30])
    return chosen[:limit]


def _contract_terms(plan: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """Ids, function names and storage keys named by the plan's shared contract."""
    text = " ".join([plan.get("shared_contract", ""), " ".join(f.get("purpose", "") for f in plan.get("files", []))])
    ids = sorted({m for m in re.findall(r"(?:#|\bid[=:\s]+[\"'`]?)([A-Za-z][\w-]{2,40})", text)} - {"html", "body", "head"})
    functions = sorted({m for m in re.findall(r"\b([a-z][A-Za-z0-9_]{2,40})\(\)", text)} - {"function", "return", "console"})
    keys = sorted({m for m in re.findall(r"(?:key|storage|localStorage)[^\"'`]{0,30}[\"'`]([A-Za-z][\w:.-]{2,60})[\"'`]", text, re.I)})
    return ids[:20], functions[:20], keys[:5]


def _static_test_source(plan: dict[str, Any]) -> str:
    """The kitchen-owned evaluator for a static web candidate (stdlib + pytest).

    The model writes the application; the kitchen writes what proves it. A
    candidate never authors its own evaluator (Masterplan Invariant 3/4).
    """
    ids, functions, keys = _contract_terms(plan)
    return f'''"""Kitchen-owned structural evaluator (generated; the builder must not edit it)."""
import html.parser
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
IDS = {json.dumps(ids)}
FUNCTIONS = {json.dumps(functions)}
KEYS = {json.dumps(keys)}


def _read(name):
    path = ROOT / name
    assert path.is_file(), f"{{name}} is missing"
    return path.read_text(encoding="utf-8")


class _Shell(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.scripts, self.styles, self.ids = [], [], [], set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])
        if tag == "link" and attrs.get("rel", "").lower() == "stylesheet" and attrs.get("href"):
            self.styles.append(attrs["href"])
        if attrs.get("id"):
            self.ids.add(attrs["id"])


def _shell():
    parser = _Shell()
    parser.feed(_read("index.html"))
    return parser


def test_index_is_a_complete_html_document():
    shell = _shell()
    for tag in ("html", "head", "body"):
        assert tag in shell.tags, f"<{{tag}}> missing"
    assert "title" in shell.tags or "h1" in shell.tags


def test_referenced_assets_exist_and_are_local():
    shell = _shell()
    for ref in shell.scripts + shell.styles:
        assert not ref.startswith(("http://", "https://", "//")), f"external asset {{ref}}"
        assert (ROOT / ref.split("?")[0]).is_file(), f"missing asset {{ref}}"
    assert shell.scripts, "index.html loads no script"


def test_app_script_uses_local_storage_and_has_no_network_calls():
    shell = _shell()
    js = "\\n".join(_read(ref.split("?")[0]) for ref in shell.scripts)
    assert "localStorage" in js
    assert not re.search(r"\\bfetch\\(|XMLHttpRequest|WebSocket", js), "network calls are not allowed"
    assert not re.search(r"https?://", js.replace("http://127.0.0.1", "")), "external URLs are not allowed"


def test_shared_contract_ids_are_present():
    shell = _shell()
    js = "\\n".join(_read(ref.split("?")[0]) for ref in shell.scripts)
    missing = [i for i in IDS if i not in shell.ids and f'"{{i}}"' not in js and f"'{{i}}'" not in js and f"#{{i}}" not in js]
    assert not missing, f"contract ids missing: {{missing}}"


def test_shared_contract_functions_are_defined():
    shell = _shell()
    js = "\\n".join(_read(ref.split("?")[0]) for ref in shell.scripts)
    missing = [f for f in FUNCTIONS if not re.search(r"\\b" + re.escape(f) + r"\\b", js)]
    assert not missing, f"contract functions missing: {{missing}}"


def test_readme_explains_how_to_run():
    readme = _read("README.md").lower()
    assert "http.server" in readme or "open" in readme or "öffne" in readme or "run" in readme or "start" in readme
'''


class SousChef:
    def __init__(self, *, host: str | None = None, model: str | None = None, grey: Any = None,
                 log: Callable[[str], None] | None = None) -> None:
        self.host = host or host_url()
        self.model = model or model_name()
        self.grey = grey
        self.log = log or (lambda text: None)
        self.steps: list[dict[str, Any]] = []
        self.deferred_verification_proposals: list[dict[str, str]] = []

    # -- helpers -------------------------------------------------------------------
    def _defer_verification(self, path: str, purpose: str = "") -> None:
        self.deferred_verification_proposals.append({"path": path, "purpose": purpose[:400],
            "reason": "frozen verification input; proposal retained without writing or executing it"})
        self.log(f"sous-chef: evaluator proposal {path} deferred; this packet does not write or execute it")

    def _motifs(self, query: str, k: int = 4) -> str:
        if self.grey is None:
            return ""
        try:
            hits = self.grey.search(query, k=k)
        except Exception:
            return ""
        lines = [f"- [{h['plane']}/{h['kind']}] {h['name']} ({h['repo']}): {h['text'][:200].replace(chr(10), ' ')}" for h in hits]
        text = "\n".join(lines)
        return text[:MOTIF_CHARS]

    def _ask(self, name: str, messages: list[dict[str, str]], *, json_mode: bool, timeout_s: float,
             num_predict: int = NUM_PREDICT) -> str:
        started = time.time()
        chars = sum(len(m["content"]) for m in messages)
        text = _chat(messages, json_mode=json_mode, timeout_s=timeout_s, host=self.host, model=self.model, num_predict=num_predict)
        self.steps.append({"step": name, "context_chars": chars, "reply_chars": len(text), "seconds": round(time.time() - started, 1)})
        self.log(f"sous-chef {name}: context {chars} chars → reply {len(text)} chars in {time.time() - started:.1f}s")
        return text

    # -- build -----------------------------------------------------------------------
    def plan(self, order: str, stack_hint: str | None, timeout_s: float) -> dict[str, Any]:
        motifs = self._motifs(order, k=6)
        system = ("You are the planning engineer of a software kitchen. You design SMALL, complete, local-first applications "
                  "that a junior developer can write one file at a time. Output strict JSON only.")
        user = f"""ORDER:
{order}

{('Preferred stack: ' + stack_hint) if stack_hint else 'Stack: choose "static-web" (index.html + styles.css + app.js, localStorage, no frameworks, no CDN) for anything that runs in a browser; choose "python" (stdlib only, main.py) for CLI tools or services.'}

Plan at most {MAX_FILES} files. Always include README.md and a tests folder:
- static-web: the KITCHEN generates tests/test_app.py from your shared_contract, so write the contract precisely: element ids as #item-input, functions as addItem(), the storage key as key "shopping-list". Only ids and functions you list there are checked.
- python: tests/test_main.py using pytest that imports main and checks behaviour.
Each file gets a one-sentence purpose that names the ids/functions other files rely on, so files agree with each other.

Reference motifs from the corpus (inspiration only, do not copy verbatim):
{motifs or '- (corpus empty)'}

Return JSON: {{"summary": "one paragraph", "stack": "static-web"|"python", "files": [{{"path": "index.html", "purpose": "..."}}, ...], "shared_contract": "ids, function names, storage keys every file must use"}}"""
        payload = _json(self._ask("plan", [{"role": "system", "system": system, "content": system}, {"role": "user", "content": user[:PLAN_CHARS]}],
                                  json_mode=True, timeout_s=timeout_s, num_predict=2500))
        files = []
        for row in payload.get("files") or []:
            path = _safe_path(row.get("path") if isinstance(row, dict) else None)
            if path and path not in {f["path"] for f in files}:
                files.append({"path": path, "purpose": str(row.get("purpose") or "")[:400]})
        stack = payload.get("stack") if payload.get("stack") in ("static-web", "python") else ("python" if stack_hint in {"python", "fastapi", "flask", "django"} else "static-web")
        if not files:
            files = ([{"path": "index.html", "purpose": "page shell"}, {"path": "styles.css", "purpose": "styles"},
                      {"path": "app.js", "purpose": "logic with localStorage"}, {"path": "tests/test_app.py", "purpose": "pytest structure checks"},
                      {"path": "README.md", "purpose": "how to run and test"}] if stack == "static-web" else
                     [{"path": "main.py", "purpose": "entry point"}, {"path": "tests/test_main.py", "purpose": "pytest"}, {"path": "README.md", "purpose": "docs"}])
        if not any(f["path"] == "README.md" for f in files):
            files.append({"path": "README.md", "purpose": "purpose, how to run, how to test"})
        if not any(f["path"].startswith("tests/") for f in files):
            files.append({"path": "tests/test_app.py" if stack == "static-web" else "tests/test_main.py", "purpose": "pytest checks of the shared contract"})
        return {"summary": str(payload.get("summary") or order)[:1200], "stack": stack, "files": files[:MAX_FILES],
                "shared_contract": str(payload.get("shared_contract") or "")[:1500]}

    def write_file(self, workspace: Path, plan: dict[str, Any], target: dict[str, Any], order: str, timeout_s: float,
                   *, failure: str | None = None, current: str | None = None) -> str:
        written = []
        for row in plan["files"]:
            path = workspace / row["path"]
            if row["path"] != target["path"] and path.is_file():
                written.append(f"--- {row['path']} (already written; key lines) ---\n{_preview(path)}")
        written_text = "\n".join(written)
        if len(written_text) > FILE_CONTEXT_CHARS:
            written_text = written_text[:FILE_CONTEXT_CHARS] + "\n… (trimmed)"
        motifs = self._motifs(f"{target['purpose']} {order[:200]}")
        system = ("You are a careful developer in a software kitchen. You write EXACTLY ONE complete file. Output only that file's "
                  "content inside a single fenced code block, nothing else. No external network, no CDN, no frameworks unless "
                  "the plan names them; localStorage for persistence; accessible, responsive UI; stdlib-only Python.")
        task = (f"REPAIR this file. The kitchen's checks failed:\n{failure[-2500:]}\n\nCurrent content:\n```\n{(current or '')[:FILE_CONTEXT_CHARS]}\n```\n"
                if failure else "WRITE this file completely.")
        user = f"""ORDER: {order[:800]}

PLAN SUMMARY: {plan['summary'][:800]}
STACK: {plan['stack']}
SHARED CONTRACT (ids, functions, storage keys every file must use): {plan['shared_contract'][:900]}
ALL FILES: {', '.join(f["path"] + ' — ' + f['purpose'][:80] for f in plan['files'])}

{written_text or '(no other files written yet)'}

Motifs from the corpus for this file (inspiration only):
{motifs or '- (none)'}

TARGET FILE: {target['path']}
PURPOSE: {target['purpose']}
{task}"""
        reply = self._ask(f"write {target['path']}", [{"role": "system", "content": system}, {"role": "user", "content": user}],
                          json_mode=False, timeout_s=timeout_s)
        return _content(reply)

    def build(self, workspace: Path, order: str, stack_hint: str | None, timeout_s: float) -> tuple[list[str], dict[str, Any]]:
        deadline = time.time() + timeout_s
        plan = self.plan(order, stack_hint, min(600, timeout_s))
        self.log(f"sous-chef plan: {plan['stack']} with {len(plan['files'])} files: {[f['path'] for f in plan['files']]}")
        changed = []
        kitchen_owned = plan["stack"] == "static-web"
        for target in plan["files"]:
            if kitchen_owned and target["path"].startswith("tests/"):
                continue  # the kitchen writes the evaluator below
            remaining = deadline - time.time()
            if remaining < 30:
                self.log("sous-chef: time budget exhausted before all files were written")
                break
            content = self.write_file(workspace, plan, target, order, min(900, remaining))
            path = workspace / target["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            changed.append(target["path"])
        if kitchen_owned:
            plan["files"] = [f for f in plan["files"] if not f["path"].startswith("tests/")] + [
                {"path": "tests/test_app.py", "purpose": "kitchen-owned structural evaluator (generated, not editable by the builder)"}]
            evaluator = workspace / "tests" / "test_app.py"
            evaluator.parent.mkdir(parents=True, exist_ok=True)
            evaluator.write_text(_static_test_source(plan), encoding="utf-8")
            changed.append("tests/test_app.py")
            self.log("sous-chef: kitchen-owned evaluator written from the shared contract")
        manifest = dict(_STATIC_MANIFEST if plan["stack"] == "static-web" else _PYTHON_MANIFEST)
        if plan["stack"] == "static-web" and not (workspace / "tests").is_dir():
            manifest["test"] = ["python", "-c", "print('no tests planned')"]
        (workspace / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        changed.append(MANIFEST)
        (workspace / ".kitchen-plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        return changed, plan

    # -- repair -----------------------------------------------------------------------
    def repair(self, workspace: Path, order: str, failures: str, timeout_s: float) -> list[str]:
        frozen_paths = _frozen_verification_paths(workspace)
        plan_path = workspace / ".kitchen-plan.json"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            plan = {"summary": order, "stack": "python" if (workspace / "main.py").is_file() else "static-web",
                    "files": [{"path": p.relative_to(workspace).as_posix(), "purpose": ""} for p in sorted(workspace.rglob("*"))
                              if p.is_file() and not p.name.startswith(".") and p.name != MANIFEST][:MAX_FILES], "shared_contract": ""}
        known = [f["path"] for f in plan["files"]]
        editable = [p for p in known if _safe_path(p) == p and not _is_verification_path(p, frozen_paths)]
        system = "You triage failing checks for a small project. Output strict JSON only."
        user = f"""FILES: {', '.join(editable)}

FAILING CHECK OUTPUT:
{failures[-4000:]}

Build/test commands, manifests, configuration and evaluator files are frozen for every stack. Fix application source only.
Do not create or change tests, conftest files or configuration. New verification proposals are deferred and are not executed by this packet.
Which files (at most {MAX_REPAIR_FILES}, from FILES only) must change to fix this? Return JSON: {{"files": ["path", ...], "diagnosis": "one sentence"}}"""
        payload = _json(self._ask("triage", [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                  json_mode=True, timeout_s=min(300, timeout_s), num_predict=600))
        proposals = [p for p in (payload.get("files") or []) if isinstance(p, str)]
        for path in proposals:
            if _is_verification_path(path, frozen_paths):
                self._defer_verification(path)
        picked = [p for p in proposals if p in editable][:MAX_REPAIR_FILES]
        if not picked:
            picked = [p for p in editable if p.endswith((".js", ".py")) and not p.startswith("tests/")][:1] or editable[:1]
        self.log(f"sous-chef triage: {payload.get('diagnosis', '')[:200]} → {picked}")
        changed = []
        for path in picked:
            target = next(f for f in plan["files"] if f["path"] == path)
            file_path = workspace / path
            current = file_path.read_text(encoding="utf-8", errors="replace") if file_path.is_file() else ""
            content = self.write_file(workspace, plan, target, order, min(900, timeout_s), failure=failures, current=current)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            changed.append(path)
        return changed

    # -- improve -------------------------------------------------------------------------
    def improve(self, workspace: Path, order: str, timeout_s: float) -> tuple[list[str], dict[str, Any]]:
        from .greymatter import GreyMatter
        frozen_paths = _frozen_verification_paths(workspace)
        scratch = GreyMatter(workspace.parent / f".{workspace.name}.greymatter.db")
        try:
            report = scratch.ingest_repo(workspace, name=f"worktree:{workspace.name}")
            hits = scratch.search(order, k=12, repo_id=report["repo_id"])
        finally:
            scratch.close()
        candidates = []
        for hit in hits:
            rel = hit["locator"].split(":", 1)[0]
            if rel not in candidates and (workspace / rel).is_file() and (workspace / rel).stat().st_size < 60_000:
                candidates.append(rel)
        listing = [p.relative_to(workspace).as_posix() for p in sorted(workspace.rglob("*"))
                   if p.is_file() and not any(part in {".git", "node_modules", "__pycache__", ".venv", "dist"} for part in p.parts)][:200]
        system = "You plan a focused improvement to an existing repository. Output strict JSON only."
        user = f"""ORDER:
{order}

Most relevant files (Grey Matter retrieval over the worktree):
{chr(10).join('- ' + h['locator'] + ' :: ' + h['name'] + ' :: ' + h['text'][:160].replace(chr(10), ' ') for h in hits[:12])}

Repository files (bounded listing): {', '.join(listing)}

Choose at most 6 application source files to rewrite or create (whole files; prefer small ones).
Build/test commands, manifests, configuration and all evaluator files are frozen. Do not add or edit tests or conftest files.
New verification proposals are deferred and are not executed by this packet. Return JSON:
{{"summary": "what changes and why", "files": [{{"path": "...", "purpose": "what this file must do after the change"}}], "shared_contract": "names other files rely on"}}"""
        payload = _json(self._ask("improve-plan", [{"role": "system", "content": system}, {"role": "user", "content": user[:PLAN_CHARS]}],
                                  json_mode=True, timeout_s=min(600, timeout_s), num_predict=2000))
        files = []
        for row in payload.get("files") or []:
            path = _safe_path(row.get("path") if isinstance(row, dict) else None)
            if not path or path in {f["path"] for f in files}:
                continue
            if _is_verification_path(path, frozen_paths):
                self._defer_verification(path, str(row.get("purpose") or ""))
                continue
            files.append({"path": path, "purpose": str(row.get("purpose") or "")[:400]})
        files = files[:6] or [{"path": rel, "purpose": order[:200]} for rel in candidates
                             if not _is_verification_path(rel, frozen_paths)][:2]
        plan = {"summary": str(payload.get("summary") or order)[:1200], "stack": "existing", "files": files,
                "shared_contract": str(payload.get("shared_contract") or "")[:1500],
                "deferred_verification_proposals": list(self.deferred_verification_proposals)}
        changed = []
        deadline = time.time() + timeout_s
        for target in files:
            if deadline - time.time() < 30:
                break
            file_path = workspace / target["path"]
            current = file_path.read_text(encoding="utf-8", errors="replace") if file_path.is_file() else None
            if current is not None and len(current) > FILE_CONTEXT_CHARS * 2:
                self.log(f"sous-chef: {target['path']} too large for a whole-file rewrite in this window; skipped")
                continue
            content = self.write_file(workspace, plan, target, order, min(900, deadline - time.time()),
                                      failure=None if current is None else "(not a failure) Rewrite the whole file so it fulfils the PURPOSE; keep everything unrelated unchanged.",
                                      current=current)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            changed.append(target["path"])
        (workspace / ".kitchen-plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        return changed, plan


def ollama_builder(workspace: Path, prompt: str, timeout_s: int = 1800, context: dict[str, Any] | None = None) -> BuilderReport:
    """The lane entry the Chef calls; ``context`` carries mode, order and Grey Matter."""
    context = context or {}
    host = context.get("host") or host_url()
    model = context.get("model") or model_name()
    if not ollama_available(host, model):
        raise BuilderUnavailable(f"Ollama at {host} has no model {model}")
    sous = SousChef(host=host, model=model, grey=context.get("grey"), log=context.get("log"))
    order = context.get("order_text") or _order_text(prompt)
    mode = context.get("mode") or ("repair" if prompt.startswith("Repair round") else "build")
    started = time.time()
    try:
        if mode == "repair":
            failures = prompt.split("FAILURES:", 1)[-1] if "FAILURES:" in prompt else prompt
            changed = sous.repair(workspace, order, failures, timeout_s)
            plan_summary = f"repaired {len(changed)} file(s)"
        elif mode == "improve":
            changed, plan = sous.improve(workspace, order, timeout_s)
            plan_summary = plan["summary"]
        else:
            changed, plan = sous.build(workspace, order, context.get("stack"), timeout_s)
            plan_summary = plan["summary"]
    except Exception as exc:
        return BuilderReport("ollama", False, None, time.time() - started, f"{type(exc).__name__}: {exc}", [], model=model,
                             details={"steps": sous.steps, "mode": mode,
                                      "deferred_verification_proposals": sous.deferred_verification_proposals})
    details = {"mode": mode, "steps": sous.steps, "step_count": len(sous.steps),
               "max_context_chars": max((s["context_chars"] for s in sous.steps), default=0),
               "total_context_chars": sum(s["context_chars"] for s in sous.steps), "decomposition": "grey-matter-task-division/1",
               "deferred_verification_proposals": sous.deferred_verification_proposals}
    return BuilderReport("ollama", bool(changed), 0 if changed else 1, time.time() - started,
                         f"{plan_summary[:600]} | files: {', '.join(changed)}", changed, model=model, details=details)


__all__ = ["SousChef", "ollama_builder", "ollama_available", "host_url", "model_name", "DEFAULT_MODEL", "DEFAULT_HOST"]
