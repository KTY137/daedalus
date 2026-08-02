# Gate 2 Project Twin closure audit

Status: **open — closure not claimed**

Audited head: `3794d0e251ea31b572dde312f449c928966ce76c`

## Validated evidence

The audited head completed both repository workflows successfully:

- Iron Plan run `30739387155`
- Gate 2 Project Twin run `30739387182`

The implemented stack currently provides:

- revision-exact Project Twin manifests and transitions;
- deterministic Genesis compilation receipts and artifact identities;
- append-only lifecycle verification with replay refusal;
- expected-head compare-and-swap under an exclusive repository writer lock;
- canonical lock ownership records binding host, PID, and random token;
- fail-closed handling for live, foreign-host, malformed, noncanonical, and symlinked locks;
- same-host abandoned-lock reclamation only after the owner is proven absent;
- crash fault points around temporary-file fsync, replace, and directory fsync;
- canonical readback verification after publication;
- Python/hash-seed matrix and isolated wheel installation coverage in the Gate 2 workflow.

## Closure blockers

Gate 2 remains open until the following storage-level durability boundary is implemented and tested:

1. Lock-record writes must not assume that one `os.write` call consumes the complete canonical payload. The writer must loop until all bytes are persisted or fail closed.
2. Lock creation, abandoned-lock reclamation, and owned-lock removal must persist the containing directory entry with directory `fsync` on supported platforms.
3. Fault tests must demonstrate that partial writes cannot produce an accepted lock and that crashes around lock-directory persistence do not permit two concurrent owners.
4. The exact hardened head must pass Iron Plan, the full Gate 2 Python/hash-seed matrix, and isolated wheel installation.

## Gate decision

The semantic ownership and lifecycle contracts are green, but the lock protocol is not yet durable enough for a formal Gate 2 closure claim. Gate 3 must remain stacked behind this blocker.
