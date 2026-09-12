"""The Waiter: Ikarus' voice at the table.

``maybe_serve`` is the single hook the chat shell calls. It recognises an
order, answers at once in the owner's language, and hands the order to the
Chef in a background thread (or synchronously with ``DAEDALUS_KITCHEN_SYNC=1``,
which the CLI and tests use). Status questions are answered from the ledger.

The Waiter never touches a workspace and never decides admission; it only
serves the table and reports what the kitchen recorded.
"""
from __future__ import annotations

import os
import json
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....foundation.projects import resolve_repo_root
from .chef import Chef, Kitchen, default_kitchen_root
from .ledger import STATUS_BLOCKED, STATUS_DONE, STATUS_FAILED, STATUS_NOMINATED, TERMINAL
from .orders import KIND_BUILD, KIND_FEED, KIND_IMPROVE, KIND_SELF, KIND_STATUS, Order, parse_order

SHELL_KITCHEN = "kitchen"
_KITCHENS: dict[str, Kitchen] = {}
_LOCK = threading.Lock()
_THREADS: dict[str, threading.Thread] = {}


def kitchen_for(repo_root: str | None) -> Kitchen:
    root = default_kitchen_root(repo_root if repo_root and not os.environ.get("DAEDALUS_KITCHEN_ROOT") else None)
    key = str(root.resolve())
    with _LOCK:
        kitchen = _KITCHENS.get(key)
        if kitchen is None:
            kitchen = Kitchen(root)
            _KITCHENS[key] = kitchen
        return kitchen


def _repo_root(project: str | None) -> str | None:
    if not project:
        return None
    try:
        return resolve_repo_root(None, project)
    except Exception:
        return None


def _kind_label(kind: str, german: bool) -> str:
    labels = {
        KIND_BUILD: ("Genesis-Bau", "Genesis build"),
        KIND_IMPROVE: ("Renovation", "Renovation"),
        KIND_SELF: ("Selbst-Renovation", "self-Renovation"),
        KIND_FEED: ("Ariadne-Fütterung", "Ariadne feeding"),
    }
    de, en = labels.get(kind, (kind, kind))
    return de if german else en


def _acceptance_text(order: Order, order_id: str, sync_result: dict[str, Any] | None, german: bool) -> str:
    label = _kind_label(order.kind, german)
    if sync_result is not None:
        return _result_text(order, sync_result, german)
    if german:
        plan = {
            KIND_BUILD: "Der Chefkoch legt einen leeren Kandidaten-Workspace an, holt passende Motive aus dem Grey Matter, "
                        "lässt den Bauagenten (lokal: Ollama-Sous-Chef mit Grey-Matter-Aufgabenteilung; sonst Claude Code oder Codex) die App schreiben, führt Build und Tests aus, "
                        "repariert bis zu zweimal, kompiliert den Kandidaten-Twin und nominiert das Ergebnis.",
            KIND_IMPROVE: "Der Chefkoch öffnet einen abgetrennten Worktree des Projekts, lässt den Bauagenten die Verbesserung "
                          "umsetzen, führt die Tests des Projekts aus, repariert bei Bedarf und legt einen Patch zur Nominierung ab. "
                          "Dein Checkout bleibt unberührt.",
            KIND_SELF: "Selbst-Renovation von Daedalus in einem abgetrennten Worktree, mit der Leckage-Grenze aus Plan §8.1: "
                       "Spine, Kernel-Policy, Plan, Amendment-Kette und AGENTS.md sind tabu; Tests laufen vor der Nominierung.",
            KIND_FEED: f"Der Chefkoch holt {len(order.sources) or 'das aktuelle'} Repositor{'ies' if len(order.sources) != 1 else 'y'}, "
                       "zerlegt sie in Vier-Ebenen-Node-Cards, berechnet Embeddings, den Relations-Tensor und Cross-Plane-Hypothesen "
                       "und schreibt alles mit Provenienz ins Grey Matter.",
        }[order.kind]
        return (f"Bestellung angenommen ({label}), Nummer `{order_id}`. {plan} Ich melde mich, sobald etwas auf dem Tisch steht; "
                f"frag mich zwischendurch „Küche Status“. Nichts wird automatisch gemerged oder promotet — du gibst frei.")
    plan = {
        KIND_BUILD: "The Chef opens an empty candidate workspace, retrieves motifs from Grey Matter, has the builder agent "
                    "(local Ollama Sous-Chef with Grey Matter task division; else Claude Code or Codex) write the app, runs build and tests, repairs up to twice, compiles the candidate "
                    "twin and nominates the result.",
        KIND_IMPROVE: "The Chef opens a detached worktree of the project, has the builder implement the improvement, runs the "
                      "project's tests, repairs if needed and files a patch for nomination. Your checkout is untouched.",
        KIND_SELF: "Self-Renovation of Daedalus in a detached worktree under the §8.1 leakage boundary: spine, kernel policy, "
                   "plan, amendment chain and AGENTS.md are off limits; tests run before nomination.",
        KIND_FEED: f"The Chef fetches {len(order.sources) or 'the current'} repositor{'ies' if len(order.sources) != 1 else 'y'}, "
                   "compiles four-plane Node Cards, embeddings, the relation tensor and cross-plane hypotheses into Grey Matter "
                   "with provenance.",
    }[order.kind]
    return (f"Order accepted ({label}), id `{order_id}`. {plan} Ask me \"kitchen status\" any time. Nothing is merged or "
            f"promoted automatically — you approve.")


