# G1-WEB-01 - Project-scoped live events

## Frozen packet metadata

- Packet ID: `G1-WEB-01`
- Artifact role: `primary`
- Active gate: `1`
- Classification: `ALIGNED`
- Owner: `repository owner`
- Base revision: `da30c3b71d327eb529fce62c89898dc1c80e2cec`
- Dependencies: `G1-IKARUS-14 at da30c3b71d327eb529fce62c89898dc1c80e2cec and the existing canonical file-bridge /api/events projection`
- Promotion authority: no automatic merge, promotion, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Dependency: existing canonical file-bridge inbox/outbox and `/api/events`
## Primary acceptance claim

A project live stream emits the documented numeric queue and in-flight fields
and observes only reports attributed to that exact project.

## Contracts and behavior

**Baseline reproduced.**

`bridge_status(project)` filtered unread reports but counted every inbox report.
`stream_state(project)` selected the globally newest report and serialized
`in_flight` as a JSON boolean despite the frontend's numeric contract. Therefore
a report for project B could advance project A's report counter and event.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Queue field | bridge signal test and TypeScript build | canonical `queue_depth` retained |
| Idle/busy projection | heartbeat signal test | `in_flight` is exactly integer `0` or `1` |
| Project A and B reports coexist | temp-inbox test | totals/latest report are exact per project |
| Unattributed legacy report | filter test | visible globally; never assigned to a project stream |
| Routes/state authority | focused API/build checks | `/api/events` and file-bus artifacts unchanged |
| Provider/network budget | focused tests | zero live starts/calls |

## Scope

Forbidden: no second report store, polling authority, route, watcher, task
identity, or persistent format. The operator's unfiltered bridge status remains
available and historical report files are not rewritten.

## Migration and rollback

Rollback restores only the prior projection. There is no data migration.

## Evidence expected failures and review

No provider or network operation is expected. Independent review must verify
strict project attribution, numeric `in_flight`, canonical `queue_depth`,
and that unattributed legacy reports remain global rather than being assigned
to a project stream.
