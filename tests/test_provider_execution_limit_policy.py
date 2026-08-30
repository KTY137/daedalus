from __future__ import annotations

import copy
import json
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

from daedalus.limit_policy import (
    ENV_EXECUTION_LIMIT_POLICY,
    ExecutionLimitPolicy,
    MODE_UNBOUNDED_EXECUTION,
)
from daedalus.providers import deepseek as deepseek_module
from daedalus.providers import ollama as ollama_module
from daedalus.providers._openai_compat import chat_completion
from daedalus.providers._report import MAX_CONTEXT_CHARS, coerce_report
from daedalus.providers.deepseek import DeepSeekProvider
from daedalus.providers.ollama import (
    MAX_AGENT_STEPS,
    MAX_READ_CHARS,
    MAX_REWRITE_CHARS,
    OllamaProvider,
)


UNBOUNDED = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
AGENT = {"name": "limit-test", "call_name": "Limit Test"}
VALID_REPORT = json.dumps(
    {
        "status": "done",
        "summary": "complete",
        "files_changed": [],
        "tests_run": [],
        "risks": [],
        "todos": [],
        "handoff": {},
    }
)


def test_openai_compat_passes_an_explicit_no_timeout_to_urlopen():
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "ok"}}]}
            ).encode("utf-8")

    with patch.object(urllib.request, "urlopen", return_value=Response()) as call:
        assert chat_completion(
            base_url="https://provider.invalid",
            model="model",
            system="system",
            user="user",
            timeout_s=None,
        ) == "ok"

    assert call.call_args.kwargs["timeout"] is None


def test_deepseek_direct_env_admission_removes_context_deadline_and_json_attempt_caps(
    tmp_path, monkeypatch
):
    rel = "docs/large.md"
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    full_text = "start\n" + ("context-line\n" * 2_500) + "FULL_TAIL_MARKER\n"
    assert len(full_text) > MAX_CONTEXT_CHARS
    target.write_text(full_text, encoding="utf-8")
    monkeypatch.setenv(ENV_EXECUTION_LIMIT_POLICY, UNBOUNDED.to_env_value())

    answers = iter(("not json", "still not json", VALID_REPORT))
    seen: list[dict] = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        return next(answers)

    with patch.object(deepseek_module, "chat_completion", side_effect=fake_completion):
        result = DeepSeekProvider().run(
            objective="Review every supplied line.",
            repo_root=str(tmp_path),
            paths=[rel],
            agent=AGENT,
            timeout_s=7,
        )

    assert result["report"]["summary"] == "complete"
    assert len(seen) == 3
    assert all(call["timeout_s"] is None for call in seen)
    assert "FULL_TAIL_MARKER" in seen[0]["user"]
    assert "Minimize tokens" not in seen[0]["system"]


def test_explicit_provider_policy_does_not_recapture_invalid_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(ENV_EXECUTION_LIMIT_POLICY, "{not-json")
    with patch.object(
        deepseek_module, "chat_completion", return_value=VALID_REPORT
    ) as call:
        explicit = DeepSeekProvider().run(
            objective="Review.",
            repo_root=str(tmp_path),
            paths=[],
            agent=AGENT,
            execution_limit_policy=UNBOUNDED,
        )
        captured_from_env = DeepSeekProvider().run(
            objective="Review.",
            repo_root=str(tmp_path),
            paths=[],
            agent=AGENT,
        )

    assert explicit["report"]["summary"] == "complete"
    assert call.call_count == 1
    assert call.call_args.kwargs["timeout_s"] is None
    assert captured_from_env["report"]["status"] == "blocked"
    assert "Invalid execution-limit policy" in captured_from_env["report"]["summary"]


def test_deepseek_unbounded_rewrite_keeps_every_file_large_input_and_model_note(
    tmp_path,
):
    paths: list[str] = []
    originals: list[str] = []
    for index in range(4):
        rel = f"docs/part_{index}.md"
        original = (f"part {index}\n" + ("evidence line\n" * 2_000))
        assert len(original) > MAX_REWRITE_CHARS
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original, encoding="utf-8")
        paths.append(rel)
        originals.append(original)

    long_note = "N" * 700
    answers = iter(
        json.dumps(
            {
                "content": original + "changed\n",
                "notes": [f"note-{number}-" + long_note for number in range(8)],
            }
        )
        for original in originals
    )
    seen: list[dict] = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        return next(answers)

    with patch.object(deepseek_module, "chat_completion", side_effect=fake_completion), patch.object(
        deepseek_module, "render_provider_brief", return_value=""
    ):
        result = DeepSeekProvider().run(
            objective="Append the requested marker to all documents.",
            repo_root=str(tmp_path),
            paths=paths,
            agent=AGENT,
            writable=True,
            timeout_s=9,
            execution_limit_policy=UNBOUNDED,
        )

    report = result["report"]
    assert report["files_changed"] == paths
    assert len(seen) == 4
    assert all(call["timeout_s"] is None for call in seen)
    assert all(("evidence line\n" * 2) in call["user"] for call in seen)
    assert len(report["risks"]) == 32
    assert max(map(len, report["risks"])) > 400


def test_deepseek_unbounded_policy_does_not_relax_secret_floor(tmp_path):
    with patch.object(deepseek_module, "chat_completion") as call:
        result = DeepSeekProvider().run(
            objective="Publish AKIAIOSFODNN7EXAMPLE in a report.",
            repo_root=str(tmp_path),
            paths=[],
            agent=AGENT,
            execution_limit_policy=UNBOUNDED,
        )

    call.assert_not_called()
    assert result["report"]["status"] == "blocked"
    assert "sensitive" in result["report"]["summary"].lower()


