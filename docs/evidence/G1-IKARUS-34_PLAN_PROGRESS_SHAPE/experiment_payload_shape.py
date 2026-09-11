"""G1-IKARUS-34 (EXPERIMENT): does the shape of plan_progress change whether the 7B finishes?

Pre-registered before the first run. Two variants, five runs each, alternating order, one
process (one loaded source), same page, objective, tools and bounded policy (max_steps 16,
timeout_s 900) as measure-10. Outcome variable: the mission's terminal state reached `finish`
(state == "completed"). Secondary: planner calls, tool steps, terminal state, elapsed seconds.

V1: the committed payload (six views: tool_steps_since_plan, next_step_index, next_step,
    open_steps, every_step_has_a_tool_step; plus advisory_plan).
V2: the plan repeated with a per-step boolean plus next_step only (Momus, 2026-09-06 02:40:
    "stop encoding one integer five ways"); installed by monkeypatching
    computer_loop._plan_progress for the V2 runs. The directive text is identical.
"""
import io, json, os, sys, time
from pathlib import Path

S = Path(os.environ["DAEDALUS_KILLSWITCH"]).parent.parent
subject = S / "subject"
port = io.open(S / "www" / "port.txt").read().strip()
RUNS = int(os.environ.get("RUNS_PER_VARIANT", "5"))

from daedalus.spine.killswitch import KillSwitch
print("killswitch:", KillSwitch(repo_root=subject).arm(force=True, note="G1-IKARUS-34 experiment"), flush=True)
from daedalus.runtimes.computer import computer_status
from daedalus.interfaces.computer_configuration import configure_computer
from daedalus.orchestration.ikarus import computer_loop
from daedalus.orchestration.ikarus.computer_loop import run_computer_task, _SOURCE_SHA

st = computer_status(subject)
current, digest = st["configuration"], st["policy_sha256"]
payload = dict(current)
payload.update({"tools": ["browser.navigate", "browser.read"], "origins": [f"http://127.0.0.1:{port}"],
                "planner_provider": "ollama_http", "planner_model": "qwen2.5-coder:7b",
                "allow_remote_context": False, "max_steps": 16, "timeout_s": 900})
print("configured:", configure_computer(subject, payload, owner_confirmed=True, expected_policy_sha256=digest)["ok"], flush=True)
st2 = computer_status(subject)
print("policy:", st2["policy_sha256"], "| source_sha256:", _SOURCE_SHA, flush=True)

V1 = computer_loop._plan_progress

def V2(plan, tool_steps_since_plan):
    if not plan:
        return None
    steps = list(plan.get("steps", []))
    done = max(0, int(tool_steps_since_plan))
    return {"steps": [{"index": i + 1, "text": text, "executed": i < done} for i, text in enumerate(steps)],
            "next_step": steps[done] if done < len(steps) else None}

objective = (f"Open http://127.0.0.1:{port}/notes.html in the browser, read the page, and report "
             "the page title, the three items listed under Today, and the sentinel code.")
order = [v for r in range(RUNS) for v in ("v1", "v2")]
results = []
for n, variant in enumerate(order, start=1):
    computer_loop._plan_progress = V1 if variant == "v1" else V2
    mission_id = f"computer-loop-exp01-{variant}-r{(n + 1) // 2}"
    t0 = time.time()
    report = run_computer_task(subject, objective, mission_id=mission_id)
    elapsed = time.time() - t0
    props = []
    for p in report.get("proposals", []):
        body = json.loads(io.open(S / "control" / "ikarus-computer-artifacts" / f"{p['sha256']}.json", encoding="utf-8").read())
        props.append({"call": body["planner_call"], "step": body["step"], "sha256": p["sha256"], "response": body["response"]})
    row = {"run": n, "variant": variant, "mission_id": mission_id, "state": report.get("state"),
           "finished": report.get("state") == "completed", "planner_calls": report.get("planner_calls"),
           "tool_steps": report.get("tool_steps"), "replans": report.get("replans"), "elapsed_s": round(elapsed, 1),
           "summary": report.get("summary"), "planner_summary": report.get("planner_summary"),
           "report_artifact": report.get("report_artifact"), "proposals": props}
    results.append(row)
    print(f"RUN {n} {variant} {mission_id}: state={row['state']} finished={row['finished']} calls={row['planner_calls']} "
          f"tool_steps={row['tool_steps']} elapsed={row['elapsed_s']}s | {row['summary']}", flush=True)
    io.open(S / "exp01_results.json", "w", encoding="utf-8").write(json.dumps(
        {"objective": objective, "policy_sha256": st2["policy_sha256"], "source_sha256": _SOURCE_SHA,
         "runs_per_variant": RUNS, "order": order, "results": results}, indent=1, ensure_ascii=False, default=str))
for variant in ("v1", "v2"):
    rows = [r for r in results if r["variant"] == variant]
    print(f"SUMMARY {variant}: finished {sum(r['finished'] for r in rows)}/{len(rows)}; states "
          f"{[r['state'] for r in rows]}; calls {[r['planner_calls'] for r in rows]}; tool_steps {[r['tool_steps'] for r in rows]}", flush=True)
print("DONE", flush=True)
