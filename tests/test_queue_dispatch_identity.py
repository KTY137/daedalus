from types import SimpleNamespace

from daedalus import conversation as conv
from daedalus import web_api


def test_queue_binds_canonical_dispatch_identity_from_real_enqueue_result(monkeypatch):
    body = {
        "project": "project_tct",
        "objective": "  inspect runtime identity  ",
        "lane": "auto",
        "source": "webapp",
        "strategy": "single",
        "paths": ["daedalus/web_api.py"],
        "conversation_id": "conv-1",
        "turn_id": 7,
    }
    queue_call = {}
    link_call = {}
    sent = {}

    def fake_queue_task(project, objective, lane, source, strategy, paths):
        queue_call.update(
            project=project,
            objective=objective,
            lane=lane,
            source=source,
            strategy=strategy,
            paths=paths,
        )
        # Deliberately differ from the request lane. The durable identity
        # must describe what enqueue returned, not reconstruct the request.
        return {"queued": "/tmp/task-identity-123.json", "lane": "claude"}

    def fake_link_dispatch(conversation_id, dispatch_ref, **kwargs):
        link_call.update(
            conversation_id=conversation_id,
            dispatch_ref=dispatch_ref,
            **kwargs,
        )
        return SimpleNamespace(
            conversation_id=conversation_id,
            turn_id=kwargs["turn_id"],
            dispatch_ref=dispatch_ref,
        )

    monkeypatch.setattr(web_api, "_read_body", lambda _handler: body)
    monkeypatch.setattr(web_api.core, "queue_task", fake_queue_task)
    monkeypatch.setattr(
        conv,
        "default_store",
        lambda: SimpleNamespace(link_dispatch=fake_link_dispatch),
    )

    handler = object.__new__(web_api.DaedalusHandler)
    handler.path = "/api/queue"
    handler._send_json = (
        lambda payload, status=200: sent.update(payload=payload, status=status)
    )

    handler._handle_post()

    assert queue_call == {
        "project": "project_tct",
        "objective": "inspect runtime identity",
        "lane": "auto",
        "source": "webapp",
        "strategy": "single",
        "paths": ["daedalus/web_api.py"],
    }
    assert link_call == {
        "conversation_id": "conv-1",
        "dispatch_ref": "task-identity-123",
        "turn_id": 7,
        "kind": "queue_task",
        "detail": {
            "schema": "conversation.dispatch.identity.v1",
            "project": "project_tct",
            "objective": "inspect runtime identity",
            "lane": "claude",
        },
    }
    assert sent["status"] == 200
    assert sent["payload"]["conversation_link"] == {
        "conversation_id": "conv-1",
        "turn_id": 7,
        "dispatch_ref": "task-identity-123",
        "linked": True,
    }