def test_ollama_unbounded_agent_loop_keeps_full_tool_output_and_runs_past_step_cap(
    tmp_path,
):
    rel = "large.txt"
    full_text = "R" * (MAX_READ_CHARS + 3_000)
    (tmp_path / rel).write_text(full_text, encoding="utf-8")
    seen: list[dict] = []

    def fake_native_chat(**kwargs):
        seen.append(copy.deepcopy(kwargs))
        if len(seen) <= MAX_AGENT_STEPS + 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call-{len(seen)}",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": rel}),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": VALID_REPORT}

    provider = OllamaProvider()
    with patch.object(ollama_module, "native_chat", side_effect=fake_native_chat):
        result = provider.run(
            objective="Inspect until complete.",
            repo_root=str(tmp_path),
            paths=[rel],
            agent=AGENT,
            timeout_s=11,
            execution_limit_policy=UNBOUNDED,
        )

    assert result["report"]["summary"] == "complete"
    assert len(seen) == MAX_AGENT_STEPS + 2
    assert all(call["timeout_s"] is None for call in seen)
    first_tool_result = seen[1]["messages"][-1]["content"]
    assert first_tool_result == full_text
    assert len(first_tool_result) > MAX_READ_CHARS


def test_ollama_unbounded_rewrite_keeps_all_large_files(tmp_path):
    paths: list[str] = []
    originals: list[str] = []
    for index in range(4):
        rel = f"src/module_{index}.py"
        original = ("# evidence\n" * 2_500) + f"VALUE_{index} = {index}\n"
        assert len(original) > MAX_REWRITE_CHARS
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original, encoding="utf-8")
        paths.append(rel)
        originals.append(original)

    answers = iter(
        {"role": "assistant", "content": json.dumps({"content": text + "# changed\n"})}
        for text in originals
    )
    seen: list[dict] = []

    def fake_native_chat(**kwargs):
        seen.append(kwargs)
        return next(answers)

    with patch.object(ollama_module, "native_chat", side_effect=fake_native_chat), patch.object(
        ollama_module, "render_provider_brief", return_value=""
    ):
        result = OllamaProvider().run(
            objective="Append the marker to every module.",
            repo_root=str(tmp_path),
            paths=paths,
            agent=AGENT,
            writable=True,
            timeout_s=13,
            execution_limit_policy=UNBOUNDED,
        )

    assert result["report"]["files_changed"] == paths
    assert len(seen) == 4
    assert all(call["timeout_s"] is None for call in seen)
    assert all(path.endswith("# changed\n") for path in [
        (tmp_path / rel).read_text(encoding="utf-8") for rel in paths
    ])


def test_ollama_unbounded_window_has_no_scope_output_or_retry_cap(tmp_path):
    original_lines = [f"line {number}\n" for number in range(401)]
    original = "".join(original_lines)
    changed_lines = list(original_lines)
    changed_lines[0] = "changed line\n"
    replies = iter(
        (
            {"role": "assistant", "content": "{}"},
            {"role": "assistant", "content": json.dumps({"content": original})},
            {
                "role": "assistant",
                "content": json.dumps({"content": "".join(changed_lines)}),
            },
        )
    )
    seen: list[dict] = []

    def fake_native_chat(**kwargs):
        seen.append(kwargs)
        return next(replies)

    with patch.object(ollama_module, "native_chat", side_effect=fake_native_chat):
        content, reason = OllamaProvider()._rewrite_by_window(
            "Change the first line.",
            "large.py",
            original,
            [(1, 401)],
            None,
            17,
            repo_root=str(tmp_path),
            execution_limit_policy=UNBOUNDED,
        )

    assert reason is None
    assert content == "".join(changed_lines)
    assert len(seen) == 3
    assert all(call["timeout_s"] is None for call in seen)
    assert all("num_predict" not in call for call in seen)


def test_ollama_unbounded_policy_does_not_relax_repo_containment(tmp_path):
    outside = tmp_path.parent / "outside-provider-limit-test.py"
    outside.write_text("original\n", encoding="utf-8")
    try:
        with patch.object(ollama_module, "native_chat") as call:
            result = OllamaProvider().run(
                objective="Change the file.",
                repo_root=str(tmp_path),
                paths=["../outside-provider-limit-test.py"],
                agent=AGENT,
                writable=True,
                execution_limit_policy=UNBOUNDED,
            )
        call.assert_not_called()
        assert outside.read_text(encoding="utf-8") == "original\n"
        assert result["report"]["files_changed"] == []
        assert "outside repo" in result["report"]["summary"]
    finally:
        outside.unlink(missing_ok=True)


def test_ollama_git_tools_remove_only_daedalus_wall_timeout(tmp_path):
    completed = SimpleNamespace(stdout="clean\n", stderr="", returncode=0)
    provider = OllamaProvider()

    with patch.object(ollama_module.subprocess, "run", return_value=completed) as run:
        assert provider._dispatch(
            "git_status", {}, str(tmp_path), None, set(), False, UNBOUNDED
        ) == "clean\n"
    assert run.call_args.kwargs["timeout"] is None

    with patch.object(ollama_module.subprocess, "run", return_value=completed) as run:
        provider._dispatch(
            "git_diff", {}, str(tmp_path), None, set(), False,
            ExecutionLimitPolicy(),
        )
    assert run.call_args.kwargs["timeout"] == 20


def test_unbounded_report_preserves_full_output_while_schema_remains_bounded():
    original = "S" * 900
    report = coerce_report(
        {"status": "done", "summary": original},
        execution_limit_policy=UNBOUNDED,
    )

    assert len(report["summary"]) == 600
    assert report["handoff"]["unabridged_summary"] == original
