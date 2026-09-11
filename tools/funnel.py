"""Point a tiered swarm of DeepSeek agents at something, get JSON back.

An OPERATOR INSTRUMENT, not a Daedalus subsystem. It borrows exactly two things
from the codebase -- the advisory fan-out lane (bounded, resumable, budget-
guarded, flight-recorded) and the redacting `.env` loader -- and adds no
control plane, no state store, and no path into the product. Its output is a
pile of model opinions for a human to read, never evidence and never a gate.

WHAT A TIER IS
--------------
A funnel is a list of tiers in a json spec. Each tier says where its inputs
come from, which system prompt file it uses, and how many units it splits into.
Wide tiers observe; narrow tiers synthesise, attack, and plan. The tiers ask
STRUCTURALLY DIFFERENT questions -- that is the only reason a funnel beats its
own widest layer. Four hundred agents all asked the same thing is one agent
with a budget problem.

SOURCE KINDS
------------
code_chunks       every file matching a glob, split into chunk_lines pieces
document_sections one file split on markdown headings, crossed with `lenses`
tier              the previous tier's `handoff` payloads, dealt round-robin
                  into `buckets`; `field` picks a list out of each payload and
                  `drop_where` filters it (that is how refuted findings stop)

WHAT MADE THE DIFFERENCE (measured 2026-07-30)
----------------------------------------------
An earlier fan-out over this codebase returned 715 answers, 713 of them "no
defect found". Same provider, same repo; two focused agents found ten real
defects the same day. Every cause was a property of the REQUEST, and each one
is designed out here:

* the default system prompt forbade the scratchpad -> every tier ships its own
  via system_override, and each says THINK BEFORE YOU ANSWER;
* the worked example ended in `"risks": []`, demonstrating the empty answer ->
  the examples here are populated and the default report template is never
  sent;
* silence was free -> output length is made a function of the INPUT (one row
  per symbol, per claim, per hypothesis), so a clean unit still costs a full
  answer;
* the unit's source was sent twice, the second time truncated -> `paths=()`,
  the text is placed in the objective exactly once;
* three votes at temperature 0.0 were one sample counted three times -> units
  differ by construction, votes stay at 1, temperature defaults to 0.7;
* the cache key carried no prompt identity -> task ids bind tier, unit, and
  revision.

A rerun of the plan-critique funnel under these rules: 102/102 answers, 102
distinct prompts, 102 distinct bodies, 7.6 findings per answer.

WHERE THE ANSWER SURVIVES
-------------------------
`providers/_report.coerce_report` rebuilds every report from a fixed key set and
discards the rest; `schemas.validate_report` caps `summary` at 600 characters.
Only `risks`, `todos` and `handoff` are unbounded, so every prompt file here
puts its structured payload in `handoff` and treats `summary` as a label.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.foundation.env import load_env  # noqa: E402
from daedalus.lanes.fanout import FanoutTask, fan_out  # noqa: E402

FUNNELS = Path("funnels")
RUNS = Path("runs/funnel")
#: What the ledger charges per advisory call BEFORE the answer exists. A
#: deliberate over-estimate, so any projection from it is a ceiling.
WORST_CASE_USD_PER_CALL = 0.05


# --------------------------------------------------------------------------
# budget: refuse at the door, never once per unit over the wire
# --------------------------------------------------------------------------
def budget_state():
    try:
        from daedalus.budget import ledger
        return ledger().state()
    except Exception:
        return None


def budget_verdict(state, calls: int) -> str:
    need = calls * WORST_CASE_USD_PER_CALL
    bad = []
    if state.period_ceiling_enabled and need > state.remaining_usd:
        bad.append(f"needs ${need:.2f} worst-case, ${state.remaining_usd:.2f} left")
    if (state.billable_call_ceiling_enabled
            and state.calls + calls > state.max_calls):
        bad.append(f"needs {calls} calls, {state.max_calls - state.calls} left "
                   "on the call axis")
    allowed = (
        f"YES (${need:.2f} worst-case fits)"
        if state.period_ceiling_enabled
        else f"YES (${need:.2f} recorded; period USD ceiling uncapped)"
    )
    return (allowed if not bad
            else "NO -- " + "; ".join(bad))


def budget_summary(state) -> str:
    period_limit = (
        f"${state.ceiling_usd:.2f}"
        if state.period_ceiling_enabled else "uncapped"
    )
    call_limit = (
        f"{state.calls} of {state.max_calls} calls"
        if state.billable_call_ceiling_enabled
        else f"{state.calls} calls recorded, call ceiling disabled"
    )
    return f"${state.spent_usd:.2f} of {period_limit}, {call_limit}"


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------
def _tracked(glob: str | Sequence[str]) -> list[Path]:
    """Tracked files matching one pathspec, or several.

    A list is not sugar. A funnel aimed at one day's work spans daedalus/,
    tests/ and tools/, and no single pathspec selects that set without also
    dragging in everything else under those trees -- which would silently
    change what the run measured. `git ls-files` takes many pathspecs; the
    only reason this took one was that nothing had needed two yet.
    """
    globs = [glob] if isinstance(glob, str) else list(glob)
    if not globs:
        return []
    out = subprocess.run(["git", "ls-files", *globs],
                         capture_output=True, text=True).stdout
    seen: dict[str, None] = {}
    for p in out.splitlines():
        if p.strip():
            seen.setdefault(p, None)
    return [Path(p) for p in seen]


_DEF = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.MULTILINE)
_IMPORTED = re.compile(r"^\s*(?:from\s+[\w.]+\s+)?import\s+(.+)$", re.MULTILINE)


def _file_scope(text: str) -> str:
    """Every name the whole file defines or imports, for a chunk that sees part.

    MEASURED on the 500-run: the four highest-ranked grounded plan items were
    all "symbol X is referenced but never defined" -- and all four were wrong.
    `_refuse_primary_checkout`, `_body_sha`, `_entry_sha` and `lane_for_host`
    are every one of them defined in the repository; the scanner simply could
    not see the definition, because it was in a different 120-line window of
    the same file.

    Chunking destroys module scope, and a reader who cannot see a definition
    reasonably concludes there is none. Smaller chunks make it worse, which is
    why the 500-run produced more of this than the 253-run. The fix is not a
    warning in the prompt but the missing fact: hand every chunk the names the
    rest of its own file provides.
    """
    names = sorted(set(_DEF.findall(text)))
    imported: set[str] = set()
    for clause in _IMPORTED.findall(text):
        for part in clause.split(","):
            name = part.strip().split(" as ")[-1].strip().strip("()")
            if name.isidentifier():
                imported.add(name)
    return (
        "NAMES DEFINED ELSEWHERE IN THIS SAME FILE (you are seeing one window "
        "of it): " + (", ".join(names) or "(none)") + "\n"
        "NAMES IMPORTED BY THIS FILE: " + (", ".join(sorted(imported)) or "(none)")
        + "\nA name in either list EXISTS. Do not report it as undefined, "
        "missing, or unimported -- you are looking at part of the file, and "
        "absence from your window is not absence from the program."
    )


def code_chunks(cfg: dict) -> list[dict]:
    size = int(cfg.get("chunk_lines", 280))
    scope = bool(cfg.get("file_scope", True))
    units = []
    for path in _tracked(cfg.get("glob", "**/*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        if not lines:
            continue
        header = _file_scope(text) if scope else ""
        total = (len(lines) + size - 1) // size
        for i in range(total):
            body = "\n".join(lines[i * size:(i + 1) * size])
            units.append({
                "id": f"{path.as_posix().replace('/', '_')}__c{i+1}of{total}",
                "label": f"{path.as_posix()} [{i+1}/{total}]",
                "body": (f"{header}\n\n{body}" if header and total > 1 else body),
                "vars": {"module": path.as_posix(), "index": i + 1,
                         "total": total, "first_line": i * size + 1},
            })
    return units


def document_sections(cfg: dict) -> list[dict]:
    text = Path(cfg["path"]).read_text(encoding="utf-8")
    level = cfg.get("split_on", "## ")
    parts = re.split(rf"^{re.escape(level)}", text, flags=re.MULTILINE)
    sections = []
    for chunk in parts[1:]:
        heading, _, body = chunk.partition("\n")
        slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:40]
        sections.append((slug or "section", f"{level}{heading}\n{body}".rstrip()))
    if cfg.get("whole_document", True):
        sections.append(("WHOLE-DOCUMENT", text))
    lenses = cfg.get("lenses") or [{"name": "review", "instruction": ""}]
    units = []
    for slug, body in sections:
        for lens in lenses:
            units.append({
                "id": f"{slug}__{lens['name']}",
                "label": f"{slug} / {lens['name']}",
                "body": body,
                "vars": {"section": slug, "lens": lens["name"],
                         "lens_instruction": lens.get("instruction", "")},
            })
    return units


def _handoffs(tier_dir: Path, rev: str = "") -> list[dict]:
    """One tier's payloads, from EXACTLY ONE run.

    A run directory accumulates. `fan_out` resumes by task id, a task id
    carries the revision, so a rerun of the same funnel lands beside the
    previous one instead of replacing it -- which is correct, the older run is
    evidence. But a tier that reads the whole directory then consumes every run
    at once, and that is silently wrong in four ways at the same time:

    * yield inflates on every rerun, because old rows are re-counted as new;
    * stale hypotheses are re-judged against a NEWER tree, so a finding that
      was true at its own revision is refuted by code written afterwards;
    * bucket size grows run over run, so cost per unit rises with no signal;
    * no two runs can be compared, because the later one contains the earlier.

    MEASURED 2026-07-31 on `runs/funnel/claims123`, three runs deep: the review
    tier's buckets carried 3, then 17, then 36 inputs, and the third run's plan
    tier was handed 161 verdict rows of which 98 were its own. The third run
    looked like the best one and was mostly reading the first two.

    So: exactly one revision, never the union. The current one when it has
    data; otherwise the newest that does, said out loud, because running a
    later tier against an earlier tier's older run is a legitimate thing to do
    deliberately and a trap to do by accident.
    """
    rows: list[dict] = []
    if not tier_dir.is_dir():
        return rows
    units = []
    for p in sorted(tier_dir.iterdir()):
        if p.suffix != ".json":
            continue
        try:
            units.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    if not units:
        return rows

    present: dict[str, float] = {}
    for p, o in units:
        r = str((o.get("meta") or {}).get("rev") or "")
        present[r] = max(present.get(r, 0.0), p.stat().st_mtime)
    chosen = rev if rev in present else max(present, key=lambda r: present[r])
    if len(present) > 1:
        others = ", ".join(sorted(r for r in present if r != chosen))
        print(f"    {tier_dir.name}: {len(present)} runs on disk; reading "
              f"'{chosen}' only (ignoring {others}). A union would re-count "
              "old rows as new.", file=sys.stderr)
    if chosen != rev and rev:
        print(f"    {tier_dir.name}: nothing at the current revision '{rev}' "
              f"-- falling back to the newest run present, '{chosen}'.",
              file=sys.stderr)

    for _, o in units:
        if str((o.get("meta") or {}).get("rev") or "") != chosen:
            continue
        for a in (o.get("answers") or []):
            h = (a.get("report") or {}).get("handoff") or {}
            if h:
                rows.append({"meta": o.get("meta") or {}, "handoff": h})
    return rows


def _deal(items: list, buckets: int) -> list[list]:
    """Round-robin, so one bucket never receives one file's chunks only."""
    out: list[list] = [[] for _ in range(max(1, buckets))]
    for i, item in enumerate(items):
        out[i % len(out)].append(item)
    return [b for b in out if b]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", str(text).lower()) if len(w) > 2}


def _merge_near_duplicates(items: list[dict], key: str,
                           threshold: float = 0.6) -> list[dict]:
    """Collapse items whose `key` text overlaps, KEEPING the multiplicity.

    Two tiers below, a hypothesis raised independently by four research
    buckets and a hypothesis raised once look identical unless somebody says
    so. Reviewing all four also pays four times for one verdict.

    Neither extreme is right. Dropping the duplicates throws away the only
    independent-rediscovery signal the funnel produces; keeping them launders
    one idea into four votes. So: merge, and hand the reviewer the count. It
    can then weigh "four buckets found this without seeing each other" without
    being told four different agents agreed.
    """
    groups: list[list[dict]] = []
    signatures: list[set[str]] = []
    for item in items:
        sig = _words(item.get(key, ""))
        placed = False
        for i, other in enumerate(signatures):
            union = sig | other
            if union and len(sig & other) / len(union) >= threshold:
                groups[i].append(item)
                signatures[i] = other | sig
                placed = True
                break
        if not placed:
            groups.append([item])
            signatures.append(sig)

    merged = []
    for group in groups:
        head = dict(group[0])
        head["raised_independently_by"] = len(group)
        if len(group) > 1:
            head["other_phrasings"] = [str(o.get(key, "")) for o in group[1:4]]
        merged.append(head)
    return merged


