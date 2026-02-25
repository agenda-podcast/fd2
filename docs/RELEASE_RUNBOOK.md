# Release Runbook (FD)

Canonical: docs/RELEASE_RUNBOOK.md

## Release Readiness

A release is allowed only if:
- All included WIs are Accepted.
- CI is green on main.
- Required E2E verification for the release scope is executed.
- Rollback steps exist and are reproducible.
- Known limitations are documented.

## Rollback

Rollback of pipeline branch:
1) Identify the last known good Release tag.
2) Download artifact.zip from that Release.
3) Force-update pipeline branch to the contents of artifact.zip via the pipeline sync workflow.
4) Re-run pipeline build workflow.

## Release Execution Record

For each release, capture:
- Release tag
- Included WIs
- Verification evidence references (CI run IDs or logs)
- Incidents and mitigations (if any)
- Post-release monitoring notes