def _result_text(order: Order, result: dict[str, Any], german: bool) -> str:
    status = result.get("status")
    if order.kind == KIND_FEED and status == STATUS_DONE:
        rows = result.get("ingested") or []
        gm = result.get("grey_matter") or {}
        parts = [f"{r['name']}@{str(r['revision'])[:10]}: {r['cards']} Cards, {r['edges']} Kanten, {r['proposals']} Hypothesen "
                 f"({r['verified_bindings']} verifiziert), Lizenz {r.get('license') or 'unbekannt'}" for r in rows]
        if german:
            return ("Ariadne ist gefüttert. " + "; ".join(parts) + f". Grey Matter gesamt: {gm.get('repos')} Repos, "
                    f"{gm.get('cards')} Cards, {gm.get('edges')} Kanten, {gm.get('verified_bindings')} verifizierte Cross-Plane-Bindungen.")
        return ("Ariadne fed. " + "; ".join(parts) + f". Grey Matter total: {gm.get('repos')} repos, {gm.get('cards')} cards, "
                f"{gm.get('edges')} edges, {gm.get('verified_bindings')} verified cross-plane bindings.")
    if status == STATUS_NOMINATED:
        checks = ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in (result.get("checks") or {}).items()) or "—"
        run = " ".join(result.get("run") or []) or "siehe README"
        where = result.get("patch") or result.get("workspace")
        if german:
            return (f"Fertig und nominiert. Kandidat `{str(result.get('candidate_tree_sha256'))[:12]}` ({result.get('files')} Dateien) "
                    f"liegt unter `{where}`. Checks: {checks}. Start: `{run}`"
                    + (f" → {result.get('preview')}" if result.get('preview') else "")
                    + f". Reparaturrunden: {result.get('repairs', 0)}. Evidence: `{result.get('evidence_path')}`. "
                    "Promotion/Merge erst nach deiner Freigabe.")
        return (f"Done and nominated. Candidate `{str(result.get('candidate_tree_sha256'))[:12]}` ({result.get('files')} files) "
                f"at `{where}`. Checks: {checks}. Run: `{run}`" + (f" → {result.get('preview')}" if result.get('preview') else "")
                + f". Repairs: {result.get('repairs', 0)}. Evidence: `{result.get('evidence_path')}`. Promotion only after your approval.")
    if status == STATUS_BLOCKED:
        return (f"Blockiert: {result.get('blocker')}" if german else f"Blocked: {result.get('blocker')}")
    detail = result.get("rejection") or result.get("error") or ", ".join(k for k, v in (result.get("checks") or {}).items() if not v) or "unknown"
    if german:
        return (f"Nicht gelungen ({detail}). Der Kandidat bleibt als negative Evidenz erhalten"
                + (f" unter `{result.get('workspace')}`" if result.get("workspace") else "") + ". Sag mir, ob ich es anders angehen soll.")
    return (f"Did not succeed ({detail}). The candidate is retained as negative evidence"
            + (f" at `{result.get('workspace')}`" if result.get("workspace") else "") + ". Tell me if I should try differently.")


