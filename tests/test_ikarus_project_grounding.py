"""G1-IKARUS-16: selected-project evidence for answer-shaped Voice turns."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

from daedalus.orchestration.ikarus import shell as ikarus_os
from daedalus.spine import picker as picker_mod
from daedalus.spine.picker import Candidate, PickedQueue


ANALYSIS_PROMPT = (
    "Schau dir den aktuellen Projektzustand an. Nenne die drei wichtigsten "
    "nächsten Schritte und erkläre kurz, warum."
)


def _candidate(task_id: str, *, target: str, instruction: str) -> Candidate:
    return Candidate(
        task_id=task_id,
        source="map_island",
        instruction=instruction,
        reason=f"{target} is measured as unreachable",
        score=810.0,
        evidence={"module": target},
        target_paths=(target,),
    )


def _owners(tmp_path, *, picked: PickedQueue, dirty: str = ""):
    config = {
        "name": "sample",
        "repo_root": str(tmp_path),
        "center": ["src", "docs"],
        "test_command": "pytest -q",
        "policy": {"allow": ["docs/", "src/"]},
    }
    return (
        mock.patch.object(ikarus_os, "resolve_repo_root", return_value=str(tmp_path)),
        mock.patch("daedalus.config.resolve_project", return_value=config),
        mock.patch("daedalus.status.collect_status", return_value={
            "git_branch": "main", "git_status": dirty,
        }),
        mock.patch("daedalus.file_bridge.bridge_status", return_value={
            "queue_depth": 1,
            "in_flight": None,
            "unread_count": 2,
            "quarantined_count": 0,
            "reports_total": 4,
            "watcher": {"state": "alive", "project": "sample"},
        }),
        mock.patch.object(ikarus_os.core, "get_governance", return_value={
            "state": "degraded",
            "promotion_allowed": False,
            "head": "a" * 40,
            "gates": [{
                "id": "discrimination", "state": "absent",
                "provenance": "MEASURED",
            }],
            "blockers": [{"gate": "discrimination", "state": "absent"}],
        }),
        mock.patch("daedalus.spine.picker.build_queue", return_value=picked),
    )


def test_exact_live_prompt_sends_measured_project_facts_to_selected_voice(
        tmp_path) -> None:
    picked = PickedQueue(
        candidates=(_candidate(
            "map-island-core", target="src/core.py",
            instruction="Inspect the measured reachability gap in src/core.py."),),
        sources={
            "map": {"state": "valid", "read": True, "candidates": 1},
            "work_queue": {
                "state": "valid", "tasks": 2, "ready": 1, "non_ready": 1,
                "candidate_base_revision": "b" * 40,
                "picker_observed_head": "a" * 40,
            },
        },
    )
    captured = {}

    def stream(_message, _model, _effort, context, **_kwargs):
        captured["context"] = context
        return iter(["Drei belastbare Schritte"])

    patches = _owners(tmp_path, picked=picked, dirty=" M src/core.py\n")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
            mock.patch.object(ikarus_os, "_local_lane", return_value="trusted"), \
            mock.patch.object(ikarus_os, "_ollama_stream", side_effect=stream):
        events = list(ikarus_os.ask_stream(
            "sample", ANALYSIS_PROMPT, provider="ollama",
            additional_context=(
                "# Explicit editor context: docs/brief.md\nselected text"
            ),
        ))

    context = captured["context"]
    assert "status.collect_status" in context
    assert "file_bridge.bridge_status" in context
    assert "core.get_governance" in context
    assert "spine.picker.build_queue" in context
    assert '"dirty": true' in context
    assert '"queue_depth": 1' in context
    assert '"gate": "discrimination"' in context
    assert "map-island-core" in context
    assert "# Explicit editor context: docs/brief.md" in context
    assert context.index("Current project evidence") < context.index(
        "Explicit editor context")

    final = events[-1][1]
    assert final["intent"] == "chat"
    assert final["shell"] == ikarus_os.SHELL_VOICE
    assert final["assistant"] == "Drei belastbare Schritte"
    assert final["context"]["kind"] == "project_state"
    assert final["context"]["fact_count"] > 0
    assert "action" not in final


def test_untrusted_project_snapshot_is_bounded_and_prunes_every_candidate_path(
        tmp_path) -> None:
    visible = _candidate(
        "docs-next", target="docs/next.md",
        instruction="Review the measured gap documented in docs/next.md.")
    hidden_path = _candidate(
        "private-next", target="src/private.py",
        instruction="Review src/private.py after reading docs/next.md.")
    hidden_secret = _candidate(
        "API_KEY=ijklmnop", target="docs/secret-note.md",
        instruction='Use API_KEY = "abcdefgh" from the note.')
    picked = PickedQueue(
        candidates=(visible, hidden_path, hidden_secret),
        sources={"map": {"state": "valid", "read": True, "candidates": 3}},
    )
    patches = _owners(
        tmp_path, picked=picked,
        dirty=(
            " M docs/ok.md\n M src/private.py\n"
            "R  docs/old.md -> src/new.py\n?? .env\n"
        ),
    )
    # External policy permits only docs. The rename proves both endpoints are
    # gated rather than the allowed source masking the disallowed destination.
    patches = list(patches)
    patches[1] = mock.patch("daedalus.config.resolve_project", return_value={
        "name": "sample",
        "repo_root": str(tmp_path),
        "center": ["docs", "src"],
        "policy": {"allow": ["docs/"]},
    })
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        context = ikarus_os._project_state_context("sample", "untrusted")

    assert len(context.text) <= ikarus_os._PROJECT_STATE_MAX_CONTEXT_CHARS
    assert "docs/ok.md" in context.text
    assert "docs-next" in context.text
    assert "src/private.py" not in context.text
    assert "docs/old.md" not in context.text
    assert "src/new.py" not in context.text
    assert ".env" not in context.text
    assert "abcdefgh" not in context.text
    assert "ijklmnop" not in context.text
    assert "private-next" not in context.text
    assert context.withheld_count >= 6


def test_explicit_mutation_after_observation_stays_on_confirm_gated_hand() -> None:
    message = "Prüf die Tests und fix den Fehler. Erklär danach warum."
    with mock.patch.object(
            ikarus_os.core, "team_config",
            return_value={"default_lane": "local_only"}), \
            mock.patch.object(ikarus_os, "_hand_state", return_value=None), \
            mock.patch.object(ikarus_os, "_project_state_context") as context, \
            mock.patch.object(ikarus_os, "_ollama_stream") as voice:
        events = list(ikarus_os.ask_stream(
            "sample", message, provider="ollama"))

    context.assert_not_called()
    voice.assert_not_called()
    final = events[-1][1]
    assert final["intent"] == "enqueue"
    assert final["shell"] == ikarus_os.SHELL_HAND
    assert final["action"]["requires_confirmation"] is True


def test_repository_strings_are_whitelisted_or_withheld_in_every_section(
        tmp_path) -> None:
    secret = 'API_KEY = "abcdefgh"'
    picked = PickedQueue(
        candidates=(
            _candidate(secret, target="docs/next.md", instruction="Review docs."),
            Candidate(
                task_id="safe-id", source=secret, instruction="Review docs.",
                reason="Measured gap", score=10.0,
                evidence={"module": "docs/next.md"},
                target_paths=("docs/next.md",),
            ),
        ),
        sources={
            "map": {
                "state": secret, "read": True, "candidates": 2,
                "candidate_base_revision": secret,
                "picker_observed_head": secret,
            },
            secret: {"state": "invalid", "error": secret},
        },
    )
    patches = list(_owners(tmp_path, picked=picked))
    patches[3] = mock.patch(
        "daedalus.file_bridge.bridge_status", return_value={
            "queue_depth": 0, "in_flight": None, "unread_count": 0,
            "quarantined_count": 0, "reports_total": 0,
            "watcher": {"state": secret, "project": secret},
        })
    patches[4] = mock.patch.object(ikarus_os.core, "get_governance", return_value={
        "state": secret,
        "promotion_allowed": secret,
        "head": secret,
        "gates": [
            {"id": "discrimination", "state": secret, "provenance": secret},
            {"id": secret, "state": "working", "provenance": "MEASURED"},
        ],
        "blockers": [
            {"gate": "discrimination", "state": secret},
            {"gate": secret, "state": "absent"},
        ],
    })
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        context = ikarus_os._project_state_context("sample", "trusted")

    payload = json.loads(context.text[context.text.index("{"):])
    assert secret not in context.text
    assert "abcdefgh" not in context.text
    assert payload["work"]["watcher_state"] == "unknown"
    assert payload["governance"]["state"] == "unknown"
    assert payload["governance"]["gates"] == [{
        "id": "discrimination", "state": "unknown", "provenance": "unknown",
    }]
    assert payload["next_work"]["source_states"]["map"]["state"] == "unknown"
    assert payload["next_work"]["ranked_candidates"] == []
    assert payload["next_work"]["unknown_source_keys_withheld"] == 1
    assert context.measurement_failures >= 3
    assert context.withheld_count >= 10


def test_invalid_policy_fails_closed_but_voice_still_answers(tmp_path) -> None:
    captured = {}

    def stream(_message, _model, _effort, context, **_kwargs):
        captured["context"] = context
        return iter(["Messung unvollständig."])

    with mock.patch.object(
            ikarus_os, "resolve_repo_root", return_value=str(tmp_path)), \
            mock.patch("daedalus.config.resolve_project", return_value={
                "policy": {"allow": 7},
            }), \
            mock.patch.object(ikarus_os, "_local_lane", return_value="trusted"), \
            mock.patch.object(ikarus_os, "_ollama_stream", side_effect=stream):
        events = list(ikarus_os.ask_stream(
            "sample", ANALYSIS_PROMPT, provider="ollama"))

    assert events[0][0] == "start"
    assert events[-1][1]["assistant"] == "Messung unvollständig."
    assert events[-1][1]["context"]["measurement_failures"] == 1
    assert '"component": "egress_policy"' in captured["context"]
    assert '"withheld_items": 1' in captured["context"]


def test_stream_start_precedes_project_measurement() -> None:
    measured: list[str] = []

    def project_context(*_args, **_kwargs):
        measured.append("measured")
        return ikarus_os._EMPTY_CTX

    with mock.patch.object(ikarus_os, "_project_context", side_effect=project_context), \
            mock.patch.object(
                ikarus_os, "_ollama_stream", return_value=iter(["ready"])):
        stream = ikarus_os._ask_stream_inner(
            "sample", ANALYSIS_PROMPT, provider="ollama")
        first = next(stream)
        assert first[0] == "start"
        assert measured == []
        remaining = list(stream)

    assert measured == ["measured"]
    assert remaining[-1][0] == "final"


def test_interactive_projection_bounds_git_and_disables_docref_scan(
        tmp_path) -> None:
    picked = PickedQueue(candidates=(), sources={})
    patches = _owners(tmp_path, picked=picked)
    with patches[0], patches[1], patches[3], patches[4], \
            mock.patch("daedalus.status.collect_status", return_value={
                "git_branch": "main", "git_status": "",
            }) as status, \
            mock.patch(
                "daedalus.spine.picker.build_queue", return_value=picked) as queue:
        ikarus_os._project_state_context("sample", "trusted")

    assert status.call_args.kwargs["git_timeout_s"] == (
        ikarus_os._PROJECT_STATE_GIT_TIMEOUT_S)
    assert queue.call_args.kwargs["include_docrefs"] is False


def test_picker_docref_switch_defaults_on_and_can_skip_scan(tmp_path) -> None:
    kwargs = {
        "limit": None,
        "use_attempt_memory": False,
        "inventory": {},
        "map_snapshot": {},
        "baseline": {},
    }
    with mock.patch("daedalus.spine.docrefs.scan") as scan:
        queue = picker_mod.build_queue(
            tmp_path, include_docrefs=False, **kwargs)
    scan.assert_not_called()
    assert queue.sources["docref"]["state"] == "disabled"

    report = SimpleNamespace(
        files_scanned=0, resolving=(), broken=(), skipped=())
    with mock.patch("daedalus.spine.docrefs.scan", return_value=report) as scan, \
            mock.patch.object(
                picker_mod, "docref_candidates", return_value=((), ())):
        picker_mod.build_queue(tmp_path, **kwargs)
    scan.assert_called_once_with(tmp_path.resolve())


def test_answer_shaped_project_status_precedes_generic_status_route() -> None:
    assert ikarus_os.classify(
        "Analysiere den Projektstatus und nenne drei nächste Schritte.") == "chat"
    assert ikarus_os.classify("status") == "status"
    assert ikarus_os.classify("/status") == "status"
    assert ikarus_os.classify("Projektstatus") == "status"
