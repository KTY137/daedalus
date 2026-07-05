from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .router import route_task
from .schemas import REPORT_KEYS, validate_report
from .fallback import fallback_decision


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "runs"

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked", "needs_review", "failed"]},
        "summary": {"type": "string", "maxLength": 600},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "todos": {"type": "array", "items": {"type": "string"}},
        "handoff": {"type": "object"},
    },
    "required": sorted(REPORT_KEYS),
    "additionalProperties": False,
}


def build_prompt(objective: str, repo_root: str, paths: list[str], agent: dict[str, Any]) -> str:
    return f"""You are acting as {agent["call_name"]} / {agent["name"]}.

Work as a stateless specialist. Do not ask another agent. Do not use full chat history.

Repository root:
{repo_root}

Objective:
{objective}

Relevant paths:
{json.dumps(paths, indent=2)}

Must read if needed:
{json.dumps(agent.get("must_read", []), indent=2)}

Constraints:
- Read only the files needed for this task.
- Prefer review/analysis unless the objective explicitly asks for edits.
- Do not run code that can touch real hardware.
- Return only the structured report required by the schema.
"""


def _extract_json(output: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(output[start : end + 1])

    if isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], str):
        return _extract_json(payload["result"])
    if not isinstance(payload, dict):
        raise ValueError("Claude output did not decode to a JSON object")
    return payload


def _blocked_report_from_wrapper(output: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get("is_error"):
        return None
    message = str(payload.get("result") or payload.get("error") or "Claude call failed")
    decision = fallback_decision("blocked")
    return {
        "status": "blocked",
        "summary": message[:600],
        "files_changed": [],
        "tests_run": [],
        "risks": ["Claude CLI returned an error before producing a specialist report."],
        "todos": [decision["todo"] or "Retry Claude bridge later."],
        "handoff": {
            "api_error_status": payload.get("api_error_status"),
            "session_id": payload.get("session_id"),
            "fallback": decision,
        },
    }


def ask_claude(
    objective: str,
    repo_root: str,
    paths: list[str],
    model: str = "sonnet",
    timeout_s: int = 300,
) -> dict[str, Any]:
    agent = route_task(objective, paths)
    prompt = build_prompt(objective, repo_root, paths, agent)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    prompt_path = RUN_DIR / "last_claude_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(REPORT_SCHEMA),
        "--permission-mode",
        "dontAsk",
        "--add-dir",
        repo_root,
    ]
    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        report = _blocked_report_from_wrapper(completed.stdout)
        if report is not None:
            report_path = RUN_DIR / "last_claude_report.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return {
                "agent": agent["name"],
                "prompt_path": str(prompt_path),
                "report_path": str(report_path),
                "report": report,
            }
        raise RuntimeError(
            "Claude failed with exit code "
            f"{completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )

    report = _extract_json(completed.stdout)
    errors = validate_report(report)
    if errors:
        raise ValueError("Invalid Claude report: " + "; ".join(errors))

    report_path = RUN_DIR / "last_claude_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"agent": agent["name"], "prompt_path": str(prompt_path), "report_path": str(report_path), "report": report}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask Claude for a structured specialist report.")
    parser.add_argument("objective")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--timeout-s", type=int, default=300)
    args = parser.parse_args()
    result = ask_claude(args.objective, args.repo_root, args.paths, args.model, args.timeout_s)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
