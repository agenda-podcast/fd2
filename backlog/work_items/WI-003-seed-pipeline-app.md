# Work Item

Work Item ID: WI-003
Milestone ID: MS-000
Title: Seed pipeline branch with minimal runnable application
Owner Role (Producer): Frontend Engineer
Receiver Role (Next step): QA Lead
Type: Feature
Priority: P0
Target Environment: pipeline

## Intent and Scope

Problem / Goal (2-3 lines):
Pipeline branch must contain a runnable application and its own workflows so FD produces working software.

In Scope:
- Minimal Node.js static server app
- pipeline workflows to verify server boots
- Simple UI page that confirms running

Out of Scope:
- Complex product features

Assumptions:
- Node.js available in GitHub Actions

Dependencies (explicit IDs):
- WI-002

## Acceptance Criteria (Given/When/Then)

AC1: Given pipeline branch, when running node pipeline_app/server.js, then it serves index.html on port 8080.
AC2: Given pipeline workflow, when push happens, then CI verifies GET / returns expected marker string.

## Evidence Required (stored in Release assets)

- CI run log on pipeline branch

## Definition of Done (Quality Gates)

- All AC met.
- pipeline workflow passes.

## Handoff Checklist (Owner -> Receiver)

- QA can run E2E-001 and mark Accepted.
