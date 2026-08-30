# Branch consolidation arm

Owner-authorized one-shot repository maintenance trigger for 2026-08-30.

Retired without payload execution. Every captured hosted attempt failed before
Step 1 or was skipped, and the later restored workflow copies through
`4877561c` had zero runs while disabled. A later final-runner variant through
`d8e496e8` produced two failed runs with four empty attempts and no allocated
runner. These workflow paths therefore deleted no refs and wrote no recovery
manifest.
Exact run, attempt, job, runner and step metadata is retained in
`BRANCH_CONSOLIDATION_FAILED_RUNS_20260830.json`. Independent post-merge review
found that the #297/#299 implementation bypassed the canonical effect boundary,
could delete a moved branch tip, retained only SHA strings rather than durable
Git refs, and closed PRs before proving that the complete deletion batch was
safe. #300 (`e1ca9aa4`) added exact archive tags, which repaired object
reachability for the observed tips, but it still lacked compare-and-swap ref
deletion, canonical repository-write admission/receipts, rerun retirement, and
an atomic full-batch boundary. #301 and the subsequent direct reintroductions
through `4877561c` did not close those defects. None of those revisions executed
their payload. The effectful workflows, triggers, and runner were therefore
removed. Their six historical Actions runs were deleted after evidence capture
because GitHub otherwise permits privileged re-runs against the original
workflow SHA for 30 days; both restored workflow IDs were disabled before their
YAML was removed. The separate, owner-authorized local consolidation is recorded
in `LOCAL_BRANCH_CONSOLIDATION_20260830.json`; it is not evidence that any of
these workflow payloads executed. This file retains the negative evidence and
must not be treated as an executable authorization.
