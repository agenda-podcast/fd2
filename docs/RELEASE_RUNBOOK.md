# Release Runbook (FD)

Canonical: docs/RELEASE_RUNBOOK.md

## Release readiness criteria
- All included WIs are Accepted.
- CI is green on main.
- E2E Verification executed for release scope.
- Rollback steps present and sanity-checked.
- Known limitations documented.

## Release procedure
1) Create a git tag: fd-YYYYMMDD-N (example: fd-20260225-1)
2) Publish GitHub Release notes:
   - Included PRs and WIs
   - Verification evidence links
   - Known limitations

## Rollback procedure
1) Identify previous known-good tag.
2) Reset deployment target (Pages branch or main) to that tag.
3) Confirm docs/index.html loads and CI is green.

## Release execution record (append-only)
Add a new section per release:
- Release ID / tag:
- Date (America/New_York):
- Included PRs:
- Included WIs:
- Verification evidence:
- Incidents:
- Post-release monitoring summary:
