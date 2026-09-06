"""Retain a list of scratch missions (report, proposals, log) into an evidence directory, paths scrubbed.
usage: retain_runs.py <scratch> <evidence_dir> <mission_id>..."""
import json, sys
from pathlib import Path
S = Path(sys.argv[1]); E = Path(sys.argv[2]); E.mkdir(parents=True, exist_ok=True); home = str(Path.home())
def variants(p):
    p = p.replace("/", "\\"); return [p, p.replace("\\", "\\\\"), p.replace("\\", "/")]
def scrub(t):
    for v in variants(str(S)): t = t.replace(v, "<SCRATCH>")
    for v in variants(home): t = t.replace(v, "<USERPROFILE>")
    return t
rows = []
for m in sys.argv[3:]:
    rep = json.loads((S / f"{m}.json").read_text(encoding="utf-8"))
    props = []
    for p in rep["report"].get("proposals", []):
        b = json.loads((S / "control" / "ikarus-computer-artifacts" / f"{p['sha256']}.json").read_text(encoding="utf-8"))
        props.append({"call": b["planner_call"], "step": b["step"], "sha256": p["sha256"], "response": b["response"],
                      "prompt_chars": b.get("prompt_chars")})
    (E / f"{m}_planner_proposals.json").write_text(scrub(json.dumps(props, indent=1, ensure_ascii=False)), encoding="utf-8", newline="\n")
    (E / f"{m}_report.json").write_text(scrub(json.dumps(rep, indent=1, ensure_ascii=False, default=str)), encoding="utf-8", newline="\n")
    (E / f"{m}.log.txt").write_text(scrub((S / f"{m}.log.txt").read_bytes().decode("utf-8", errors="replace")), encoding="utf-8", newline="\n")
    r = rep["report"]
    rows.append({"mission": m, "state": r.get("state"), "planner_calls": r.get("planner_calls"), "tool_steps": r.get("tool_steps"),
                 "elapsed_s": round(rep.get("elapsed_s", 0), 1), "planner": r.get("planner"),
                 "absent": (r.get("summary_tokens_absent_from_observations") or {}).get("absent"),
                 "prompt_chars_max": r.get("prompt_chars_max"), "summary": (r.get("planner_summary") or "")[:200]})
(E / "summary.json").write_text(scrub(json.dumps(rows, indent=1, ensure_ascii=False)), encoding="utf-8", newline="\n")
for f in E.iterdir():
    assert "nukei" not in f.read_text(encoding="utf-8"), f.name
for r in rows: print(r["mission"], r["state"], r["planner_calls"], r["tool_steps"], r["elapsed_s"], "absent=", r["absent"])
