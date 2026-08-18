# Gate 0 — Promotion-Trust-Root: konsolidierter Review-Befund (2026-08-18)

Status: BEFUND, verbindlich für die Lane `grind/sealed-approval`. Advisory
in der Herkunft (Momus-Kritik + 10-Slice-codex-only-Council), verbindlich
gemacht durch die Koordinatorin unter Owner-Delegation vom 2026-08-18.

## Der eine Strukturdefekt (fünf Slices konvergieren)

Der Promotion-Trust-Root — Ledger, Keyring UND Mechanismus-Identität — ist
heute **caller-supplied und unverankert**. `promote_candidates` /
`authorize_persisted_promotion` nehmen `approval_ledger` und `owner_keyring`
als gewöhnliche Parameter; die einzige Prüfung an gated_writes.py:202 ist ein
Präsenz-Check (truthy), keine Provenienz. Ein Aufrufer, der beides stellt,
authentifiziert sich gegen sich selbst.

Zwei unabhängige Angriffe wurden konstruiert (codex, verbatim in
`runs/council/council-20260818T10*.jsonl`):

- **Ledger-Replay (Slice 8):** `UNIQUE(owner_id,key_id,nonce)` ist per-DB;
  `verify_consumption` fragt nur die Verifizierer-DB; `ledger_path` wird nur
  bei `None` spine-aufgelöst. Ein zweites vorgeseedetes Ledger mit der
  kopierten Row + passendem Keyring authentifiziert dieselbe consumed
  approval erneut.
- **Trust-Root-Swap (Slice 7):** `VerifiedOwnerApproval` bindet keine
  `approval_mechanism_sha256` — nichts koppelt die Approval an die
  allowed-signers/Keyring-Namespace-Generation. Ein Root-Swap kann als
  gültige Approval durchgehen.

## HMAC ist inhärent symmetrisch (Slice 2, kein in-process-Fix)

Mit geteiltem HMAC-Secret gibt es KEINE in-process-Key-Platzierung, die
Verify-ohne-Sign gewährt: Wer verifizieren kann, kann fälschen. Das heutige
Label `approval_assurance="authenticated"` bei env-var-Root ist deshalb der
§4.9-Ehrlichkeitsverstoß, den das Options-Papier für Option D selbst
verbietet. → Der Fix ist Option B (git-signierte Tags), nicht ein vierter
HMAC-Key.

## Verbindliche Auflagen (Lane grind/sealed-approval)

1. Trust-Root aus dem Aufrufer-Interface entfernen; Autorität = committete
   allowed-signers-Blob + gepinntes Tag-Objekt, nicht ein Argument.
2. `approval_mechanism_sha256` (Digest des Signer-Sets) in den signierten
   Body UND in die Consumption-Re-Verifikation.
3. Option-B-Pins exakt: Trust-Commit-OID + allowed-signers-Blob-Hash
   unabhängig; annotated-tag-OID → Ziel-OID (nicht der mutable Tag-Name);
   Erfolg = NUR Exit 0 von hermetischem `git verify-tag`
   (`GIT_CONFIG_NOSYSTEM`, `GIT_NO_LAZY_FETCH`,
   `gpg.ssh.allowedSignersFile`); fehlende Objekte → fail-closed, nie
   lazy-fetch. „Good git signature" auf stdout ist bedeutungslos.
4. Report-Kopplung explizit: `closed` braucht einen eigenen
   `assurance != authenticated`-Term, statt sich auf das implizite Kippen
   von `security_boundary_claimed` zu verlassen.

## Geklärt, keine Arbeit nötig

- Slice 4: Domain-Separation HÄLT (`contract_type` im signierten Body).
- Slice 9: mögliches CAS-loses TOCTOU-Restfenster zwischen in-lock-Re-Auth
  und `_promote_locked` — am vollen Lock verifizieren (codex argumentierte
  aus einem Ausschnitt).

## Provenienz

Momus-Kritik (read-only) 2026-08-18; 30-Opus→3-Fable-Workflow
(GO-WITH-CHANGES, Linse A bestätigt Existenz der Versiegelung + Spender auf
checkpoint-Branch); 10-Slice-codex-only-Council (alle rc=0, chains intakt,
floor-clean, none degraded, 8530 charged prompt tokens). Bus-Transkripte
append-only unter `runs/council/`.
