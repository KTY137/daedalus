"""The Chef: one order in, one nominated candidate (or an honest failure) out.

Pipelines (all through the same kitchen contracts):

* ``build_app``      -- Genesis: spec → builder agent in a fresh candidate
                        workspace → toolchain checks → bounded repair → CAS
                        identity → Grey Matter ingest → evidence → NOMINATION.
* ``improve_app``    -- Renovation: detached git worktree of the project →
                        builder agent → checks → ``candidate.patch`` → evidence
                        → NOMINATION. The primary checkout is never touched.
* ``self_improve``   -- Renovation of Daedalus itself with the §8.1 leakage
                        boundary: a candidate that touches the spine, kernel
                        policy, plan, amendment chain, AGENTS.md or its own
                        evaluator's tests is rejected and retained as negative
                        evidence.
* ``feed_ariadne``   -- corpus ingestion: clone/copy repositories with
                        provenance, compile Node Cards, embeddings, relation
                        tensor and binding proposals into Grey Matter.

Nothing here merges, publishes or promotes. ``automatic_promotion`` is False
in every packet; promotion stays with the owner-controlled path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .builders import BuilderFn, BuilderReport, BuilderUnavailable, DEFAULT_TIMEOUT_S, run_builder
from .toolchain import (DEFAULT_STEP_TIMEOUT_S, MANIFEST, Observation, Plan, detect, failure_digest,
                        freeze_verification, verification_integrity, run_plan, verdict)
from .greymatter import GreyMatter, SKIP_DIRS, source_tree_digest
from .ledger import (OrderLedger, STATUS_BLOCKED, STATUS_COOKING, STATUS_DONE, STATUS_FAILED, STATUS_NOMINATED)
from .orders import KIND_BUILD, KIND_FEED, KIND_IMPROVE, KIND_SELF, Order

MAX_REPAIRS = int(os.environ.get("DAEDALUS_KITCHEN_MAX_REPAIRS", "2"))
BUILDER_TIMEOUT_S = int(os.environ.get("DAEDALUS_KITCHEN_BUILDER_TIMEOUT_S", str(DEFAULT_TIMEOUT_S)))
STEP_TIMEOUT_S = int(os.environ.get("DAEDALUS_KITCHEN_STEP_TIMEOUT_S", str(DEFAULT_STEP_TIMEOUT_S)))
EVIDENCE_SCHEMA = "daedalus-kitchen-evidence/1"

# Masterplan §8.1 leakage boundary for self-Renovation candidates.
PROTECTED_PREFIXES = ("daedalus/spine/", "daedalus/kernel/policy/", "daedalus/kernel/contracts/",
                      "docs/IKARUS_ARIADNE_MASTER_PLAN", "AGENTS.md", "CLAUDE.md", ".agentenv/",
                      "daedalus/orchestration/ikarus/kitchen/chef.py", "tests/orchestration/test_ikarus_kitchen.py")

_LOG = Callable[[str], None]


@dataclass
class Kitchen:
    """Where the kitchen keeps state. Everything under ``root`` is regenerable."""

    root: Path
    ledger: OrderLedger = field(init=False)
    grey: GreyMatter = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        for name in ("candidates", "worktrees", "corpus", "orders"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.ledger = OrderLedger(self.root / "orders.db")
        self.grey = GreyMatter(self.root / "greymatter.db")

    def close(self) -> None:
        self.ledger.close()
        self.grey.close()


def default_kitchen_root(repo_root: str | Path | None = None) -> Path:
    """Where the kitchen keeps corpus clones, candidates, worktrees and ledgers.

    Outside every repository tree on purpose: cloned corpus code and candidate
    workspaces are not Daedalus sources, must not enter its entrypoint
    discovery or history scans, and are regenerable. ``DAEDALUS_KITCHEN_ROOT``
    overrides; ``repo_root`` only names the project the kitchen serves.
    """
    override = os.environ.get("DAEDALUS_KITCHEN_ROOT")
    if override:
        return Path(override)
    del repo_root
    return Path.home() / ".daedalus" / "kitchen"


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def tree_digest(root: Path) -> tuple[str, int]:
    """Content-addressed identity of a candidate tree (paths + bytes)."""
    return source_tree_digest(root)


def _git(args: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False)


def _git_bytes(args: list[str], cwd: Path, timeout: int = 300) -> bytes:
    completed = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"git inspection failed (exit {completed.returncode}): {args[0]}")
    return completed.stdout


def _git_z(args: list[str], cwd: Path, timeout: int = 120) -> list[str]:
    """NUL-separated git output decoded as UTF-8 paths; never C-quoted."""
    raw = _git_bytes(args, cwd, timeout)
    return [part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\0") if part]


def _head(repo: Path) -> str | None:
    result = _git(["rev-parse", "HEAD"], repo, 30)
    return result.stdout.strip() if result.returncode == 0 else None


def _slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:limit] or "candidate").strip("-")


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return hashlib.sha256(data).hexdigest()
    with path.open("xb") as stream:
        stream.write(data)
    return hashlib.sha256(data).hexdigest()


def _language_line(order: Order) -> str:
    return ("Antworte und dokumentiere auf Deutsch; Code, Bezeichner und Kommentare auf Englisch."
            if order.language == "de" else "Write documentation in English.")


# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #
def build_prompt(order: Order, workspace: Path, motifs: str) -> str:
    stack = f"Preferred stack: {order.stack}." if order.stack else (
        "No stack was required. Default (Masterplan §7.1): a local-first web application for one user, no login, "
        "no telemetry, no paid services, responsive and WCAG 2.2 AA. Prefer plain HTML/CSS/JavaScript or a small "
        "Vite project; use Python only when the request is clearly a CLI or a service.")
    return f"""You are the Chef's builder inside the Daedalus kitchen. Build a complete, runnable application.