_EVIDENCE_REF = re.compile(
    r"\b((?:daedalus|tools|tests|docs|apps|funnels|templates)/"
    r"(?:[\w.\-]+/)*[\w.\-]+\.\w{1,4})(?::([\w.]+))?")


def attach_evidence(items: list[dict], field: str, max_refs: int = 4,
                    window: int = 40) -> list[dict]:
    """Resolve each item's cited references and attach the REAL source.

    Without this, a review tier is asked to attack a claim about code it has
    never seen. It can only weigh the claim's prose against its own priors,
    which is how a confident sentence survives review and a badly-worded true
    finding dies. The reviewer needs the thing itself.

    Attaching the source also makes an invented citation obvious at exactly
    the moment it matters: a reference that resolves to nothing arrives at the
    reviewer as `NOT FOUND IN REPOSITORY`, and a hypothesis whose evidence
    does not exist is one the reviewer can kill without further thought.
    """
    out = []
    for item in items:
        blob = json.dumps(item.get(field) or item, ensure_ascii=False)
        seen, excerpts = set(), []
        for path, symbol in _EVIDENCE_REF.findall(blob):
            if (path, symbol) in seen or len(excerpts) >= max_refs:
                continue
            seen.add((path, symbol))
            p = Path(path)
            if not p.is_file():
                excerpts.append(f"--- {path} : NOT FOUND IN REPOSITORY ---")
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            if symbol and not symbol.isdigit():
                hit = next((i for i, ln in enumerate(lines)
                            if re.search(rf"\b{re.escape(symbol)}\b", ln)), None)
                if hit is None:
                    excerpts.append(
                        f"--- {path} : symbol '{symbol}' NOT PRESENT IN FILE ---")
                    continue
            elif symbol:
                hit = max(0, int(symbol) - 1)
            else:
                hit = 0
            lo, hi = max(0, hit - window // 4), min(len(lines), hit + window)
            body = "\n".join(f"{n:>5}| {lines[n-1]}" for n in range(lo + 1, hi + 1))
            excerpts.append(f"--- {path} lines {lo+1}-{hi} ---\n{body}")
        merged = dict(item)
        if excerpts:
            merged["cited_source"] = "\n".join(excerpts)
        out.append(merged)
    return out


def _norm(value: object) -> str:
    """One spelling per verdict: upper-cased, separators folded to underscore.

    `drop_where` is an exact-match filter, so every spelling a model can emit
    is a hole in it. Lower-casing alone was not enough, MEASURED: the review
    tier returned `needs-evidence` 20 times and `NEEDS_EVIDENCE` 14 times in
    one run -- one verdict, two spellings, and `.lower()` folds neither into
    the other because the separator differs, not the case.

    The two spellings were not the model being careless. The system prompt
    wrote `needs-evidence` and the task example wrote `NEEDS_EVIDENCE`; each
    bucket obeyed one of them. The prompts have since been made to agree, and
    this stays anyway: a filter that silently fails open is worth more
    robustness than it costs.

    `tools/funnel_report.normalize` folds identically on purpose. If they ever
    disagree, a row this filter drops will still be counted by the report, or
    the reverse.
    """
    return re.sub(r"[\s\-]+", "_", str(value).strip()).upper()


def _rows_for(handoff: dict, field: str) -> list:
    """`field` from the payload, or from wherever the harness had to park it.

    `providers/_report.coerce_report` moves keys the schema refused into
    `handoff.unexpected_keys` rather than dropping them, and a model sometimes
    wraps its whole payload in one extra `handoff` layer. Reading only the
    plain field discards the first case; reading all three naively double-counts
    the second, whose copy is normally identical. So: all three, de-duplicated.
    """
    if not isinstance(handoff, dict):
        return []
    sources = [handoff]
    for extra in (handoff.get("unexpected_keys"), handoff.get("handoff")):
        if isinstance(extra, dict):
            sources.append(extra)
    out, seen = [], set()
    for source in sources:
        for row in (source.get(field) or []) if isinstance(
                source.get(field), list) else []:
            key = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
            if key not in seen:
                seen.add(key)
                out.append(row)
    return out


def from_tier(cfg: dict, run_dir: Path, rev: str = "") -> list[dict]:
    rows = _handoffs(run_dir / cfg["from"], rev)
    field = cfg.get("field")
    if field:
        items = [x for r in rows for x in _rows_for(r["handoff"], field)]
    else:
        items = [{"source": r["meta"].get("label") or r["meta"].get("unit"),
                  "report": r["handoff"]} for r in rows]

    # A tier may declare the closed set of values its prompt actually states.
    # Anything outside it is not merely untidy: `drop_where` cannot see it, so
    # a row the funnel meant to stop walks through. MEASURED: one scan row came
    # back "PARTIALLY KEPT" against a stated vocabulary of KEPT/BROKEN/
    # UNCHECKABLE, and `drop_where: {"verdict": ["KEPT"]}` passed it downstream.
    vocab = {_norm(v) for v in (cfg.get("vocabulary") or [])}
    key_field = cfg.get("vocabulary_field", "verdict")
    if vocab:
        stray = {}
        for x in items:
            if isinstance(x, dict) and x.get(key_field) is not None:
                value = _norm(x[key_field])
                if value not in vocab:
                    stray[value] = stray.get(value, 0) + 1
        if stray:
            print(f"    OUTSIDE the declared vocabulary for '{key_field}': "
                  + ", ".join(f"{v} x{n}" for v, n in sorted(stray.items()))
                  + " -- these pass every drop_where rule untouched",
                  file=sys.stderr)

    drop = cfg.get("drop_where") or {}
    for key, bad_values in drop.items():
        bad = {_norm(v) for v in bad_values}
        before = len(items)
        items = [x for x in items
                 if not (isinstance(x, dict) and _norm(x.get(key, "")) in bad)]
        print(f"    drop_where {key} in {sorted(bad)}: "
              f"{before} -> {len(items)} ({before - len(items)} dropped)",
              file=sys.stderr)

    dedupe_on = cfg.get("dedupe_on")
    if dedupe_on and items and isinstance(items[0], dict):
        before = len(items)
        items = _merge_near_duplicates(
            items, dedupe_on, float(cfg.get("dedupe_threshold", 0.6)))
        print(f"    dedupe on '{dedupe_on}': {before} -> {len(items)} "
              f"({before - len(items)} merged, multiplicity retained)",
              file=sys.stderr)

    if cfg.get("attach_evidence"):
        items = attach_evidence(items, cfg.get("evidence_field", "evidence"),
                                int(cfg.get("evidence_refs", 4)),
                                int(cfg.get("evidence_window", 40)))
        n_src = sum(1 for x in items if isinstance(x, dict) and x.get("cited_source"))
        print(f"    attached real source to {n_src}/{len(items)} items",
              file=sys.stderr)

    units = []
    for n, bucket in enumerate(_deal(items, int(cfg.get("buckets", 10))), start=1):
        units.append({
            "id": f"b{n:03d}",
            "label": f"bucket {n} ({len(bucket)} inputs)",
            "body": json.dumps(bucket, ensure_ascii=False, indent=1),
            "vars": {"bucket": n, "inputs": len(bucket)},
        })
    return units


SOURCES = {
    "code_chunks": lambda cfg, run_dir, rev: code_chunks(cfg),
    "document_sections": lambda cfg, run_dir, rev: document_sections(cfg),
    "tier": from_tier,
}


# --------------------------------------------------------------------------
# the funnel
# --------------------------------------------------------------------------
def load_spec(name: str) -> tuple[dict, Path]:
    base = Path(name)
    if not base.is_dir():
        base = FUNNELS / name
    spec_path = base / "funnel.json"
    return json.loads(spec_path.read_text(encoding="utf-8")), base


def repo_index(globs: Sequence[str], with_symbols: bool = False) -> str:
    """The real file tree, so a tier that must name a file can look one up.

    MEASURED: 29% of the plan tier's cited paths named a file that exists
    nowhere in the repository. The tier was not lying for sport -- its output
    schema requires a `file` for every step, it receives only prose verdicts,
    and a step without a path is not a step. Given no way to look anything up,
    it reconstructs what a project like this ought to contain, and produces
    `daedalus/runner.py`.

    A prohibition cannot fix that; the tier has nothing to obey it with. The
    index is the missing capability, not a stricter instruction.
    """
    files: list[str] = []
    for glob in globs:
        files.extend(p.as_posix() for p in _tracked(glob))
    files = sorted(set(files))
    if not with_symbols:
        return ("EVERY FILE IN THIS REPOSITORY (authoritative, current):\n"
                + "\n".join(files)
                + "\n\nYou may name ONLY a path from this list. It is the whole "
                  "truth about what exists; a path you do not find here does "
                  "not exist, however natural it looks.")
    rows = []
    for f in files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names = sorted(set(_DEF.findall(text)))[:24]
        rows.append(f"{f}: " + ", ".join(names) if names else f)
    return ("EVERY FILE IN THIS REPOSITORY AND WHAT IT DEFINES "
            "(authoritative, current):\n" + "\n".join(rows)
            + "\n\nYou may name ONLY a path from this list.")


def build_tasks(tier: dict, base: Path, run_dir: Path, rev: str) -> list[FanoutTask]:
    kind = tier["source"]["kind"]
    units = SOURCES[kind](tier["source"], run_dir, rev)
    index = ""
    if tier.get("repo_index"):
        index = repo_index(tier.get("index_globs") or ["daedalus/**/*.py",
                                                       "tools/*.py",
                                                       "tests/*.py"],
                           with_symbols=bool(tier.get("index_symbols")))
    template = tier.get("task", "")
    intro = tier.get("intro", "")
    fence = tier.get("fence", "INPUT")
    tasks = []
    for u in units:
        head = intro.format(**u["vars"]) if intro else u["label"]
        body_note = template.format(**u["vars"]) if template else ""
        objective = (
            f"{head}\n\n"
            + (f"=== REPOSITORY INDEX ===\n{index}\n=== END INDEX ===\n\n"
               if index else "")
            + f"=== {fence} (verbatim) ===\n{u['body']}\n=== END {fence} ===\n\n"
            + body_note
        )
        tasks.append(FanoutTask(
            task_id=f"{tier['name']}__{u['id']}__{rev}",
            objective=objective, paths=(), votes=1,
            meta={"tier": tier["name"], "label": u["label"], "rev": rev,
                  **u["vars"]}))
    return tasks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="tools.funnel",
        description="Run a tiered DeepSeek funnel defined by funnels/<name>/funnel.json")
    ap.add_argument("funnel", help="funnel name under funnels/, or a directory")
    ap.add_argument("--run", action="store_true", help="actually spend")
    ap.add_argument("--tier", default="", help="run only this tier")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--limit", type=int, default=0, help="first N units per tier")
    ap.add_argument("--out", default="", help="override the run directory")
    args = ap.parse_args(argv)

    load_env()
    spec, base = load_spec(args.funnel)
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip() or "nogit"
    run_dir = Path(args.out) if args.out else RUNS / spec["name"]
    tiers = [t for t in spec["tiers"] if not args.tier or t["name"] == args.tier]

    if not args.run:
        print(f"funnel      : {spec['name']} -- {spec.get('description', '')}")
        print(f"revision    : {rev}")
        print(f"run dir     : {run_dir}")
        total = 0
        for tier in tiers:
            try:
                n = len(build_tasks(tier, base, run_dir, rev))
            except (KeyError, OSError) as exc:
                n = 0
                print(f"  {tier['name']:<10} unavailable until its input tier "
                      f"has run ({exc})")
                continue
            n = min(n, args.limit) if args.limit else n
            total += n
            print(f"  {tier['name']:<10} {n:>4} units   "
                  f"<- {tier['source']['kind']}")
        print(f"PROJECTED CALLS (tiers that can be planned now): {total}")
        st = budget_state()
        if st:
            print(f"budget      : {budget_summary(st)}")
            print(f"CAN THIS RUN: {budget_verdict(st, total)}")
        print("\nno calls made. add --run to spend.")
        return 0

    # The projection above stays fail-open; tiered spending starts at the
    # central boundary with the really-installed spend net.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.funnel",
        REGISTRY_BY_ID["tools.funnel"].effects,
        (process_guard_boundary_decision(),),
    )
    for tier in tiers:
        system = (base / tier["system"]).read_text(encoding="utf-8")
        tasks = build_tasks(tier, base, run_dir, rev)
        if args.limit:
            tasks = tasks[: args.limit]
        if not tasks:
            print(f"[{tier['name']}] no units -- the tier above produced nothing "
                  "usable", file=sys.stderr)
            return 4
        st = budget_state()
        if st:
            verdict = budget_verdict(st, len(tasks))
            if verdict.startswith("NO"):
                print(f"[{tier['name']}] budget refuses: {verdict}\n"
                      "Raise DAEDALUS_BUDGET_USD *and* DAEDALUS_BUDGET_MAX_CALLS "
                      "deliberately -- they are independent axes.", file=sys.stderr)
                return 3
        print(f"\n=== TIER {tier['name']}: {len(tasks)} units ===", flush=True)
        summary = fan_out(tasks, run_dir / tier["name"], repo_root=".",
                          concurrency=args.concurrency, timeout_s=args.timeout,
                          system_override=system, temperature=args.temperature,
                          graph_hops=0, resume=True)
        print(json.dumps({k: v for k, v in summary.items() if k != "results"},
                         indent=1, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