def _status_text(kitchen: Kitchen, german: bool) -> str:
    recent = kitchen.ledger.recent(8)
    grey = kitchen.grey.stats()
    if not recent:
        head = "Die Küche ist leer — noch keine Bestellung." if german else "The kitchen is idle — no orders yet."
    else:
        lines = []
        for row in recent:
            order = kitchen.ledger.order(row["order_id"]) or {}
            last = (order.get("events") or [{}])[-1].get("text", "")
            lines.append(f"- `{row['order_id']}` [{row['status']}] {row['kind']}: {row['text'][:80]} — {last[:120]}")
        head = ("Küche:\n" if german else "Kitchen:\n") + "\n".join(lines)
    tail = (f"\nGrey Matter: {grey['repos']} Repos, {grey['cards']} Cards, {grey['edges']} Kanten, "
            f"{grey['verified_bindings']} verifizierte Bindungen." if german else
            f"\nGrey Matter: {grey['repos']} repos, {grey['cards']} cards, {grey['edges']} edges, {grey['verified_bindings']} verified bindings.")
    return head + tail


def _envelope(project: str | None, assistant: str, **payload: Any) -> dict[str, Any]:
    # Same shape as `daedalus.core.envelope`; spelled here so the kitchen does
    # not import `core` and join the shell's import cycle (import census).
    warnings = payload.pop("warnings", [])
    return {"ok": True, "generated_at": datetime.now(timezone.utc).isoformat(), "project": project,
            "warnings": warnings, "intent": "kitchen", "shell": SHELL_KITCHEN, "assistant": assistant,
            "provider_used": "kitchen", **payload}


def place_order(project: str | None, order: Order, *, sync: bool | None = None,
                chef: Chef | None = None) -> dict[str, Any]:
    repo_root = _repo_root(project)
    if project is not None or repo_root is not None:
        order = replace(order, context=json.dumps({"project": project, "repo_root": repo_root}, sort_keys=True))
    kitchen = kitchen_for(repo_root)
    order_id = order.order_id
    german = order.language == "de"
    if not kitchen.ledger.open_order(order_id, order.kind, project, order.text):
        existing = kitchen.ledger.order(order_id) or {}
        if existing.get("project") != project:
            return _envelope(project, "Order context conflict; existing evidence retained.",
                             order_id=order_id, status=STATUS_BLOCKED)
        result = existing.get("result")
        if result is not None:
            return _envelope(project, _result_text(order, result, german), order=order.to_dict(),
                             order_id=order_id, status=existing["status"], result=result, replayed=True)
        return _envelope(project, ("Diese Bestellung läuft bereits." if german else "That order is already cooking.") +
                         f" (`{order_id}`)", order=order.to_dict(), order_id=order_id,
                         status=existing.get("status", "cooking"), replayed=True)
    chef = chef or Chef(kitchen)
    run_sync = sync if sync is not None else os.environ.get("DAEDALUS_KITCHEN_SYNC") == "1"
    if run_sync:
        result = chef.cook(order, project=project, repo_root=repo_root)
        return _envelope(project, _acceptance_text(order, order_id, result, german), order=order.to_dict(),
                         order_id=order_id, status=result.get("status"), result=result)
    thread = threading.Thread(target=chef.cook, args=(order,), kwargs={"project": project, "repo_root": repo_root},
                              name=f"ikarus-chef-{order_id}", daemon=True)
    with _LOCK:
        _THREADS[order_id] = thread
    thread.start()
    return _envelope(project, _acceptance_text(order, order_id, None, german), order=order.to_dict(),
                     order_id=order_id, status="accepted")


def order_status(project: str | None, order_id: str | None = None) -> dict[str, Any]:
    kitchen = kitchen_for(_repo_root(project))
    if order_id:
        return kitchen.ledger.order(order_id) or {"order_id": order_id, "status": "unknown"}
    return {"orders": kitchen.ledger.recent(20), "grey_matter": kitchen.grey.stats()}


def maybe_serve(project: str | None, message: str, *, conversation_id: str | None = None) -> dict[str, Any] | None:
    """The chat hook: an envelope when the sentence is an order, else ``None``."""
    order = parse_order(message)
    if order is None:
        return None
    german = order.language == "de"
    if order.kind == KIND_STATUS:
        kitchen = kitchen_for(_repo_root(project))
        return _envelope(project, _status_text(kitchen, german), status=order_status(project))
    return place_order(project, order)


__all__ = ["maybe_serve", "place_order", "order_status", "kitchen_for", "SHELL_KITCHEN"]