ORDER (verbatim from the owner):
{order.text}

{stack}
{_language_line(order)}

RULES
- Work ONLY inside the current directory ({workspace.name}); it is an empty candidate workspace. Never touch paths outside it.
- Produce a real, working program with a README.md (purpose, how to run, how to test), source code and automated tests.
- Write `{MANIFEST}` at the root with JSON keys: "stack", "install" (optional), "build", "test", "run", "preview" (URL or null). Each command is an argv list, e.g. {{"build": ["npm","run","build"], "test": ["npm","test"], "run": ["npm","run","dev"], "preview": "http://127.0.0.1:5173"}}. For a static site use ["python","-m","http.server","8765","--bind","127.0.0.1"].
- Install dependencies and RUN the build and the tests yourself before you finish; fix what fails. Keep dependencies minimal and pinned via a lockfile when you use npm.
- No network services, no secrets, no telemetry, no external accounts. Local-first storage only.
- Do not initialise git and do not create files outside this directory.
- Finish with a short summary of what you built and how it was verified.

{motifs}
""".strip()


def improve_prompt(order: Order, workspace: Path, motifs: str, *, self_mode: bool) -> str:
    boundary = ""
    if self_mode:
        boundary = ("\nLEAKAGE BOUNDARY (Masterplan §8.1, enforced after you finish): do NOT modify anything under "
                    + ", ".join(PROTECTED_PREFIXES) + ". A candidate that touches them is rejected.")
    return f"""You are the Chef's builder inside the Daedalus kitchen, improving an existing repository checkout.

ORDER (verbatim from the owner):
{order.text}

{_language_line(order)}

RULES
- You are in a detached worktree of the project ({workspace.name}). Edit only inside it. Do not commit, push, merge, or change branches.
- First understand the project (README, tests, structure). Then implement the improvement with focused, complete changes.
- Existing test files, evaluator scripts, test configuration and build/test commands are frozen. Do not add, remove or edit them; repair application source against these unchanged checks.
- If the repository has no usable check command, report that blocker. New evaluator/test proposals require independent admission before execution.
- Do not create or change `{MANIFEST}` or package/toolchain configuration in this repair packet.
- Finish with a short summary: what changed, why, and how it was verified.{boundary}

{motifs}
""".strip()


def repair_prompt(order: Order, failures: str, attempt: int) -> str:
    return f"""Repair round {attempt}. The kitchen ran the build/test commands and they FAILED. Fix the causes inside this directory, re-run the failing commands yourself, and do not remove or weaken tests to make them pass.

ORDER (for context):
{order.text}

