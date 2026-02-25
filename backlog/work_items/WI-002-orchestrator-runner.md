# Work Item

Work Item ID: WI-002
Milestone ID: MS-000
Title: Implement orchestrator runner to publish artifacts to Releases and sync pipeline branch
Owner Role (Producer): DevOps / Platform Engineer
Receiver Role (Next step): Tech Lead (Architecture / Delivery Lead)
Type: Feature
Priority: P0
Target Environment: CI / main / pipeline

## Intent and Scope

Problem / Goal (2-3 lines):
Need automation that executes WIs via Gemini, validates manifest outputs, publishes Release assets, and updates pipeline branch with runnable snapshot.

In Scope:
- Runner scripts (manifest validation, apply files, zip packaging)
- GitHub Actions workflow to run orchestrator
- Release publishing with artifacts
- Pipeline branch sync from artifact.zip

Out of Scope:
- Product-specific features beyond pipeline seed

Assumptions:
- GEMINI_API_KEY available as GitHub Actions secret
- GITHUB_TOKEN available for Release publishing

Dependencies (explicit IDs):
- WI-001

## Acceptance Criteria (Given/When/Then)

AC1: Given a WI id, when workflow runs, then it builds a prompt and calls Gemini.
AC2: Given a valid manifest output, when workflow completes, then a Release is created with manifest.json and artifact.zip.
AC3: Given artifact_type pipeline_snapshot, when workflow completes, then pipeline branch content matches artifact.zip.
AC4: Given invalid output (missing manifest or schema mismatch), when workflow runs, then it fails deterministically.

## Evidence Required (stored in Release assets)

- Release assets for a test WI run

## Definition of Done (Quality Gates)

- All AC met.
- CI passes.

## Handoff Checklist (Owner -> Receiver)

- Receiver can run workflow_dispatch for a sample WI.
- Receiver can download Release assets and verify pipeline branch update.
