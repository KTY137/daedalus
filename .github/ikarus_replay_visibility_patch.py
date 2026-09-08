from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one patch anchor, found {text.count(old)}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "daedalus/file_bridge.py",
    '''    request = payload.get("request") or {}\n    summary = ((payload.get("report") or {}).get("summary")\n               or payload.get("error") or "")\n    return {\n''',
    '''    request = payload.get("request") or {}\n    summary = ((payload.get("report") or {}).get("summary")\n               or payload.get("error") or "")\n    # Provider execution mode is terminal evidence too. Keep exact booleans\n    # only: False means something here (the sealed broker reused a terminal\n    # invocation instead of starting a new provider run), so truthiness would\n    # erase the distinction. Request/chat metadata is intentionally ignored.\n    replay = payload.get("replay")\n    replay = replay if type(replay) is bool else None\n    runtime_receipt = payload.get("runtime_receipt")\n    execution_executed = (\n        runtime_receipt.get("executed")\n        if type(runtime_receipt) is dict\n        and type(runtime_receipt.get("executed")) is bool\n        else None\n    )\n    return {\n''',
)

replace_once(
    "daedalus/file_bridge.py",
    '''        "agent": payload.get("agent") or "",\n        "runtime_id": payload.get("runtime_id") or "",\n''',
    '''        "agent": payload.get("agent") or "",\n        "provider": payload.get("provider") or "",\n        "replay": replay,\n        "execution_executed": execution_executed,\n        "runtime_id": payload.get("runtime_id") or "",\n''',
)

replace_once(
    "apps/web/src/cockpit/liveWork.ts",
    '''  lane?: string;\n  agent?: string;\n  runtimeId?: string;\n''',
    '''  lane?: string;\n  agent?: string;\n  provider?: string;\n  /** Exact provider-owned replay evidence; false is meaningful and retained. */\n  replay?: boolean;\n  /** Exact runtime_receipt.executed projection; never inferred from status/lane. */\n  executionExecuted?: boolean;\n  runtimeId?: string;\n''',
)

replace_once(
    "apps/web/src/cockpit/liveWork.ts",
    '''function terminalReceiptSha256(value: unknown): string | undefined {\n  const candidate = canonicalEvidenceText(value);\n  return candidate && LOWER_SHA256.test(candidate) ? candidate : undefined;\n}\n\nexport function reportBrief(value: unknown): LiveReportBrief | undefined {\n''',
    '''function terminalReceiptSha256(value: unknown): string | undefined {\n  const candidate = canonicalEvidenceText(value);\n  return candidate && LOWER_SHA256.test(candidate) ? candidate : undefined;\n}\n\nfunction exactBoolean(value: unknown): boolean | undefined {\n  return typeof value === 'boolean' ? value : undefined;\n}\n\nexport function reportBrief(value: unknown): LiveReportBrief | undefined {\n''',
)

replace_once(
    "apps/web/src/cockpit/liveWork.ts",
    '''    lane: canonicalEvidenceText(row.lane),\n    agent: canonicalEvidenceText(row.agent),\n    runtimeId: canonicalEvidenceText(row.runtime_id),\n''',
    '''    lane: canonicalEvidenceText(row.lane),\n    agent: canonicalEvidenceText(row.agent),\n    provider: canonicalEvidenceText(row.provider),\n    replay: exactBoolean(row.replay),\n    executionExecuted: exactBoolean(row.execution_executed),\n    runtimeId: canonicalEvidenceText(row.runtime_id),\n''',
)