FAILURES:
{failures[-9000:]}
""".strip()


# --------------------------------------------------------------------------- #
# The Chef                                                                     #
# --------------------------------------------------------------------------- #
class Chef:
    def __init__(self, kitchen: Kitchen, *, builder: BuilderFn | None = None,
                 chain: tuple[str, ...] | None = None, max_repairs: int = MAX_REPAIRS) -> None:
        self.kitchen = kitchen
        self.builder = builder
        self.chain = chain
        self.max_repairs = max_repairs

    # -- public --------------------------------------------------------------
    def cook(self, order: Order, *, project: str | None, repo_root: str | None) -> dict[str, Any]:
        ledger = self.kitchen.ledger
        order_id = order.order_id
        existing = ledger.order(order_id)
        if existing and existing.get("project") != project:
            return {"status": STATUS_BLOCKED, "order_id": order_id,
                    "blocker": "order context conflict; existing evidence retained"}
        if existing and existing.get("result") is not None:
            return existing["result"]
        log = lambda text, level="info": ledger.event(order_id, text, level)  # noqa: E731
        ledger.set_status(order_id, STATUS_COOKING)
        started = time.time()
        try:
            if order.kind == KIND_BUILD:
                result = self._build(order, log)
            elif order.kind == KIND_IMPROVE:
                result = self._improve(order, repo_root, log, self_mode=False)
            elif order.kind == KIND_SELF:
                result = self._improve(order, str(Path(__file__).resolve().parents[4]), log, self_mode=True)
            elif order.kind == KIND_FEED:
                result = self._feed(order, repo_root, log)
            else:
                raise ValueError(f"the Chef has no pipeline for {order.kind}")
        except BuilderUnavailable as exc:
            result = {"status": STATUS_BLOCKED, "blocker": str(exc), "order_id": order_id}
            log(f"blocked: {exc}", "error")
        except Exception as exc:  # the order fails honestly; nothing is hidden
            result = {"status": STATUS_FAILED, "error": f"{type(exc).__name__}: {exc}", "order_id": order_id}
            log(f"failed: {type(exc).__name__}: {exc}", "error")
        result.setdefault("order_id", order_id)
        result.setdefault("project", project)
        result["seconds"] = round(time.time() - started, 2)
        result["automatic_promotion"] = False
        result["owner_approval_required"] = result.get("status") == STATUS_NOMINATED
        ledger.set_status(order_id, result["status"], result)
        log(f"finished with status {result['status']}")
        return result

    # -- build --------------------------------------------------------------
    def _build(self, order: Order, log: _LOG) -> dict[str, Any]:
        workspace = self.kitchen.root / "candidates" / f"{_slug(order.text)}-{order.order_id[-8:]}"
        workspace.mkdir(parents=True, exist_ok=False)
        log(f"candidate workspace created: {workspace.name}")
        motifs = self.kitchen.grey.motif_context(order.text)
        log("grey matter retrieval: " + (f"{motifs.count(chr(10))} motifs" if motifs else "corpus empty, no motifs"))
        reports = [self._run_builder(workspace, build_prompt(order, workspace, motifs), log, order=order, mode="build")]
        plan, observations, green, rounds = self._check_and_repair(order, workspace, reports, log)
        return self._nominate(order, workspace, reports, plan, observations, green, log,
                              base_revision=None, patch=None, verification_rounds=rounds)

    # -- improve ------------------------------------------------------------
    def _improve(self, order: Order, repo_root: str | None, log: _LOG, *, self_mode: bool) -> dict[str, Any]:
        if not repo_root:
            raise ValueError("an improvement order needs a registered project (repo root unknown)")
        repo = Path(repo_root).resolve()
        if not repo.is_dir():
            raise FileNotFoundError(f"project root missing: {repo}")
        base = _head(repo)
        workspace = self.kitchen.root / "worktrees" / f"{_slug(repo.name)}-{order.order_id[-8:]}"
        if workspace.exists():
            raise FileExistsError(f"existing candidate retained: {workspace}")
        if base:
            added = _git(["worktree", "add", "--detach", str(workspace), "HEAD"], repo, 300)
            if added.returncode != 0:
                raise RuntimeError(f"git worktree add failed: {added.stderr.strip()[:500]}")
            log(f"detached worktree at {base[:12]} created: {workspace.name}")
        else:
            shutil.copytree(repo, workspace, ignore=shutil.ignore_patterns(*SKIP_DIRS, ".git"))
            log(f"non-git project copied into {workspace.name}")
        base_plan = detect(workspace)
        frozen = freeze_verification(base_plan, workspace)
        motifs = self.kitchen.grey.motif_context(order.text)
        reports = [self._run_builder(workspace, improve_prompt(order, workspace, motifs, self_mode=self_mode), log, order=order, mode="improve")]
        leak = self._leak(workspace, base) if self_mode else []
        if leak:
            log(f"leakage boundary violated by {len(leak)} path(s); candidate rejected", "error")
            return self._reject(order, workspace, reports, leak, base)
        plan, observations, green, rounds = self._check_and_repair(
            order, workspace, reports, log, plan=base_plan, frozen=frozen)
        # Repair rounds are builder passes too: the boundary holds for the tree
        # that is nominated, not for the first draft only.
        leak = self._leak(workspace, base) if self_mode else []
        if leak:
            log(f"leakage boundary violated during repair by {len(leak)} path(s); candidate rejected", "error")
            return self._reject(order, workspace, reports, leak, base)
        changed = self._changed_paths(workspace, base)
        patch = None
        if base:
            untracked = [p for p in _git_z(["ls-files", "-z", "--others", "--exclude-standard"], workspace)
                         if not p.startswith(".kitchen-") and "__pycache__" not in p]
            if untracked:
                _git(["add", "-N", "--", *untracked], workspace, 120)
            diff = _git_bytes(["diff", "--binary", "HEAD", "--", ".", ":(exclude).kitchen-plan.json", ":(exclude)**/__pycache__/**"], workspace, 300)
            patch = self.kitchen.root / "orders" / f"{order.order_id}.patch"
            with patch.open("xb") as stream:
                stream.write(diff)  # preserve CRLF and previous candidate evidence
            log(f"candidate patch written ({len(diff)} bytes, {len(changed)} paths)")
        return self._nominate(order, workspace, reports, plan, observations, green, log,
                              base_revision=base, patch=patch, verification_rounds=rounds)

    def _changed_paths(self, workspace: Path, base: str | None) -> list[str]:
        """Every modified or untracked path, NUL-separated so git never C-quotes it."""
        if not base:
            return []
        entries = _git_z(["status", "--porcelain=v1", "-z", "--untracked-files=all"], workspace)
        paths: list[str] = []
        skip_next = False
        for entry in entries:
            if skip_next:  # removal of the original path is part of the candidate too
                paths.append(entry.replace("\\", "/"))
                skip_next = False
                continue
            if len(entry) < 4:
                continue
            code, path = entry[:2], entry[3:].replace("\\", "/")
            skip_next = "R" in code or "C" in code
            if path.startswith(".kitchen-") or "__pycache__" in path:
                continue  # kitchen bookkeeping and compiled caches are not candidate content
            paths.append(path)
        return sorted(set(paths))

    def _leak(self, workspace: Path, base: str | None) -> list[str]:
        return [p for p in self._changed_paths(workspace, base) if p.startswith(PROTECTED_PREFIXES)]

    def _reject(self, order: Order, workspace: Path, reports: list[BuilderReport], leak: list[str],
                base: str | None) -> dict[str, Any]:
        digest, files = tree_digest(workspace)
        packet = {"schema": EVIDENCE_SCHEMA, "order": order.to_dict(), "status": STATUS_FAILED,
                  "rejection": "leakage_boundary", "protected_paths_touched": leak, "base_revision": base,
                  "candidate_tree_sha256": digest, "files": files, "builder_reports": [r.to_dict() for r in reports],
                  "automatic_promotion": False, "negative_evidence_retained": True}
        sha = _write_json(self.kitchen.root / "orders" / f"{order.order_id}.evidence.json", packet)
        return {"status": STATUS_FAILED, "rejection": "leakage_boundary", "protected_paths_touched": leak,
                "candidate_tree_sha256": digest, "evidence_sha256": sha, "workspace": str(workspace)}

    # -- feed ----------------------------------------------------------------
    def _feed(self, order: Order, repo_root: str | None, log: _LOG) -> dict[str, Any]:
        sources = list(order.sources)
        if not sources:
            # Ingestion is an effect on the corpus; it happens only for a source
            # the owner named, never for a project inferred from the chat.
            log("feed order names no repository URL or path; nothing ingested", "warn")
            return {"status": STATUS_BLOCKED,
                    "blocker": "name the repository to feed (a URL or an existing path), e.g. "
                               "'füttere Ariadne mit https://github.com/org/repo'"}
        allowed = tuple(s.strip().upper() for s in os.environ.get("DAEDALUS_KITCHEN_LICENSE_ALLOW", "").split(",") if s.strip())
        ingested: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for source in sources:
            try:
                root, origin = self._materialise_source(source, log)
                from .greymatter import _license_of
                license_id = _license_of(root)
                if allowed and (license_id or "").upper() not in allowed:
                    skipped.append({"source": source, "reason": f"license {license_id or 'undeclared'} not in allow-list {list(allowed)}"})
                    log(f"skipped {source}: license {license_id or 'undeclared'} not allowed", "warn")
                    continue
                report = self.kitchen.grey.ingest_repo(root, origin=origin, provenance={"order_id": order.order_id})
            except Exception as exc:  # one bad repository never starves the corpus of the others
                skipped.append({"source": source, "reason": f"{type(exc).__name__}: {str(exc)[:300]}"})
                log(f"skipped {source}: {type(exc).__name__}: {str(exc)[:200]}", "warn")
                continue
            tensor = self.kitchen.grey.relation_tensor(report["repo_id"])
            report["relation_tensor_sha256"] = tensor["sha256"]
            report["relation_tensor_entries"] = len(tensor["entries"])
            report["cross_plane_edges"] = tensor["cross_plane"]
            _write_json(self.kitchen.root / "corpus" / f"{report['repo_id']}.tensor.json", tensor)
            ingested.append(report)
            log(f"ingested {report['name']}@{report['revision'][:12]}: {report['cards']} cards, {report['edges']} edges, "
                f"{report['proposals']} proposals ({report['verified_bindings']} verified), license={report['license']}")
        stats = self.kitchen.grey.stats()
        status = STATUS_DONE if ingested else STATUS_FAILED
        return {"status": status, "ingested": ingested, "skipped": skipped, "grey_matter": stats}

    def _materialise_source(self, source: str, log: _LOG) -> tuple[Path, str | None]:
        if re.match(r"^(https?://|git@)", source):
            name = _slug(re.sub(r"\.git$", "", source.rstrip("/").rsplit("/", 1)[-1]))
            target = self.kitchen.root / "corpus" / f"{name}-{hashlib.sha256(source.encode()).hexdigest()[:8]}"
            if (target / ".git").exists():
                log(f"corpus repository present, fetching: {name}")
                _git(["fetch", "--depth", "1", "origin"], target, 600)
                _git(["reset", "--hard", "FETCH_HEAD"], target, 120)
            else:
                log(f"cloning {source}")
                cloned = _git(["-c", "core.longpaths=true", "clone", "--depth", "1", source, str(target)], self.kitchen.root, 900)
                if cloned.returncode != 0:
                    shutil.rmtree(target, ignore_errors=True)
                    raise RuntimeError(f"git clone failed for {source}: {cloned.stderr.strip()[:400]}")
            return target, source
        path = Path(source).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"repository path not found: {source}")
        return path, None

    # -- shared -------------------------------------------------------------
    def _run_builder(self, workspace: Path, prompt: str, log: _LOG, *, order: Order | None = None,
                     mode: str = "build") -> BuilderReport:
        # The context lets a tool-less lane (the Ollama Sous-Chef) divide the
        # labour through Grey Matter instead of parsing the agentic prompt.
        context = {"grey": self.kitchen.grey, "order_text": order.text if order else None,
                   "stack": order.stack if order else None, "mode": mode}
        report = run_builder(workspace, prompt, chain=self.chain, timeout_s=BUILDER_TIMEOUT_S,
                                      builder=self.builder, log=log, context=context)
        log(f"builder summary: {report.summary[:600]}")
        return report

    def _check_and_repair(self, order: Order, workspace: Path, reports: list[BuilderReport], log: _LOG,
                          *, plan: Plan | None = None, frozen=None):
        plan = plan or detect(workspace)
        frozen = frozen or freeze_verification(plan, workspace)
        log(f"toolchain detected: {plan.stack} via {plan.source}; steps={[s.name for s in plan.steps]}")
        rounds: list[dict[str, Any]] = []
        for attempt in range(self.max_repairs + 1):
            integrity = verification_integrity(frozen, detect(workspace), workspace)
            observations = [integrity] if integrity else run_plan(plan, workspace, timeout_s=STEP_TIMEOUT_S)
            if integrity is None:
                integrity = verification_integrity(frozen, detect(workspace), workspace)
                if integrity is not None:
                    observations.append(integrity)
            green, failures = verdict(observations)
            rounds.append({"round": attempt, "toolchain": plan.to_dict(), "passed": green,
                           "failures": failures, "observations": [o.to_dict() for o in observations]})
            _write_json(self.kitchen.root / "orders" / f"{order.order_id}.round-{attempt:04d}.json", rounds[-1])
            for o in observations:
                log(f"check {o.name}: {'passed' if o.passed else 'FAILED'} (exit {o.exit_code}, {o.seconds:.1f}s)")
            if green or integrity is not None or attempt == self.max_repairs:
                break
            log(f"repair round {attempt + 1}/{self.max_repairs} for {failures}")
            try:
                report = self._run_builder(workspace, repair_prompt(order, failure_digest(observations), attempt + 1),
                                            log, order=order, mode="repair")
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                report = BuilderReport("unavailable", False, None, 0.0, reason)
                reports.append(report)
                observations = [Observation("repair_builder", [], None, 0.0, False, reason)]
                green = False
                rounds.append({"round": attempt + 1, "toolchain": plan.to_dict(), "passed": False,
                               "failures": ["repair_builder"], "observations": [o.to_dict() for o in observations]})
                _write_json(self.kitchen.root / "orders" / f"{order.order_id}.round-{attempt + 1:04d}.json", rounds[-1])
                break
            reports.append(report)
        return plan, observations, green, rounds

    def _nominate(self, order: Order, workspace: Path, reports: list[BuilderReport], plan: Plan,
                  observations: list[Observation], green: bool, log: _LOG, *, base_revision: str | None,
                  patch: Path | None, verification_rounds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        digest, files = tree_digest(workspace)
        try:
            ingest = self.kitchen.grey.ingest_repo(workspace, name=f"candidate:{workspace.name}",
                                                   source_digest=digest,
                                                   provenance={"order_id": order.order_id, "candidate": True})
            tensor = self.kitchen.grey.relation_tensor(ingest["repo_id"])
            twin = {"repo_id": ingest["repo_id"], "cards": ingest["cards"], "edges": ingest["edges"],
                    "planes": ingest["planes"], "relation_tensor_sha256": tensor["sha256"],
                    "cross_plane_edges": tensor["cross_plane"], "verified_bindings": ingest["verified_bindings"]}
            log(f"candidate twin compiled: {ingest['cards']} cards / {ingest['edges']} edges / tensor {tensor['sha256'][:12]}")
        except Exception as exc:  # the twin is a projection; its failure never hides the candidate
            twin = {"error": f"{type(exc).__name__}: {exc}"}
            green = False
            observations.append(Observation("candidate_twin", [], None, 0.0, False, twin["error"]))
            log("candidate twin failed; candidate retained without nomination", "error")
        if reports and not reports[-1].ok:
            green = False
            observations.append(Observation("builder", [], reports[-1].exit_code, 0.0, False,
                                            "the final builder attempt failed"))
        status = STATUS_NOMINATED if green else STATUS_FAILED
        packet = {"schema": EVIDENCE_SCHEMA, "order": order.to_dict(), "status": status,
                  "candidate": {"workspace": str(workspace), "tree_sha256": digest, "files": files,
                                "digest_algorithm": "sha256-path-content-posix-sort/1",
                                "base_revision": base_revision, "patch": str(patch) if patch else None},
                  "toolchain": plan.to_dict(), "observations": [o.to_dict() for o in observations],
                  "verification_rounds": verification_rounds or [],
                  "builder_reports": [r.to_dict() for r in reports], "candidate_twin": twin,
                  "containment": "deferred (owner decision 2026-09-12): builder agents ran on the host without a candidate sandbox",
                  "automatic_promotion": False, "owner_approval_required": green,
                  "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        sha = _write_json(self.kitchen.root / "orders" / f"{order.order_id}.evidence.json", packet)
        log(f"evidence packet {sha[:12]} written; status={status}")
        return {"status": status, "workspace": str(workspace), "candidate_tree_sha256": digest, "files": files,
                "evidence_sha256": sha, "evidence_path": str(self.kitchen.root / "orders" / f"{order.order_id}.evidence.json"),
                "toolchain": plan.to_dict(), "checks": {o.name: o.passed for o in observations},
                "builder_lanes": [r.lane for r in reports], "repairs": max(0, len(reports) - 1),
                "patch": str(patch) if patch else None, "base_revision": base_revision, "candidate_twin": twin,
                "run": plan.run, "preview": plan.preview}


__all__ = ["Chef", "Kitchen", "default_kitchen_root", "tree_digest", "PROTECTED_PREFIXES", "EVIDENCE_SCHEMA"]
