# E2E Verification

Canonical: docs/E2E_VERIFICATION.md

## Environments

- main: governance and orchestration checks
- pipeline: runnable application snapshot

## Scenario Index

E2E-001: Pipeline app boots and serves content
Related WIs: WI-000 (seed)

## Scenario Template

Scenario ID: E2E-###
Related WIs: WI-###
Preconditions:
Steps:
Expected Results:
Evidence Required:

## E2E-001

Scenario ID: E2E-001
Related WIs: WI-000

Preconditions:
- pipeline branch exists with the seeded app
- Node.js is available in CI runner

Steps:
1) Checkout pipeline branch.
2) Run: node pipeline_app/server.js
3) Fetch: http://127.0.0.1:8080/
4) Verify the response contains "FAVELLA DEVELOPMENT".

Expected Results:
- Server starts and returns index page with expected marker text.

Evidence Required:
- CI job log showing server start and successful fetch.