replace_once(
    "apps/web/src/cockpit/WorkPulse.tsx",
    '''export function terminalEvidenceStatus(report: LiveReportBrief): string | undefined {\n  const hasAny = Boolean(\n    report.runtimeId || report.workItemId || report.attemptId || report.phase || report.terminalReceiptSha256\n  );\n  if (!hasAny) return undefined;\n  const complete = Boolean(\n    report.runtimeId\n      && report.workItemId\n      && report.attemptId\n      && report.phase === 'terminal'\n      && report.terminalReceiptSha256\n  );\n  return complete\n    ? 'Terminale Evidenz: geschlossen'\n    : 'Terminale Evidenz: unvollständig · Abschluss nicht als vollständig belegt behandeln';\n}\n\n/**\n * Confidence label for dispatch identity. A bound versioned snapshot is\n''',
    '''export function terminalEvidenceStatus(report: LiveReportBrief): string | undefined {\n  const hasAny = Boolean(\n    report.runtimeId || report.workItemId || report.attemptId || report.phase || report.terminalReceiptSha256\n  );\n  if (!hasAny) return undefined;\n  const complete = Boolean(\n    report.runtimeId\n      && report.workItemId\n      && report.attemptId\n      && report.phase === 'terminal'\n      && report.terminalReceiptSha256\n  );\n  return complete\n    ? 'Terminale Evidenz: geschlossen'\n    : 'Terminale Evidenz: unvollständig · Abschluss nicht als vollständig belegt behandeln';\n}\n\n/**\n * Show whether the sealed provider boundary actually started a new invocation\n * or returned already-terminal replay evidence. This is observation only: no\n * lane/status inference, no receipt inspection and no repair of contradictory\n * producer facts. A closed terminal spine can therefore still be labelled as\n * a replay instead of looking like fresh work.\n */\nexport function providerExecutionLine(report: LiveReportBrief): string | undefined {\n  const parts: string[] = [];\n  if (report.provider) parts.push(`Provider ${briefText(report.provider)}`);\n\n  if (report.replay === true && report.executionExecuted === true) {\n    parts.push('Ausführungsevidenz widersprüchlich: Replay und neuer Lauf zugleich');\n  } else if (report.replay === true && report.executionExecuted === false) {\n    parts.push('Replay · kein neuer Provider-Lauf');\n  } else if (report.replay === true) {\n    parts.push('Replay · Ausführungsstatus nicht mitgeliefert');\n  } else if (report.executionExecuted === true) {\n    parts.push('neuer Provider-Lauf belegt');\n  } else if (report.executionExecuted === false) {\n    parts.push('kein neuer Provider-Lauf belegt');\n  }\n\n  return parts.length > 0 ? parts.join(' · ') : undefined;\n}\n\n/**\n * Confidence label for dispatch identity. A bound versioned snapshot is\n''',
)

replace_once(
    "apps/web/src/cockpit/WorkPulse.tsx",
    '''          {scoped.recent.map((report, index) => {\n            const executionEvidence = terminalExecutionLine(report);\n            const evidenceStatus = terminalEvidenceStatus(report);\n            return (\n''',
    '''          {scoped.recent.map((report, index) => {\n            const executionEvidence = terminalExecutionLine(report);\n            const evidenceStatus = terminalEvidenceStatus(report);\n            const providerExecution = providerExecutionLine(report);\n            return (\n''',
)

replace_once(
    "apps/web/src/cockpit/WorkPulse.tsx",
    '''                {evidenceStatus && (\n                  <div className="focuscard-counts" aria-label="Status der Ausführungsevidenz">\n                    {evidenceStatus}\n                  </div>\n                )}\n                {executionEvidence && (\n''',
    '''                {providerExecution && (\n                  <div className="focuscard-counts" aria-label="Beobachteter Provider-Lauf">\n                    {providerExecution}\n                  </div>\n                )}\n                {evidenceStatus && (\n                  <div className="focuscard-counts" aria-label="Status der Ausführungsevidenz">\n                    {evidenceStatus}\n                  </div>\n                )}\n                {executionEvidence && (\n''',
)

replace_once(
    "tests/test_bridge_report_execution_evidence.py",
    '''                "bridge_status": "done",\n                "lane": "claude",\n                "agent": "qa-critic",\n                **EXECUTION_EVIDENCE,\n''',
    '''                "bridge_status": "done",\n                "lane": "claude",\n                "agent": "qa-critic",\n                "provider": "claude_cli",\n                "replay": True,\n                "runtime_receipt": {"executed": False},\n                **EXECUTION_EVIDENCE,\n''',
)

