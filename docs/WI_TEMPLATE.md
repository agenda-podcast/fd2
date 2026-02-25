# Work Item

## Work Item Header
Work Item ID: WI-###
Milestone ID: MS-###
Title: Verb + outcome
Owner Role (Producer): <one role only>
Receiver Role (Next step): <one role only>
Type: Feature / Bug / Tech Debt / Experiment
Priority: P0 / P1 / P2
Target Environment: Local / Dev / Staging / Prod

## Intent and Scope
Problem / Goal (2-3 lines):

In Scope:
- <bullet>
- <bullet>

Out of Scope:
- <bullet>

Assumptions:
- <bullet>

Dependencies (explicit IDs):
- <WI-### or none>

## Acceptance Criteria (Must be objectively testable)
AC1: Given <context>, when <action>, then <outcome>.
AC2:
AC3:
AC4:
AC5:

## Evidence Required
- Code link: PR #
- Test output: CI run link + summary
- Screens: screenshot/video
- API examples: curl / Postman excerpt
- Metrics/Telemetry: event names + triggers

## Definition of Done (Quality Gates)
- All Acceptance Criteria met in the target environment.
- CI passes (build, lint, unit tests; integration tests if applicable).
- No P0/P1 open defects linked to the work item.
- Security and logging basics met (no secrets in logs; errors logged with correlation id).
- Evidence attached (see above).
- Handoff checklist completed.

## Handoff Checklist (Owner -> Receiver)
- Receiver can reproduce verification steps.
- All configuration notes included (env vars, feature flags).
- Any rollback notes included (if deployment-affecting).
- Known limitations explicitly listed.

## Status
Draft -> Ready for Receiver -> In Review -> Rework -> Ready for Receiver -> Accepted -> Closed
Only the Receiver can mark Accepted.
