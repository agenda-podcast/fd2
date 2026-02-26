# FAVELLA DEVELOPMENT (FD) Documentation

Version: 1.1
Canonical location: docs/FD_DOCUMENTATION.md
Applies to: FAVELLA DEVELOPMENT only (FD-only rule)

## 0) FD-Only Rule (Hard Boundary)

This repository and its documentation must not include:
- Any description, architecture, schemas, or workflows belonging to other products.
- Any references to other repos/products as dependencies unless explicitly added as an FD dependency with an ID.

If content is not clearly FD, it does not belong here.

## 1) What FD Is

FD is a GitHub-native, role-driven engineering system that converts ideas into working software via:
- Atomic work items (WI) with single producer and single receiver.
- Deterministic CI enforcement of constraints.
- A clean main branch for governance and orchestration.
- A pipeline branch that contains the runnable application snapshots.
- GitHub Releases as the sole storage for produced artifacts (no generated outputs stored on main).

Docs are the control plane. The product is a working application.

## 2) Non-Negotiable Principles

### 2.1 Small Chunk Deliverable Criteria
A deliverable is acceptable only if it is:
- Atomic: one purpose, one receiver, one clear next step.
- Testable: objective acceptance criteria or verification evidence exists.
- Traceable: references WI and MS IDs.
- Non-ambiguous: receiver can proceed with zero follow-up questions.

### 2.2 1-to-1 Handoff Policy
- Every deliverable has exactly one producer and exactly one receiver.
- If multiple roles contribute, they contribute inputs. One owner publishes the final artifact.

### 2.3 Allowed Loops
Loops are allowed only in:
A) Spec refinement: PM <-> UX
B) Technical feasibility: Tech Lead <-> PM
C) Code review: Engineer <-> Code Reviewer
D) QA verification: QA Lead <-> Engineer

### 2.4 Always Update E2E Verification
Whenever FD adds or changes functionality, scenarios, outputs, releases, schemas, or processes,
E2E Verification must be updated to include new/changed coverage.

### 2.5 File and Content Constraints
- Keep every non-table logic/code file <= 500 lines.
- Do not use ellipses to omit content.
- Use ASCII only unless explicitly exempted.
- Do not change declared production-critical logic without explicit approval where such a rule exists.

## 3) Branch and Artifact Model

### 3.1 Branches
- main: governance, templates, orchestrator, policy checks, GitHub Pages docs UI.
- pipeline: runnable application snapshot. Updated only by automation.

### 3.2 Artifacts
All produced outputs are stored in GitHub Releases.
The repository does not store agent outputs, runner logs, or evidence packs on main.

Each WI execution produces a Release with:
- manifest.json
- artifact.zip (pipeline snapshot or patch)
- runner_log.txt
- verification_report.txt

## 4) Repository Structure

Top-level directories:
- /agent_guides: shared constraints and per-role guides (ASCII .txt)
- /docs: documentation and GitHub Pages UI
- /backlog: milestones and work items
- /src: FD orchestration and tooling code (not the product app)
- /tools: scripts for CI checks and runner utilities
- /.github/workflows: CI and orchestration workflows
- /pipeline_base: seed template for the pipeline branch application (source template, not output)

## 5) Work Item System

A work item is the smallest independently shippable slice.

Canonical template: docs/WI_TEMPLATE.md

Status model:
Draft -> Ready for Receiver -> In Review -> Rework -> Ready for Receiver -> Accepted -> Closed
Only the Receiver can mark Accepted.

## 6) Roles and Responsibilities

See docs/ROLES.md for the role catalog and loop closure rules.

## 7) Verification System

Canonical: docs/E2E_VERIFICATION.md

E2E scenarios must be deterministic, reproducible, and traceable to WIs.
If behavior changes, at least one scenario must be added or updated.

## 8) Change Control and CI Gates

CI must fail deterministically if:
- Any non-table logic/code file exceeds 500 lines.
- Prohibited non-ASCII characters are introduced.
- Ellipses are used to omit content.
- Required docs/templates are missing.

## 9) Releases

Canonical: docs/RELEASE_RUNBOOK.md

A release is allowed only if:
- Included WIs are Accepted.
- CI is green.
- Required E2E verification for scope is executed.
- Rollback steps are present and reproducible.

## 10) GitHub Pages UI

Open docs/index.html locally or via GitHub Pages.
No build tooling is required.

## 11) Pipeline Orchestration

The orchestrator runs in GitHub Actions and:
- Reads a WI.
- Builds a prompt from agent_guides.
- Calls Gemini.
- Validates response via manifest schema.
- Builds artifact.zip and publishes it to a GitHub Release.
- Updates the pipeline branch with the artifact content (when artifact_type is pipeline_snapshot).

### 11.1 Manual start from a Milestone Issue

FD supports a manual start workflow that turns a Milestone Issue into a normalized v1 brief and a set of Work Item issues.

Workflow:
- .github/workflows/orchestrate_milestone.yml

Inputs:
- issue_number: the GitHub Issue number of the Milestone Issue (auto-assigned by GitHub).
- role_guide: ROLE_PM.txt

Required secrets:
- GEMINI_API_KEY

Outputs:
- A GitHub Release FD-MS-XX-PM-YYYYMMDD-HHMMSS
- A comment on the Milestone Issue with the Release tag
- Created Work Item issues based on files under handoff/work_items/

