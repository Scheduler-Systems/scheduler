# scheduler-ios

Native iOS client for the Scheduler native platform split.

## Owns

Swift/SwiftUI Scheduler app backed by scheduler-api contracts.

## Native Shell

The first shell lives in `Sources/SchedulerApp`. It renders mocked
contract-shaped schedule state from `fixtures/mock-schedule.json` and identifies
manager and worker modes.

## Boundary

No Flutter legacy code and no direct Schedgy service calls except through approved APIs.

## Platform Rules

- Scheduler remains the product umbrella and scheduling system of record.
- Schedgy is the intelligent intake/discovery layer that feeds Scheduler through approved contracts.
- Every route, event, persisted object, log, and external binding must carry tenant identity.
- Manager approval is required before schedule mutation or employee-facing action.
- Agent-network is used only for delegated service tasks with identity, scopes, correlation id, and audit evidence.
- This repo is part of Scheduler issue #1771 and the Scheduler Native Platform Split milestone.

## Related Repos

- https://github.com/Scheduler-Systems/Scheduler
- https://github.com/Scheduler-Systems/schedgy
- https://github.com/Scheduler-Systems/scheduler-contracts
- https://github.com/Scheduler-Systems/scheduler-api
