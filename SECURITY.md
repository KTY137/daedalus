# Security Policy

Daedalus controls code-writing agents, external runtimes, effects, evidence, and
promotion. Treat suspected bypasses of those boundaries as security-sensitive.

## Report privately

Do not open a normal public issue for:

- unauthorized writes or Primary Checkout mutation;
- Effect Lease, scope, replay, or kill-switch bypasses;
- OwnerApproval or promotion bypasses;
- secret or credential exposure;
- sandbox escape or Docker-socket access;
- evaluator or evidence tampering;
- receipt-ledger corruption that can hide or duplicate an effect;
- unplanned external egress.

Use GitHub's private security reporting for this repository when available, or
contact the repository owner through a private channel. Do not include live
credentials, tokens, private source, or destructive proof-of-concept payloads.

## Initial report contents

Provide:

- exact commit SHA, artifact digest, runtime version, and operating system;
- affected entrypoint, contract, or trust boundary;
- minimal non-destructive reproduction;
- observed and expected result;
- whether an external effect occurred;
- safe containment or disablement steps;
- relevant logs or receipt locators with secrets removed.

## Containment rule

The safe fallback is fail-closed: disable or quarantine the affected runtime,
entrypoint, adapter, or promotion path. Do not restore service by bypassing the
Iron Plan guard, Effect Lease, sandbox, evidence verification, or owner approval.

## Disclosure

Coordinate disclosure with the repository owner after a fix, negative tests,
replay/fault evidence, and review are complete. A passing test alone does not
prove that the affected security boundary is restored.