replace_once(
    "tests/test_bridge_report_execution_evidence.py",
    '''        "project": "project_tct",\n        "agent": "qa-critic",\n        **EXECUTION_EVIDENCE,\n''',
    '''        "project": "project_tct",\n        "agent": "qa-critic",\n        "provider": "claude_cli",\n        "replay": True,\n        "execution_executed": False,\n        **EXECUTION_EVIDENCE,\n''',
)

replace_once(
    "tests/test_bridge_report_execution_evidence.py",
    '''                    "terminal_receipt_sha256": "c" * 64,\n                },\n                "bridge_status": "failed",\n''',
    '''                    "terminal_receipt_sha256": "c" * 64,\n                    "provider": "request-provider-must-not-be-promoted",\n                    "replay": True,\n                    "runtime_receipt": {"executed": True},\n                },\n                "bridge_status": "failed",\n''',
)

replace_once(
    "tests/test_bridge_report_execution_evidence.py",
    '''    assert brief["agent"] == ""\n    assert brief["runtime_id"] == ""\n''',
    '''    assert brief["agent"] == ""\n    assert brief["provider"] == ""\n    assert brief["replay"] is None\n    assert brief["execution_executed"] is None\n    assert brief["runtime_id"] == ""\n''',
)

replace_once(
    "tests/test_bridge_report_execution_evidence.py",
    '''    for key, value in EXECUTION_EVIDENCE.items():\n        assert rows[0][key] == value\n''',
    '''    for key, value in EXECUTION_EVIDENCE.items():\n        assert rows[0][key] == value\n\n\ndef test_report_brief_keeps_exact_provider_execution_booleans_only(tmp_path):\n    report = tmp_path / "task.report.json"\n    report.write_text(\n        json.dumps(\n            {\n                "request": {"project": "project_tct", "lane": "claude"},\n                "bridge_status": "done",\n                "lane": "claude",\n                "provider": "claude_cli",\n                "replay": "false",\n                "runtime_receipt": {"executed": 0},\n                "report": {"summary": "malformed optional execution mode"},\n            }\n        ),\n        encoding="utf-8",\n    )\n\n    brief = file_bridge._report_brief(report)\n    assert brief["provider"] == "claude_cli"\n    assert brief["replay"] is None\n    assert brief["execution_executed"] is None\n''',
)

replace_once(
    "apps/web/tests/live-report-project-evidence.spec.ts",
    '''      summary: 'verified terminal evidence'\n    });\n  }, project);\n  await expect(pulse).toContainText('bound.report.json');\n''',
    '''      provider: 'claude_cli',\n      replay: true,\n      execution_executed: false,\n      summary: 'verified terminal evidence'\n    });\n  }, project);\n  await expect(pulse).toContainText('bound.report.json');\n''',
)

replace_once(
    "apps/web/tests/live-report-project-evidence.spec.ts",
    '''  const evidenceStatus = pulse.getByLabel('Status der Ausführungsevidenz').first();\n  await expect(evidenceStatus).toContainText('Terminale Evidenz: geschlossen');\n  const observed = pulse.getByLabel('Beobachtete Ausführungsevidenz').first();\n''',
    '''  const providerRun = pulse.getByLabel('Beobachteter Provider-Lauf').first();\n  await expect(providerRun).toContainText('Provider claude_cli · Replay · kein neuer Provider-Lauf');\n  const evidenceStatus = pulse.getByLabel('Status der Ausführungsevidenz').first();\n  await expect(evidenceStatus).toContainText('Terminale Evidenz: geschlossen');\n  const observed = pulse.getByLabel('Beobachtete Ausführungsevidenz').first();\n''',
)

print("patched replay/provider execution visibility")
